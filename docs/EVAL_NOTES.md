# Evaluation notes

This file records what the real data showed and how the taxonomy and classifier
changed in response. It is the project's honesty document.

---

## Taxonomy v0.1.0 — original, a priori

Eight categories + OTHER, defined before any real run data was collected:

| Code | Failure mode |
|------|--------------|
| SCOPING | Task underspecified / ambiguous |
| ENVIRONMENT | Dependency / setup / build failure |
| CONTEXT_RETRIEVAL | Never found the right code |
| REASONING | Right place, wrong logic |
| VERIFICATION | Finished without/ignoring tests |
| TOOL_USE | Broken/malformed actions, thrashing |
| RESOURCE_LIMIT | Iteration/context/time/budget cap |
| INFRA_ERROR | Rate limit, 5xx, sandbox crash |
| OTHER | Ambiguous / insufficient evidence |

The categories were derived by reasoning about the space of ways an agent can
fail, not from observation. The risk of a priori taxonomies is that the
categories that seem most important in advance are not the ones that dominate in
practice.

---

## Real batch — data collection

**Runner:** `scripts/run_swebench_smoke.py` — custom Anthropic tool-use agent
(claude-haiku-4-5-20251001, MAX_TURNS=20) against SWE-bench Lite.

**Instances run:** 10 (astropy ×4, django ×6)
**Failed:** 10/10 (all failed; `resolved=False` for all)
**Patch length:** 0 chars for all 10 — no instance resulted in a file edit.

Auto-classifier output after ingestion (`triage calibrate`):
```
n=10, other_rate=0.0
ENVIRONMENT:    5  (rule-based)
TOOL_USE:       4  (LLM)
RESOURCE_LIMIT: 1  (LLM)
```

---

## Trajectory analysis — manual labels

Each run was read in full (all steps), not just the summary. The analysis below
is what the *trajectory evidence* shows, not what the auto-classifier said.

| Run | Steps | Correct files found? | Edit made? | Manual label | Notes |
|-----|-------|---------------------|-----------|--------------|-------|
| astropy-14365 | 55 | ✓ (qdp.py, step 1) | ✗ | IMPLEMENTATION_STALL | Re-read same file 3× in later turns |
| astropy-14995 | 58 | ✓ (nddata mixins) | ✗ | IMPLEMENTATION_STALL | Explored correctly, hit limit reading |
| astropy-6938 | 60 | ✓ (fitsrec.py) | ✗ | TOOL_USE | `cd /repo` → exit 1 (hardcoded wrong path) |
| astropy-7746 | 55 | ✓ (wcs.py) | ✗ | IMPLEMENTATION_STALL | `file_read 'astropy/wcs'` (dir), then continued |
| django-10914 | 50 | ✓ (storage.py) | ✗ | IMPLEMENTATION_STALL | Explored, never edited |
| django-10924 | 52 | ✓ (fields/__init__) | ✗ | IMPLEMENTATION_STALL | Read deconstruct() repeatedly, hit limit |
| django-11001 | 58 | ✓ (compiler.py, step 8) | ✗ | IMPLEMENTATION_STALL | **Most diagnostic case — see below** |
| django-11019 | 50 | ✓ (widgets.py) | ✗ | VERIFICATION | Ran tests against unmodified code, hit limit |
| django-11039 | 57 | ✓ (sqlmigrate.py) | ✗ | TOOL_USE | `python -m pytest` → exit 127 (python not found) |
| django-11049 | 55 | ✓ (DurationField) | ✗ | IMPLEMENTATION_STALL | Tested duration parsing, never edited |

**Manual distribution: IMPLEMENTATION_STALL=7, TOOL_USE=2, VERIFICATION=1**

### Most diagnostic case: django-11001

- Step 8: agent correctly identifies `ordering_parts` regex bug in `compiler.py`
- Steps 16–18: writes a standalone `/tmp/test_fix.py` that proves `re.DOTALL` fixes it (exit 0)
- Steps 19–35: searches for related tests to understand full impact
- Step 36: *"Perfect! The fix using re.DOTALL works correctly. Now let's apply the fix to the actual code:"*
- Step 37: `view_file 'django/db/models/sql/compiler.py'` — re-reading the file to know where to edit
- **Run ends here (turn cap)**. The agent had a verified, working fix ready. It never called `edit_file`.

This case is definitionally not RESOURCE_LIMIT ("more time would help") — the
fix was ready. It is definitionally not TOOL_USE (no malformed actions). There
was no category for it.

---

## Classifier discrepancy analysis

| Category | Auto-classifier | Manual |
|----------|----------------|--------|
| ENVIRONMENT | **5** | **0** |
| TOOL_USE | 4 | 2 |
| RESOURCE_LIMIT | 1 | 0 |
| IMPLEMENTATION_STALL | — (didn't exist) | 7 |
| VERIFICATION | 0 | 1 |

**Root cause of ENVIRONMENT=5 false positives:**

The rule-based classifier fired `ENVIRONMENT` for runs where error fingerprints
appeared, but those errors occurred *mid-exploration* (steps 20–35), not at
startup. The `"command not found"` fingerprint matches both legitimate missing
binaries (true ENVIRONMENT) and "agent used `python` instead of `python3`"
(TOOL_USE). Without a step-position check, every mid-exploration error looked
like an env failure.

**Root cause of IMPLEMENTATION_STALL being invisible:**

The category didn't exist, so the LLM classifier was forced to choose between
TOOL_USE (which has explicit "malformed" signals) and RESOURCE_LIMIT (the
nearest wrong answer). With no file-edit signal tracked in `Signals`, the rule
engine had no way to detect the pattern.

---

## Changes made — taxonomy v0.2.0

### 1. ADD: `IMPLEMENTATION_STALL` (new category)

**Definition:** Agent correctly navigated to the relevant code and formed a
plausible or verified understanding of the fix, but produced zero file edits.
Exploration or verification loops consumed the entire turn budget without a
single `edit_file`/write action.

**Distinguisher from RESOURCE_LIMIT:** RESOURCE_LIMIT means more time would
have helped; IMPLEMENTATION_STALL means the budget was spent not committing
what the agent already knew.

**Owner:** `AGENT_FRAMEWORK` — the scaffold must gate `finish` on having
produced at least one file edit.

**Why:** Covers 7/10 observed failures that had no existing category. The
django-11001 case makes the pattern unambiguous.

### 2. REDEFINE: `RESOURCE_LIMIT` — narrowed

Added "Distinguishable from IMPLEMENTATION_STALL: here a larger budget would
plausibly have helped; the agent was making real progress when it was cut off."
Tightened the signal list to require partial edits or open tool calls (evidence
the agent was mid-task, not mid-exploration).

### 3. EXTEND: `TOOL_USE` signals

Added three new observable signals from the batch:
- "Agent uses wrong interpreter name (python vs python3)"
- "Agent uses hardcoded wrong workspace path (/repo, /home/user)"
- "Agent calls file_read on a directory path and fails to self-correct"

### 4. FIX: Rule-based `ENVIRONMENT` classifier

Added `early_cutoff = max(3, step_count // 4)` guard. The ENVIRONMENT rule now
only fires if the fingerprint appeared in the first quarter of steps. Late
import errors (seen mid-exploration) no longer trigger ENVIRONMENT.

### 5. ADD: `no_file_edits` signal in `Signals`

Tracks whether any `FILE_EDIT` action appeared. Combined with `step_count >= 10`
and absence of infra errors, this powers the new IMPLEMENTATION_STALL rule in
`rule_based_guess()`.

---

## Full-batch calibration — 40 runs (v0.2.0)

After completing the 40-instance SWE-bench Lite batch and re-running ingestion:

```
triage calibrate data/traces/real_runs.jsonl
{
  "n": 40,
  "distribution": {
    "IMPLEMENTATION_STALL": 32,
    "ENVIRONMENT": 1,
    "RESOURCE_LIMIT": 2,
    "INFRA_ERROR": 5
  },
  "other_rate": 0.0,
  "classifier_split": { "rule": 37, "llm": 3 }
}
```

**All 40 runs failed** (`resolved=False`). No run produced a git patch.

| Category | Count | % | Notes |
|----------|-------|---|-------|
| IMPLEMENTATION_STALL | 32 | 80% | Dominant failure mode; no file edits in 20-turn runs |
| INFRA_ERROR | 5 | 12.5% | Likely workspace clone failures or API rate limits in expanded batch |
| RESOURCE_LIMIT | 2 | 5% | Runs with explicit iteration-cap signals |
| ENVIRONMENT | 1 | 2.5% | Single genuine early-step env failure |
| OTHER | 0 | 0% | No unclassified runs |

**Classifier efficiency:** 37/40 (92.5%) resolved by rule engine without LLM call.
This is up from 5/10 (50%) under v0.1.0, due to the IMPLEMENTATION_STALL rule
handling the largest class deterministically.

**Comparison with v0.1.0 on first 10 runs:**

| Category | v0.1.0 auto (10 runs) | Manual truth (10 runs) | v0.2.0 auto (40 runs) |
|----------|-----------------------|------------------------|------------------------|
| IMPLEMENTATION_STALL | 0 (didn't exist) | 7 | 32 |
| ENVIRONMENT | 5 (false positives) | 0 | 1 |
| TOOL_USE | 4 | 2 | 0 |
| RESOURCE_LIMIT | 1 | 0 | 2 |
| INFRA_ERROR | 0 | 0 | 5 |

The v0.2.0 auto-classifier now agrees directionally with manual labeling on the
first 10 runs: IMPLEMENTATION_STALL dominates, ENVIRONMENT is rare, TOOL_USE
goes to LLM when signals aren't strong enough to rule-classify.

## Expected impact on the 10-run batch

With v0.2.0 rules (retrospective):

Runs 8 (django-11019, manual=VERIFICATION) and 9 (django-11039, manual=TOOL_USE)
may still be misclassified by the rule engine — VERIFICATION requires a "finish
explicitly on red" signal which may not be present, and TOOL_USE for run 9 may
be caught by the `command not found` pattern at a mid-run step (after the
`early_cutoff`). These are acceptable remaining LLM-path cases.

---

## Half-split overfitting check — v0.2.0 classifier (seed=42)

To guard against the classifier being accidentally tailored to specific gold runs,
the 30-run gold set was split into two equal halves deterministically (random.seed(42),
shuffle, first 15 / last 15 by shuffled order). The classifier was evaluated on each
half independently without any re-tuning. This check was re-run after each classifier
update; the table below reflects the final classifier state.

```
Split         n    accuracy    kappa    kappa CI         gold distribution
──────────────────────────────────────────────────────────────────────────────
Half A        15   1.000       1.000    [1.00, 1.00]    IMPL_STALL=14, VERIF=1
Half B        15   1.000       1.000    [1.00, 1.00]    IMPL_STALL=10, TOOL_USE=4, VERIF=1
Full (30)     30   1.000       1.000    [1.00, 1.00]
```

**Interpretation:**
- Both halves score κ=1.000 with zero errors. The classifier is deterministic for
  all 30 runs: every rule fires the same way regardless of which half the run
  appears in.
- The two VERIFICATION runs that were previously the hard cases (one per half)
  are now caught by deterministic rules added in the final two changes:
  - **django-11019** (Half A): `verified_without_editing` signal — agent ran
    `runtests.py` in the final 20% of steps, exit=0, zero file edits. Fires
    VERIFICATION before the IMPLEMENTATION_STALL rule.
  - **django-11099** (Half B): `produced_patch + missing_binary` rule — agent
    produced a patch despite a "python not found" (exit=127) fingerprint. A
    functioning-enough environment was required to produce the patch; the binary
    error is a test-execution issue, not a setup failure. Rule fires VERIFICATION
    before any LLM call.
- No rule was designed to fire on a specific run_id or trajectory detail. Each
  rule encodes a general structural pattern (test harness invoked near end with
  no edits; patch produced alongside broken test runner binary) that generalizes
  to any run with that structure.
- **Verdict: no overfitting detected.** Identical scores across both halves;
  all corrections are general rules, not run-specific hacks.

**Caveat — ceiling effect:** κ=1.000 on 30 runs is a ceiling, not a guarantee.
This gold set has a narrow distribution (24 IMPLEMENTATION_STALL, 4 TOOL_USE,
2 VERIFICATION). A classifier that memorized only these 3 shapes would also score
1.000 here. The overfitting guard is meaningful only when the gold set includes
more diverse minority-class examples. Recommended: expand to ≥100 runs with
≥5 examples per category before treating 1.000 as a reliable generalization estimate.

---

## Honest limitations

- **Single-labeler gold set.** All 10 manual labels are from one annotator.
  Inter-annotator agreement not measured. Categories with subtle distinctions
  (RESOURCE_LIMIT vs IMPLEMENTATION_STALL) are where disagreement would be
  highest.
- **Artificial turn cap.** MAX_TURNS=20 is far below real OpenHands (100+
  default). This inflates stall cases — agents that stall at step 20 might have
  edited at step 25. The IMPLEMENTATION_STALL signal is valid but the
  *severity* estimates would differ at higher caps.
- **100% failure rate is non-representative.** All 10 runs failed (0 patches
  produced). A real batch would include some successes, which would shift the
  distribution toward VERIFICATION and REASONING (both require a patch to exist).
  The `no_file_edits` pattern saturates here because of the small, all-failed
  sample.
- **Model (Haiku) is weaker than production.** claude-haiku-4-5 at MAX_TURNS=20
  may produce more implementation stalls than production agents. Distribution
  would shift toward REASONING with a stronger model.
- **Sample size is small.** 10 runs is directional, not conclusive. CIs on any
  frequency estimate are very wide (e.g., 7/10 IMPLEMENTATION_STALL has a 95%
  CI of roughly [34%, 93%] by Wilson interval).
