# Building this in Antigravity — the complete prompt playbook

This is the step-by-step process to take the scaffold in this repo and finish it
into the real, deployed, evaluated project — driven from Antigravity (or any
agentic IDE). Each prompt is written to be pasted directly. They're ordered by the
three-week plan. Run them in sequence; each assumes the previous ones are done.

**How to use this file:** paste one prompt, let the agent work, review its diff,
run the verification command listed under the prompt, then move on. Don't batch
multiple prompts — review between each so you stay in control of the codebase and
can actually speak to every line in an interview.

> Note on framing: keep your public writeup focused on the artifact and the
> engineering, not on which IDE you used. The work is what matters.

---

## Week 1 — real data + taxonomy validation

### 1.1 — Get the repo running locally

```
Set up this repo locally. Create a Python 3.12 virtualenv, install the package
with `pip install -e ".[dev]"`, run `python scripts/generate_fixtures.py`, then
run `pytest`. Confirm all tests pass and `triage classify
data/traces/example_run.json` produces output. Report the test count and any
failures. Do not change application logic — only fix environment/setup issues if
something doesn't run.
```
Verify: `pytest` is green, `triage --help` works.

### 1.2 — Stand up OpenHands and generate a first small batch

```
I want to generate real failed coding-agent traces using OpenHands on SWE-bench
Lite. Read docs/RUNBOOK_OPENHANDS.md. Install OpenHands, configure it to use my
ANTHROPIC_API_KEY (read it from the environment, never hardcode it), and run its
SWE-bench evaluation harness on 10 instances of SWE-bench Lite as a smoke test.
Keep the per-task cost low. Report where the output.jsonl lands and show me one
example trajectory record so I can see the shape. Stop before scaling up.
```
Verify: an `output.jsonl` exists with `history`, `git_patch`, and resolution info.

### 1.3 — Wire the ingestion script

```
Using the template in docs/RUNBOOK_OPENHANDS.md section 4, create
scripts/ingest_openhands.py that converts the OpenHands output.jsonl into
normalized AgentRun JSONL at data/traces/real_runs.jsonl, keeping only failed
runs. Use the existing agent_triage.harness.openhands_adapter — do not write a new
parser. After running it, print how many total runs there were and how many
failed. Then run `triage calibrate data/traces/real_runs.jsonl` and show me the
category distribution and OTHER rate.
```
Verify: `real_runs.jsonl` populated; calibration prints a distribution.

### 1.4 — Scale the batch to a useful size

```
Now scale the OpenHands run to ~40 SWE-bench Lite instances (mind the cost; stop
and tell me if projected spend exceeds $10). Re-run ingestion. I want at least
~20 failed runs to triage. Report the final failed-run count and the updated
calibration distribution.
```
Verify: ~20+ failed runs in `real_runs.jsonl`.

### 1.5 — Validate the taxonomy against real failures (the honest step)

```
Read 15–20 of the failed runs in data/traces/real_runs.jsonl (open the
trajectories, not just the IDs). For each, tell me which taxonomy category in
src/agent_triage/taxonomy/categories.py you think it is, and flag any run that
doesn't fit cleanly. Then give me a report: (a) does any category never appear,
(b) is any single category swallowing most failures, (c) are there recurring
patterns in the runs that don't fit existing categories. Recommend concrete
taxonomy changes (add/merge/redefine a category) with justification. Do NOT change
the taxonomy yet — just propose.
```
Verify: you get a written taxonomy-validation report. Read it yourself and decide.

### 1.6 — Apply taxonomy revisions (only if 1.5 justified them)

```
Apply the taxonomy changes we agreed on to src/agent_triage/taxonomy/categories.py.
Bump TAXONOMY_VERSION appropriately (semver: new category = minor bump). Update the
taxonomy table in README.md to match. Update any tests that assert specific codes.
Run pytest and confirm green. Then write docs/EVAL_NOTES.md documenting: the
original taxonomy, what real data showed, and exactly what changed and why.
```
Verify: `pytest` green; `docs/EVAL_NOTES.md` tells the before/after story.

---

## Week 2 — real classification + calibrated evaluation

### 2.1 — Run real LLM classification end to end

```
With ANTHROPIC_API_KEY set, run `triage batch data/traces/real_runs.jsonl --out
data/traces/real_cards.jsonl`. This uses the real Claude provider, not the mock.
Show me three example cards (one rule-classified, one LLM-classified, one OTHER if
present). Sanity-check that the evidence step indices actually exist in each run's
trajectory and that the root causes are specific, not generic. Flag any card where
the evidence doesn't support the verdict.
```
Verify: real cards produced; evidence indices are real; root causes are specific.

### 2.2 — Hand-label the gold set

```
Help me build a gold set. Pick 30 failed runs from data/traces/real_runs.jsonl
spanning as many categories as possible. For each, show me the compacted
trajectory (use agent_triage.engine.compaction.compact_trace) and your suggested
label with a one-line reason, then let me confirm or override. Write the confirmed
labels to data/gold/real_gold.jsonl in the GoldLabel JSONL format. I am the final
labeler — record labeler as my name. Use the labeling tips in the runbook to keep
CONTEXT_RETRIEVAL/REASONING/TOOL_USE/VERIFICATION distinct.
```
Verify: `data/gold/real_gold.jsonl` has ~30 labels you personally confirmed.

### 2.3 — Run the real evaluation

```
Run `triage eval data/traces/real_runs.jsonl data/gold/real_gold.jsonl`. Show me
the accuracy, Cohen's kappa (with bootstrap CI), and per-class precision/recall/F1.
Then read eval_report.json's confusion matrix and tell me the top two
misclassification pairs. For each, look at the specific runs that were
misclassified and hypothesize why (is it a prompt problem, a genuinely ambiguous
case, or a real classifier weakness?).
```
Verify: you have real numbers (accuracy + kappa) on real data. This is the headline result.

### 2.4 — Improve the classifier where the eval shows weakness

```
Based on the confusion matrix, improve the classifier without overfitting to the
gold set. Options to consider: sharpen the category definitions sent in the prompt,
add a disambiguation instruction for the most-confused pair, or add a deterministic
signal that distinguishes them (e.g. a stronger "edited the file the test imports"
check for CONTEXT_RETRIEVAL vs REASONING). Make ONE change at a time, re-run the
eval, and report whether kappa improved. Keep changes that help, revert ones that
don't. Show me the before/after kappa for each.
```
Verify: kappa improves and you can explain each change.

### 2.5 — Add a held-out check (guard against overfitting)

```
Split the gold set into two halves deterministically (seeded). Re-run the eval on
each half separately and report whether accuracy/kappa are similar across halves.
If they diverge a lot, the classifier may be overfit to specific runs — tell me.
Add this as a documented check in docs/EVAL_NOTES.md.
```
Verify: consistent metrics across halves; documented.

---

## Week 3 — deploy + polish + writeup

### 3.1 — Deploy the API

```
Deploy the FastAPI backend. Use the Dockerfile and render.yaml in the repo. Walk
me through deploying to Render (or Fly.io): build the image, set the
ANTHROPIC_API_KEY env var in the dashboard, confirm /health returns ok and not
mock_mode. Give me the public API URL.
```
Verify: `curl https://<api>/health` returns `"mock_mode": false`.

### 3.2 — Deploy the dashboard

```
Deploy the Next.js dashboard in dashboard/ to Vercel. Set NEXT_PUBLIC_API_BASE to
the deployed API URL so the dashboard pulls live verdicts. Confirm the build
passes and the live site loads, the distribution renders, and clicking a card
opens the modal with real evidence. Give me the public dashboard URL. If the live
API is slow or rate-limited, make sure the dashboard still degrades gracefully to
the bundled demo data.
```
Verify: live dashboard loads; cards show real triaged runs.

### 3.3 — Replace demo data with real triaged runs

```
Regenerate the dashboard's bundled demo data (dashboard/lib/demoData.ts) from the
REAL triaged cards in data/traces/real_cards.jsonl, so even the offline fallback
shows genuine results. Keep the clear "sample of real triaged runs" labeling.
Rebuild and confirm the dashboard still works.
```
Verify: dashboard shows real cards even with the API off.

### 3.4 — Final quality pass

```
Do a full quality pass: run ruff, mypy, and pytest and fix anything that's not
clean. Confirm test coverage is >=70%. Check the README is accurate to the current
code (taxonomy table, commands, claims). Make sure no API key is committed
anywhere (grep the repo). Confirm the "illustrative/real" labeling is honest
everywhere. Report a final checklist.
```
Verify: everything green; no secrets; honest labeling.

### 3.5 — Write the teardown

```
Write docs/WRITEUP.md: a 1–2 page teardown of this project aimed at a hiring
audience. Structure: (1) the problem — agent failure investigation is slow and
manual; (2) what I built — the pipeline, with the architecture diagram; (3) the
honest result — real numbers on real OpenHands traces, including kappa and the
taxonomy-validation story; (4) the three design decisions I'd defend (deterministic
signals first, model-agnostic provider, evidence-grounded auditable output); (5)
limitations and what I'd do next. Keep it factual and specific — cite the real
metrics from eval_report.json. No hype, no claims I can't back.
```
Verify: a writeup you can attach to an application and defend line by line.

---

## After the build: how to present it

- **Lead with one fully-worked real example**, not the architecture. Show a real
  failed OpenHands run, then the triage card, then the evidence that grounds it.
  The worked example proves you can do root-cause analysis; the system proves you
  can scale it.
- **State the honest numbers.** "On N real OpenHands failures, the classifier
  agrees with my hand labels at kappa = X; rules handle the unambiguous Y% for
  free." Real and modest beats impressive and unverifiable.
- **Frame it as helping the support function**, not grading the product. "A tool I
  built to make agent-failure investigation faster and more systematic" — not
  "here's everything wrong with the agent."
- **Don't claim product access you don't have.** You used OpenHands as an open
  stand-in for the category; say so. It's more credible, not less.
```
