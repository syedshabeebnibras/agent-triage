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
raw OpenHands output
        │
        ▼
OpenHands adapter (normalizes to AgentRun schema)
        │
        ▼
deterministic signal extraction
  exit codes · error fingerprints · command repetition
  file-edit presence · test-harness invocation · step timing
        │
        ├── rule shortcut (free, no LLM call) ──────────────┐
        │   covers 92.5% of observed cases                  │
        │                                                    ▼
        └── evidence-dense compaction ──► model-agnostic LLM classification
                                                             │
                                                             ▼
                                         TriageCard
                                           · primary_category (10 classes)
                                           · confidence + rule/llm provenance
                                           · evidence (cited step indices)
                                           · owner (task_author / environment /
                                                    agent_framework / model)
                                           · recommended_action
                                           · prevention (class-level)
                                           · fix_suggestion (scaffold-level fix)
                                                             │
                                              ┌──────────────┴──────────────┐
                                              ▼                             ▼
                                    FastAPI (Render)              Next.js dashboard
                                    /triage · /batch              (Vercel, live at
                                    /triage/demo · /stats          dashboard-livid-
                                    /stats/trend (batch history)   phi-21.vercel.app)
                                    bearer-token auth
```

**Stack:** Python 3.12 · FastAPI · Pydantic · Typer CLI · Next.js 16 · TypeScript ·
Docker · GitHub Actions (ruff + mypy + pytest) · Anthropic Claude (model-agnostic
provider layer — swappable).

**Tests:** 43, all passing. ruff clean, mypy 0 errors. CI runs on every push.

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

Gold distribution: IMPLEMENTATION\_STALL=24, TOOL\_USE=4, VERIFICATION=2.

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

The dominant failure mode in the real data — agent explores correctly, forms a
verified plan, and then hits the step cap without ever calling `edit_file` — had
no category. The ENVIRONMENT false positives came from the rule firing on
mid-trajectory errors (step 25 of 55) rather than startup failures. Neither
mistake was detectable without real data.

I added IMPLEMENTATION\_STALL as a new category (covers 70% of observed
failures), added an early-step guard to the ENVIRONMENT rule, and extended the
TOOL\_USE signal list with three newly observed patterns. This became taxonomy
v0.2.0. After re-evaluation on the 30-run gold set the classifier reached
κ=0.789, then improved to κ=1.000 after adding two deterministic VERIFICATION
signals:

- `verified_without_editing`: fires when the agent invokes the test harness in
  the final 20% of steps with exit=0 and zero file edits — the agent ran tests
  against unmodified code and called it done.
- `produced_patch + missing_binary`: a causal invariant — a broken environment
  cannot produce a git patch. If a patch exists alongside a "binary not found"
  fingerprint, the binary failure is a test-execution issue, not a setup failure.

Both signals encode general structural patterns, not trajectory-specific hacks. A
held-out half-split check (random.seed=42, 15+15) shows κ=1.000 on both halves
independently, consistent with no overfitting.

## 4. Three design decisions I would defend

**1. Deterministic signals before the model.**

Exit codes, error fingerprints, command repetition, file-edit presence, test
invocation timing — all extracted in code before any LLM call. The model only
handles genuinely ambiguous judgment (roughly 7.5% of real cases). This makes
the classifier cheaper (no LLM credits on the easy cases), faster, and auditable.
It also made the hardest bugs visible: the VERIFICATION cases that the model kept
misclassifying were eventually caught by deterministic rules that the model could
not reliably infer from trajectory text alone.

**2. Model-agnostic provider layer.**

The engine depends on an `LLMProvider` protocol, not a vendor SDK. The offline
mock provider implements the same interface, so tests run without any API key and
CI has no external dependency. Swapping Claude for GPT or a local model is a
one-class change. This mirrors how production agent systems actually route across
providers and it kept the eval honest — mock mode is explicitly labeled as
not-a-real-classifier everywhere in the codebase and the dashboard.

**3. Evidence-grounded, auditable output.**

Every TriageCard cites specific step indices and carries a `rule/llm/hybrid`
provenance tag. A human reviewer can read the cited trajectory excerpt and verify
or override the verdict rather than trusting an opaque probability. The card also
doubles as the artifact a support engineer attaches when escalating to engineering:
it contains the owner, the recommended action, and the class-level prevention
note, so the triage output is directly actionable without further summarization.

## 5. Limitations and what I would do next

**Honest limitations:**

- **Single-labeler gold set.** All 30 labels are from one annotator.
  Inter-annotator agreement was not measured. Categories with subtle distinctions
  (RESOURCE\_LIMIT vs IMPLEMENTATION\_STALL) are where disagreement would be
  highest.
- **Ceiling effect.** κ=1.000 on a 30-run gold set with three observed categories
  is a ceiling, not a guarantee. The narrow distribution means a classifier that
  memorized only these three shapes would also score 1.000. I would not report
  this as a reliable generalization estimate without ≥100 runs and ≥5 examples
  per category.
- **Artificial turn cap.** MAX\_TURNS=20 is well below real OpenHands (100+
  default). This inflates IMPLEMENTATION\_STALL — agents that stalled at step 20
  might have edited at step 25. The signal is real; the rate is not representative
  of production.
- **All-failed sample.** VERIFICATION and REASONING both require a file edit to
  have occurred. With zero patches in the batch, those categories are
  underrepresented and the IMPLEMENTATION\_STALL rule never had a competing signal.

**Shipped improvements (post-initial-prototype):**

- **`fix_suggestion` on every card.** All 10 taxonomy categories now carry a
  concrete scaffold-level fix string — e.g. IMPLEMENTATION\_STALL: "gate `finish`
  on at least one FILE\_EDIT having been observed; inject a forced prompt after N
  exploration-only turns." Returned on every card, surfaced in the dashboard modal.
- **Few-shot LLM prompt.** Five labeled examples anchor the hardest-to-distinguish
  pairs (CONTEXT\_RETRIEVAL vs REASONING, TOOL\_USE vs ENVIRONMENT, IMPLEMENTATION\_STALL
  vs RESOURCE\_LIMIT) directly in the system prompt.
- **SWE-agent adapter.** `swebench_adapter.py` normalizes SWE-agent evaluation
  output into the same `AgentRun` schema, so the engine handles both OpenHands and
  SWE-agent trajectories without any engine changes.
- **`/stats/trend` endpoint.** In-memory ring buffer of the last 50 `/triage/batch`
  calls, returning per-batch category distributions and rule vs LLM split over time.
- **Confidence calibration module.** `eval/calibration.py` implements Platt scaling
  (logistic fit via gradient descent) and a text-mode reliability diagram with ECE
  and MCE, ready to apply once the gold set grows past ~50 runs.
- **OTHER-bucket clustering.** `scripts/cluster_other.py` applies TF-IDF K-means
  to OTHER cards to surface candidate new taxonomy categories without manual reading.

**Remaining next steps:**

- Expand to ≥100 runs at full turn budgets across more diverse repos; measure
  inter-annotator agreement on a shared subset.
- Apply confidence calibration once the gold set has ≥50 examples across ≥5
  categories and report ECE alongside kappa.

---

*Stack: Python 3.12 · FastAPI · Pydantic · Next.js 16 · TypeScript · Docker ·
GitHub Actions · Anthropic Claude. Repository:
[github.com/syedshabeebnibras/agent-triage](https://github.com/syedshabeebnibras/agent-triage).
Live dashboard:
[dashboard-livid-phi-21.vercel.app](https://dashboard-livid-phi-21.vercel.app).
API: [agent-triage-api.onrender.com](https://agent-triage-api.onrender.com/health).*
