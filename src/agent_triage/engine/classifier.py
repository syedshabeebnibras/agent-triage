"""The triage classifier.

Pipeline for one run:
  1. Extract deterministic signals.
  2. Try a high-precision rule-based shortcut (free, fast, auditable).
  3. If the case is nuanced, compact the trace and ask the LLM to classify
     *over the extracted evidence* (grounded, not from scratch).
  4. Assemble a TriageCard: category + confidence + evidence + owner +
     action + prevention (action/prevention seeded from the taxonomy, the
     root-cause and evidence specialized to this run).

The LLM is constrained to the taxonomy and required to cite step indices, so
its output is auditable. Confidence and the rule/LLM/hybrid provenance are
preserved so downstream eval can measure where accuracy comes from.
"""

from __future__ import annotations

from agent_triage.engine.card import Evidence, TriageCard
from agent_triage.engine.compaction import compact_trace
from agent_triage.engine.signals import extract_signals, rule_based_guess
from agent_triage.llm.provider import LLMProvider, default_provider
from agent_triage.schema.trace import AgentRun
from agent_triage.taxonomy.categories import TAXONOMY, all_codes, get, is_valid

_SYSTEM = """You are a senior support engineer specializing in autonomous \
coding-agent failures. You classify *why* an agent run failed, grounded strictly \
in provided evidence. You never speculate beyond the trace. You always cite the \
specific step indices that justify your classification. You output only JSON."""

# Concrete scaffold-level fixes keyed by category — returned on every card so
# the output is directly actionable without further summarisation.
_FIX_SUGGESTIONS: dict[str, str] = {
    "IMPLEMENTATION_STALL": (
        "Gate `finish` on at least one FILE_EDIT having been observed. "
        "After every N exploration-only turns with no edit, inject a forced prompt: "
        "'You have not modified any files yet. You must now commit to an implementation "
        "and call edit_file.' Consider a mandatory skeleton-edit step after the planning phase."
    ),
    "VERIFICATION": (
        "Gate `finish` on `last_test_exit_code == 0`. If the agent tries to finish "
        "without a passing test run, return an error observation: 'Tests are not passing — "
        "you cannot finish until the relevant tests pass.' Align the agent's test command "
        "with the grading harness command."
    ),
    "TOOL_USE": (
        "Add edit-application validation after every FILE_EDIT: verify the modified file "
        "still parses (Python: `ast.parse`). Detect command repetition — if the same "
        "command fails 3 times with identical output, inject: 'You are repeating the same "
        "failing action. Re-read the file and change your approach.'"
    ),
    "CONTEXT_RETRIEVAL": (
        "Inject a repository map at run start: a structured index of files and exported "
        "symbols so the agent does not have to discover structure from scratch. Add a "
        "pre-run step that runs `find . -name '*.py' | head -100` and pipes the result "
        "into the first context window."
    ),
    "REASONING": (
        "Add a mandatory self-review step before `finish`: require the agent to re-read "
        "the failing test assertion, trace through its own change mentally, and confirm "
        "the fix addresses the specific assertion. Consider routing hard-reasoning tasks "
        "to a stronger model via a complexity pre-filter."
    ),
    "SCOPING": (
        "Introduce a pre-flight task-quality check that rejects tasks missing: "
        "(1) the exact test that should pass, (2) the target file or function, "
        "(3) a reproduction command. Provide task authors with a scoping template "
        "and gate run submission on the checklist."
    ),
    "ENVIRONMENT": (
        "Pin the missing dependency in the sandbox base image or setup script. "
        "Add a pre-run smoke test that verifies the environment imports all required "
        "packages before the agent starts. Snapshot known-good environments per repo "
        "and tag them in the run manifest."
    ),
    "RESOURCE_LIMIT": (
        "Estimate task complexity before starting and scale the turn budget accordingly. "
        "Add context compression every 10 turns to prevent window overflow. "
        "Surface a cost/step estimate to the user before long runs and allow early exit."
    ),
    "INFRA_ERROR": (
        "Add retry logic with exponential backoff for all model provider calls. "
        "Implement multi-provider failover so a 429 or 5xx falls through to a backup "
        "provider. Separate infrastructure failures from quality failures in reliability "
        "dashboards so they are not counted against agent quality."
    ),
    "OTHER": (
        "Flag for human review. Capture the trajectory and attach it as evidence when "
        "filing a taxonomy-gap ticket. If this pattern recurs in 3 or more runs, "
        "promote it to a named category."
    ),
}

_FEW_SHOTS = """
EXAMPLES (few-shot anchors for the hardest-to-distinguish pairs):

--- EXAMPLE A: CONTEXT_RETRIEVAL (never found the right place) ---
Run: agent searches for `warm_start` in `sklearn/ensemble/bagging.py`, finds nothing,
     edits that file anyway, test asserts `IsolationForest` has no `warm_start`.
Key signal: agent never opened `sklearn/ensemble/_iforest.py` (the actual target).
Label: CONTEXT_RETRIEVAL — the agent looked in the wrong place entirely.

--- EXAMPLE B: REASONING (right place, wrong logic) ---
Run: agent opens `django/contrib/auth/validators.py` at step 1, edits the regex
     from `r'^[\\w.@+-]+$'` to `r'^[\\w.@+-]+\\Z'`, test asserts regex still
     matches `'abc\\n'` (because \\Z admits a trailing newline in Python).
Key signal: correct file edited, correct line changed, but the anchor semantics
are subtly wrong. Edit was successfully applied.
Label: REASONING — right place, wrong logic.

--- EXAMPLE C: TOOL_USE (right plan, malformed action) ---
Run: agent correctly identifies the fix in `requests/sessions.py`, attempts to
     apply a patch at step 0, 1, 2 — each time: "hunk #1 FAILED at 428".
     Agent never re-reads the file to get fresh context lines.
Key signal: the plan is sound but the same action is repeated identically 3 times
with the same error. No file edit ever succeeds.
Label: TOOL_USE — right plan, but the action was malformed/thrashing.

--- EXAMPLE D: IMPLEMENTATION_STALL vs RESOURCE_LIMIT ---
IMPLEMENTATION_STALL: agent identifies the fix at step 12, writes a standalone test
     that proves it works (exit=0 at step 16), then re-reads the target file at step
     17 "to know where to edit" — run ends at step 18 (cap). Fix was ready; agent
     never called edit_file.
RESOURCE_LIMIT: agent is mid-edit at cap — has partial changes committed, tool calls
     open, clearly making progress when cut off. More budget would have helped.
Key distinction: did the agent have a ready fix but not commit it (STALL),
or was it genuinely mid-task when cut off (RESOURCE_LIMIT)?

--- EXAMPLE E: ENVIRONMENT vs TOOL_USE (post-edit error) ---
ENVIRONMENT: `ModuleNotFoundError: No module named tomllib` at step 0, before any
     edit. Agent cannot even start the test suite.
TOOL_USE: agent edits `utils.py` at step 5, then `ImportError: cannot import name
     'X' from 'utils'` at step 6. The import error was caused by the edit corrupting
     the file's namespace.
Key distinction: did the error appear before any edit (ENVIRONMENT) or after an
edit that the agent made (TOOL_USE/REASONING)?
"""


def _build_user_prompt(compacted: str) -> str:
    cat_lines = []
    for code in all_codes():
        c = TAXONOMY[code]
        cat_lines.append(f"- {code}: {c.definition}")
    catalog = "\n".join(cat_lines)
    return f"""Classify the root cause of this failed coding-agent run.

FAILURE TAXONOMY (choose primary from these codes only):
{catalog}

{_FEW_SHOTS}

RUN:
{compacted}

Return JSON with exactly these keys:
{{
  "primary_category": "<one taxonomy code>",
  "secondary_category": "<one taxonomy code or null>",
  "confidence": <float 0..1>,
  "root_cause": "<2-4 sentence specific hypothesis grounded in the evidence>",
  "evidence_step_indices": [<int>, ...],
  "evidence_notes": {{"<step_index>": "<why this step is evidence>"}},
  "reasoning": "<brief chain of reasoning>"
}}

Rules:
- primary_category MUST be one of the taxonomy codes above.
- Cite at least one evidence_step_index that actually appears in the trajectory.
- REASONING vs CONTEXT_RETRIEVAL: if the agent opened and edited the correct file
  but the logic in the edit is wrong → REASONING. If the agent never found or opened
  the correct file → CONTEXT_RETRIEVAL.
- TOOL_USE vs REASONING: if the edit was successfully applied but produced wrong
  behaviour → REASONING. If the edit itself failed to apply (patch error, corruption,
  thrashing) → TOOL_USE.
- TOOL_USE vs INFRA_ERROR: NameError or ImportError that appears AFTER a FILE_EDIT
  was caused by the edit — classify as TOOL_USE, not INFRA_ERROR. INFRA_ERROR is
  reserved for API rate limits, 5xx responses, network resets, and sandbox crashes.
- ENVIRONMENT vs TOOL_USE: if the error appears before any file edit → ENVIRONMENT.
  If it appears only after an edit the agent made → TOOL_USE or REASONING.
- IMPLEMENTATION_STALL vs RESOURCE_LIMIT: STALL means the agent had a ready fix but
  never called edit_file. RESOURCE_LIMIT means the agent was mid-task and more budget
  would have helped. No file edits + exploration-only loop → STALL.
- If evidence is genuinely insufficient, use OTHER with low confidence (<0.4)."""


class TriageClassifier:
    """Classifies a single AgentRun into a TriageCard."""

    def __init__(self, provider: LLMProvider | None = None, *, use_rules: bool = True):
        self.provider = provider or default_provider()
        self.use_rules = use_rules

    def classify(self, run: AgentRun) -> TriageCard:
        sig = extract_signals(run)

        # 1. rule-based shortcut for unambiguous, high-precision cases
        if self.use_rules:
            guess = rule_based_guess(sig)
            if guess is not None:
                code, conf, rationale = guess
                return self._card_from_rule(run, sig, code, conf, rationale)

        # 2. LLM classification over compacted, evidence-dense trace
        compacted = compact_trace(run, sig)
        try:
            raw = self.provider.complete_json(
                _SYSTEM, _build_user_prompt(compacted), max_tokens=1200
            )
        except Exception as exc:  # provider failure shouldn't crash a batch
            return self._fallback_card(run, sig, f"Provider error: {exc}")

        return self._card_from_llm(run, sig, raw)

    # ------------------------------------------------------------------ helpers

    def _card_from_rule(self, run, sig, code, conf, rationale) -> TriageCard:
        cat = get(code)
        evidence = [
            Evidence(step_index=s, excerpt=label, why="deterministic fingerprint")
            for s, c, label in sig.error_fingerprints
            if c == code
        ][:3]
        return TriageCard(
            run_id=run.run_id,
            task_id=run.task.task_id,
            agent=run.agent,
            model=run.model,
            primary_category=code,
            confidence=conf,
            classifier="rule",
            root_cause=rationale,
            evidence=evidence,
            owner=cat.typical_owner,
            recommended_action=cat.recommended_action,
            prevention=cat.prevention,
            fix_suggestion=_FIX_SUGGESTIONS.get(code),
            provider="rule-based",
        )

    def _card_from_llm(self, run, sig, raw: dict) -> TriageCard:
        code = str(raw.get("primary_category", "OTHER")).strip().upper()
        if not is_valid(code):
            code = "OTHER"
        cat = get(code)

        secondary = raw.get("secondary_category")
        if secondary is not None:
            secondary = str(secondary).strip().upper()
            if not is_valid(secondary):
                secondary = None

        try:
            conf = float(raw.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))

        # build evidence from cited step indices, attaching real excerpts
        notes = raw.get("evidence_notes", {}) or {}
        step_by_index = {s.index: s for s in run.steps}
        evidence: list[Evidence] = []
        for idx in raw.get("evidence_step_indices", []) or []:
            try:
                i = int(idx)
            except (TypeError, ValueError):
                continue
            step = step_by_index.get(i)
            if step is None:
                continue
            excerpt = step.content[:200] or (
                step.observation.content[:200] if step.observation else ""
            )
            evidence.append(
                Evidence(step_index=i, excerpt=excerpt, why=str(notes.get(str(i), "")))
            )

        return TriageCard(
            run_id=run.run_id,
            task_id=run.task.task_id,
            agent=run.agent,
            model=run.model,
            primary_category=code,
            secondary_category=secondary,
            confidence=conf,
            classifier="llm",
            root_cause=str(raw.get("root_cause", "")).strip() or "(no root cause given)",
            evidence=evidence,
            owner=cat.typical_owner,
            recommended_action=cat.recommended_action,
            prevention=cat.prevention,
            fix_suggestion=_FIX_SUGGESTIONS.get(code),
            provider=self.provider.name,
        )

    def _fallback_card(self, run, sig, reason: str) -> TriageCard:
        cat = get("OTHER")
        return TriageCard(
            run_id=run.run_id,
            task_id=run.task.task_id,
            agent=run.agent,
            model=run.model,
            primary_category="OTHER",
            confidence=0.0,
            classifier="llm",
            root_cause=f"Classification unavailable: {reason}",
            evidence=[],
            owner=cat.typical_owner,
            recommended_action=cat.recommended_action,
            prevention=cat.prevention,
            fix_suggestion=_FIX_SUGGESTIONS.get("OTHER"),
            provider=getattr(self.provider, "name", "unknown"),
        )
