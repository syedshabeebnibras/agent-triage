# Agent Triage

**Root-cause analysis for autonomous coding-agent runs.**

When a coding agent (Devin, OpenHands, SWE-agent) fails a task, "it failed" is
not useful. The useful questions are: **why** did it fail, **who** should fix it,
and **how do we stop the whole class of failure**. Agent Triage answers those
questions automatically — it ingests a failed run, classifies the failure against
an ownership-tagged taxonomy, grounds the verdict in specific trajectory steps,
and emits a reusable playbook card.

That card is the exact artifact a support / deployed engineer attaches when
escalating to engineering or educating a customer.

> **Status:** working prototype. The taxonomy is **v0.2.0 — empirically validated**
> against 30 real SWE-bench Lite run trajectories (Cohen's κ = 1.000 on the full gold
> set; held-out half-split check shows no overfitting). v0.2.0 added `IMPLEMENTATION_STALL`
> and tightened the `RESOURCE_LIMIT` / `ENVIRONMENT` rule-based classifier based on
> observed false-positive patterns (see `docs/EVAL_NOTES.md`).

---

## Why this exists

Autonomous coding agents fail on a meaningful fraction of real tasks, and the
investigation work — reading logs, tracing the trajectory, forming a root-cause
hypothesis, deciding whether to escalate or educate — is slow, manual, and
inconsistent. Agent Triage turns that into a fast, systematic, auditable pipeline,
and turns a batch of failures into a distribution you can act on (which failure
modes dominate? what share is escalate-to-eng vs educate-the-user?).

## Architecture

```
 raw agent output                normalized                 triage
 (OpenHands / SWE-agent)   ─►   AgentRun schema   ─►   ┌──────────────────────┐
        adapters                (agent-agnostic)        │ 1. deterministic     │
                                                        │    signal extraction │
                                                        │ 2. rule-based        │
                                                        │    shortcut (free)   │
                                                        │ 3. evidence-dense    │
                                                        │    compaction        │
                                                        │ 4. model-agnostic    │
                                                        │    LLM classification│
                                                        └─────────┬────────────┘
                                                                  ▼
                                                          TriageCard (category,
                                                          confidence, evidence,
                                                          owner, action, prevention)
                                                                  ▼
                                  FastAPI  ◄──────────────────────┤
                                  Next.js dashboard  ◄────────────┘
                                  calibrated eval (kappa + bootstrap CIs)
```

### Design principles

1. **Never ask the model to do what code can do deterministically.** Exit codes,
   error fingerprints, command repetition, premature-finish, whether tests ran —
   all extracted in code. The LLM only does the genuinely ambiguous judgment.
   Cheaper, faster, auditable.
2. **Model-agnostic by design.** The engine depends on an `LLMProvider` protocol,
   not a vendor SDK. Swap Claude → GPT → a local model with one class. (This
   mirrors how production agent systems route across providers.)
3. **Evidence-grounded, not magic.** Every card cites specific step indices and
   carries a `rule` / `llm` / `hybrid` provenance tag. A human can verify the
   verdict instead of trusting it.
4. **Honest about what's measured.** The offline mock provider is loudly labeled
   as not-a-real-classifier. Real accuracy comes from a real provider on real
   traces, reported with Cohen's kappa and bootstrap confidence intervals.

## The failure taxonomy

Nine categories plus a catch-all, each tagged with the **owner** of the fix —
which maps directly onto the support decision (educate the user / fix the
environment / escalate to engineering / route to a different model):

| Code | Failure mode | Typical owner |
|------|--------------|---------------|
| `SCOPING` | Task underspecified / ambiguous | Task author |
| `ENVIRONMENT` | Dependency / setup / build failure | Environment / infra |
| `CONTEXT_RETRIEVAL` | Never found the right code | Agent framework |
| `REASONING` | Right place, wrong logic | Model |
| `VERIFICATION` | Finished without/ignoring tests | Agent framework |
| `TOOL_USE` | Broken/malformed actions, thrashing, wrong command names | Agent framework |
| `RESOURCE_LIMIT` | Budget cap hit mid-task; more budget would have helped | Agent framework |
| `IMPLEMENTATION_STALL` | Understood the fix but never called edit_file | Agent framework |
| `INFRA_ERROR` | Rate limit, 5xx, sandbox crash | Environment / infra |
| `OTHER` | Ambiguous / insufficient evidence | Unclassified |

## Quickstart

```bash
# 1. install
pip install -e ".[dev]"

# 2. generate the demo fixtures + gold set
python scripts/generate_fixtures.py

# 3. classify a single run
triage classify data/traces/example_run.json

# 4. evaluate against the gold set (Cohen's kappa, per-class F1, bootstrap CIs)
triage eval data/traces/demo_runs.jsonl data/gold/demo_gold.jsonl

# 5. run the API
triage serve         # http://localhost:8000/docs

# 6. run the dashboard
cd dashboard && npm install && npm run dev
```

Without an `ANTHROPIC_API_KEY`, the system runs in **mock mode** (deterministic
offline provider) so everything is runnable for free. Set the key to enable real
LLM classification:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Generating real traces

The honest version of this project is evaluated on **real** OpenHands failures,
not fixtures. See [`docs/RUNBOOK_OPENHANDS.md`](docs/RUNBOOK_OPENHANDS.md) for the
end-to-end process: run OpenHands on a SWE-bench subset, normalize the output with
the adapter, hand-label a gold set, and run calibration.

## Deployment

- **Dashboard → Vercel** (`dashboard/`, `dashboard/vercel.json`). Set
  `NEXT_PUBLIC_API_BASE` to the API URL, or leave unset to serve the bundled demo.
- **API → Render / Fly.io / Docker** (`Dockerfile`, `render.yaml`). Set
  `ANTHROPIC_API_KEY` to leave mock mode.

## Tests

```bash
pytest --cov=agent_triage
```

32 tests covering schema contracts, taxonomy integrity, deterministic signals,
the classifier pipeline, evaluation math (kappa verified against known values),
the API, and the OpenHands adapter.

## Project layout

```
src/agent_triage/
  schema/trace.py          normalized AgentRun representation
  taxonomy/categories.py   the failure taxonomy (versioned, ownership-tagged)
  engine/
    signals.py             deterministic signal extraction + rule shortcut
    compaction.py          evidence-dense trace compaction
    card.py                TriageCard output schema
    classifier.py          the triage pipeline
  llm/provider.py          model-agnostic provider layer (+ offline mock)
  harness/openhands_adapter.py   OpenHands → AgentRun
  eval/                    gold set, metrics (kappa, F1, CIs), runner
  api/app.py               FastAPI service
  cli.py                   Typer CLI
dashboard/                 Next.js + TypeScript dashboard (Vercel)
scripts/generate_fixtures.py
docs/                      runbook, design notes
```

## License

MIT.
