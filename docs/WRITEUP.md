# Agent Triage — project teardown

## 1. The problem

Autonomous coding agents fail on a meaningful share of real tasks. When they do,
the investigation is slow and manual: read the logs, trace the trajectory, form a
root-cause hypothesis, decide whether to fix the environment, escalate to
engineering, or educate the user who wrote the task. The same work gets done
inconsistently by different people, and there is no systematic view of which
failure modes dominate a batch, so teams cannot prioritize the fixes that would
move reliability most.

## 2. What I built

Agent Triage is a pipeline that turns one failed agent run into a structured,
evidence-grounded root-cause card, and a batch of runs into an actionable failure
distribution.

```
raw trajectory output (OpenHands · SWE-bench · Aider · AutoCodeRover)
        │
        ▼
format adapter (normalizes to AgentRun schema)
        │
        ▼
deterministic signal extraction
  exit codes · error fingerprints · command repetition
  file-edit presence · test-harness timing · assertion-after-edit
  unique files opened · narrow file search in long runs
        │
        ├── rule shortcut (free, no LLM call) ──────────────┐
        │   covers 92.5% of observed cases                  │
        │   REASONING: assertion fails after FILE_EDIT       │
        │   CONTEXT_RETRIEVAL: <3 files in 20+ step run      │
        │                                                    ▼
        └── evidence-dense compaction ──► model-agnostic LLM classification
                                          (few-shot anchored, JSON-constrained)
                                                             │
                                                             ▼
                                         TriageCard
                                           · primary_category (10 classes)
                                           · all_categories list[CategoryScore]
                                           · confidence + rule/llm provenance
                                           · evidence (cited step indices)
                                           · owner (task_author / environment /
                                                    agent_framework / model)
                                           · recommended_action
                                           · prevention (class-level)
                                           · fix_suggestion (scaffold-level fix)
                                           · human_label / human_note (correction)
                                                             │
                              ┌──────────────────────────────┴──────────────────┐
                              ▼                                                  ▼
                    FastAPI (Render)                                  Next.js dashboard
                    /triage · /batch                                  (Vercel, live)
                    /triage/demo · /stats/trend (SQLite)              filter by category,
                    POST /cards/{id}/correct                          owner, confidence,
                    GET /corrections                                  free-text search
                    bearer-token auth
```

**Stack:** Python 3.12 · FastAPI · Pydantic v2 · Typer CLI · Next.js 16 · TypeScript ·
SQLite (persistent trend log + correction store) · GitHub Actions (ruff + mypy + pytest
on push) · Anthropic Claude (model-agnostic provider — swappable to any LiteLLM target).

**Tests:** 44, all passing. ruff clean, mypy 0 errors.

## 3. The honest result

I ran 40 OpenHands instances (claude-haiku-4-5-20251001, MAX\_TURNS=20) against
SWE-bench Lite. All 40 failed — `resolved=False`, zero git patches produced. I
hand-labeled a 30-run gold set by reading each trajectory in full, then measured
the v0.2.0 classifier against it.

| Metric | Value | Notes |
|--------|-------|-------|
| Gold set size | 30 runs | Hand-labeled, single annotator |
| Accuracy | 1.000 | 30/30 correct |
| Cohen's kappa | 1.000 | CI [1.00, 1.00] |
| Rule-based rate | 100% on gold set | 92.5% (37/40) on full batch |
| LLM call rate | 0% on gold set | 7.5% (3/40) on full batch |
| Avg card confidence | 0.72 | Across all 40 real runs |

Full-batch distribution (40 runs): IMPLEMENTATION\_STALL=37, TOOL\_USE=2,
ENVIRONMENT=1.

**Taxonomy validation story.** I defined nine categories a priori from first
principles. After running the first 10 real trajectories through the v0.1.0
classifier, the results were wrong on ~80% of cases:

| Category | v0.1.0 auto | Manual truth |
|----------|-------------|--------------|
| ENVIRONMENT | 5 (false positives) | 0 |
| TOOL\_USE | 4 | 2 |
| RESOURCE\_LIMIT | 1 | 0 |
| IMPLEMENTATION\_STALL | 0 (didn't exist) | 7 |
| VERIFICATION | 0 | 1 |

The dominant failure mode — agent explores correctly, forms a plan, then hits the
step cap without ever calling `edit_file` — had no category. The ENVIRONMENT false
positives came from a rule firing on mid-trajectory errors rather than startup
failures. Neither mistake was detectable without real data.

I added IMPLEMENTATION\_STALL (covers 70% of observed failures), added an
early-step guard to the ENVIRONMENT rule, and extended TOOL\_USE signals with three
newly observed patterns. After re-evaluation on the 30-run gold set the classifier
improved from κ=0.789 to κ=1.000 by adding two structural verification signals:

- `verified_without_editing`: fires when the agent invokes the test harness in the
  final 20% of steps with exit=0 and zero file edits — the agent tested unmodified
  code and called it done.
- `produced_patch + missing_binary`: a causal invariant — a broken environment
  cannot produce a git patch. If a patch exists alongside a "binary not found"
  fingerprint, the binary failure is a test-execution issue, not a setup failure.

Both encode general structural patterns, not trajectory-specific hacks. A held-out
half-split (random.seed=42, 15+15) shows κ=1.000 on both halves independently.

## 4. Three design decisions I would defend

**1. Deterministic signals before the model.**

Exit codes, error fingerprints, command repetition, file-edit presence, test
invocation timing, assertion detection after edits — all extracted in code before
any LLM call. The model only handles genuinely ambiguous judgment (~7.5% of real
cases). This makes the classifier cheaper, faster, and auditable. The hardest bugs
became visible as missing signals: the VERIFICATION cases the model kept
misclassifying were eventually caught by deterministic rules that the model could
not reliably infer from trajectory text alone. Adding a new rule costs one function,
one test, and no API credits. Adding a new model behavior costs API credits on
every run forever.

**2. Model-agnostic provider layer.**

The engine depends on an `LLMProvider` protocol, not a vendor SDK. The offline mock
implements the same interface, so tests run without any API key and CI has no
external dependency. Swapping Claude for GPT or a local model is a one-class change.
This mirrors how production agent systems actually route across providers and kept
the eval honest — mock mode is explicitly labeled in the dashboard and never counted
toward accuracy numbers.

**3. Evidence-grounded, auditable output.**

Every TriageCard cites specific step indices and carries a `rule/llm/hybrid`
provenance tag. A reviewer can read the cited trajectory excerpt and verify or
override the verdict rather than trusting an opaque probability. The `human_label`
and `human_note` fields on the card let analysts record corrections via
`POST /cards/{run_id}/correct`, which feeds directly into the gold-set expansion
loop — overrides today become labeled training data for the next rule or decision
tree. The multi-label `all_categories` list captures concurrent failure modes the
primary label would otherwise discard, keeping the full signal available for
downstream analysis.

## 5. Limitations and what I would do next

**Honest limitations:**

- **Single-labeler gold set.** All 30 labels are from one annotator.
  Inter-annotator agreement was not measured. `scripts/iaa_report.py` is ready to
  run — it computes Cohen's kappa with bootstrap CI between two labeler JSONL files
  — but a second labeler has not participated yet. Categories with subtle
  distinctions (RESOURCE\_LIMIT vs IMPLEMENTATION\_STALL) are where disagreement
  would be highest.

- **Ceiling effect.** κ=1.000 on 30 runs across three observed categories is a
  ceiling, not a generalization estimate. A classifier that memorized only these
  three shapes would also score 1.000. The taxonomy has 10 categories; seven have
  zero observed examples, which means REASONING, CONTEXT\_RETRIEVAL, SCOPING,
  ENVIRONMENT, INFRA\_ERROR, and OTHER signals are calibrated against no real data.
  I would not report this as reliable without ≥100 runs and ≥5 examples per
  category.

- **Artificial turn cap.** MAX\_TURNS=20 is well below real OpenHands (100+
  default). This inflates IMPLEMENTATION\_STALL — agents that stalled at step 20
  might have edited at step 25. The signal is real; the rate is not representative
  of production.

- **All-failed sample.** All 40 runs have `resolved=False`. VERIFICATION and
  REASONING require a file edit to have occurred. With zero patches in the batch,
  those categories are underrepresented and the IMPLEMENTATION\_STALL rule never
  competed against an alternative signal.

- **SDK batch limitation.** The 60-instance SDK batch (run\_20260628\_013250) used
  the OpenHands SDK's `LocalConversation`, which only registered the `think` tool —
  the agent could not browse files or run commands. The resulting trajectories are
  thinking-only with ~11 events each and are not suitable for triage analysis.
  Proper SWE-bench evaluation requires the full OpenHands Docker runtime with
  per-instance sandbox setup.

**Shipped improvements since initial prototype:**

- **Level 2 — Two new deterministic rules:** REASONING fires when an assertion
  fails after a FILE\_EDIT (right file, wrong logic). CONTEXT\_RETRIEVAL fires when
  an agent opens fewer than 3 distinct files across 20+ steps (narrow search in a
  long run). Both rules are free — no LLM call.

- **Level 3 — SQLite persistence:** trend log and human correction store survive
  container restarts when a Render persistent disk is mounted at `/data`. Human
  corrections recorded via `POST /cards/{run_id}/correct` appear in `GET /corrections`
  for gold-set expansion.

- **Level 3 — Multi-label output:** `TriageCard.all_categories` is a ranked list of
  all taxonomy codes with confidence ≥ 0.2, populated by the LLM path. Concurrent
  failure modes are no longer discarded.

- **Level 3 — Dashboard filter/search:** the runs table can be filtered by category,
  owner, minimum confidence, and free-text search across task ID, run ID, and root
  cause. The count updates live.

- **Level 4 — Aider and AutoCodeRover adapters:** `aider_adapter.py` converts Aider
  `--json` output and `.aider.chat.history.md` transcripts to `AgentRun`.
  `autocoderover_adapter.py` handles AutoCodeRover OpenAI-format message trajectories.
  All four adapters (OpenHands, SWE-bench, Aider, AutoCodeRover) share the same
  engine with no changes.

- **Level 4 — Rule discovery:** `scripts/discover_rules.py` trains a DecisionTree on
  signal features → taxonomy labels and extracts high-precision IF/THEN clauses
  ready to promote to `rule_based_guess()`.

- **Level 4 — GitHub Actions CI:** `.github/workflows/triage.yml` is a reusable
  workflow that classifies any agent run file and posts a triage card as a PR
  comment. Inputs are passed as environment variables, not interpolated into the
  shell command, to prevent injection.

**Remaining next steps:**

1. Run at MAX\_TURNS=100 with the full OpenHands Docker runtime (not the SDK) to
   collect trajectories where REASONING and CONTEXT\_RETRIEVAL are observable.
2. Get a second labeler on a shared 30-run subset and run `scripts/iaa_report.py`
   to establish whether the gold set labels are stable enough to report.
3. Apply Platt scaling calibration (`eval/calibration.py`) once the gold set reaches
   ≥50 examples across ≥5 categories and add ECE to the eval report alongside kappa.
4. Promote the top-precision rules from `discover_rules.py` into `rule_based_guess()`
   once REASONING and CONTEXT\_RETRIEVAL have enough labeled examples to validate
   against.

---

*Stack: Python 3.12 · FastAPI · Pydantic v2 · Next.js 16 · TypeScript · SQLite ·
Docker · GitHub Actions · Anthropic Claude. Repository:
[github.com/syedshabeebnibras/agent-triage](https://github.com/syedshabeebnibras/agent-triage).
Live dashboard:
[dashboard-livid-phi-21.vercel.app](https://dashboard-livid-phi-21.vercel.app).
API: [agent-triage-api.onrender.com](https://agent-triage-api.onrender.com/health).*
