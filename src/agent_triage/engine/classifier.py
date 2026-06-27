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


def _build_user_prompt(compacted: str) -> str:
    cat_lines = []
    for code in all_codes():
        c = TAXONOMY[code]
        cat_lines.append(f"- {code}: {c.definition}")
    catalog = "\n".join(cat_lines)
    return f"""Classify the root cause of this failed coding-agent run.

FAILURE TAXONOMY (choose primary from these codes only):
{catalog}

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
- primary_category MUST be one of the taxonomy codes.
- Cite at least one evidence_step_index that actually appears in the trajectory.
- Distinguish REASONING (right place, wrong logic) from CONTEXT_RETRIEVAL
  (never found the right place) and from TOOL_USE (right plan, broken actions).
- TOOL_USE vs INFRA_ERROR: NameError, ImportError, or "undefined name" that appears
  AFTER a FILE_EDIT action is caused by the edit corrupting the file — classify as
  TOOL_USE, not INFRA_ERROR. INFRA_ERROR is reserved for API rate limits, 5xx
  responses, network resets, and sandbox crashes that have nothing to do with any
  edit the agent made.
- TOOL_USE vs ENVIRONMENT: if the agent successfully made at least one file edit
  and errors appear only during post-edit testing, the failure is in the edit
  quality (TOOL_USE or REASONING), not in the environment setup (ENVIRONMENT).
  Reserve ENVIRONMENT for setup failures that occur before any meaningful work.
- TOOL_USE vs ENVIRONMENT: if the agent successfully made at least one file edit
  and errors appear only during post-edit testing, the failure is in the edit
  quality (TOOL_USE or REASONING), not in the environment setup (ENVIRONMENT).
  Reserve ENVIRONMENT for setup failures that occur before any meaningful work.
- If evidence is genuinely insufficient, use OTHER with low confidence."""


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
            provider=getattr(self.provider, "name", "unknown"),
        )
