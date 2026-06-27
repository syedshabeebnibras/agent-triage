# Agent Triage — project teardown

> This is the template for your final writeup. Fill the bracketed placeholders
> after the real OpenHands run (Week 2–3). Keep it factual; cite real numbers from
> `eval_report.json`. The structure below is what a hiring audience wants.

## 1. The problem

Autonomous coding agents fail on a meaningful share of real tasks. When they do,
the investigation — read the logs, trace the trajectory, form a root-cause
hypothesis, decide whether to escalate to engineering or educate the user — is
slow, manual, and inconsistent across people. There's no systematic view of
*which* failure modes dominate a batch of runs, so teams can't prioritize the
fixes that would move reliability most.

## 2. What I built

Agent Triage is a pipeline that turns one failed agent run into a structured,
evidence-grounded root-cause card, and a batch of runs into an actionable failure
distribution.

```
raw OpenHands output → normalized AgentRun → [deterministic signals → rule
shortcut → evidence-dense compaction → model-agnostic LLM classification] →
TriageCard (category · confidence · evidence · owner · action · prevention)
→ FastAPI + Next.js dashboard + calibrated evaluation
```

- **Backend:** Python / FastAPI, [N] modules, [32] tests, ruff + mypy + CI.
- **Taxonomy:** [8] ownership-tagged failure categories, versioned, validated
  against real data (see §3).
- **Dashboard:** Next.js / TypeScript, deployed on Vercel: [URL].
- **API:** Dockerized, deployed on [Render]: [URL].

## 3. The honest result

I generated [N] real OpenHands runs on SWE-bench Lite, of which [M] failed. I
hand-labeled a gold set of [G] runs and measured the classifier against it:

- **Accuracy:** [X] (95% CI [lo, hi])
- **Cohen's kappa:** [X] (95% CI [lo, hi]) — agreement corrected for chance
- **Rules handled [Y]%** of cases deterministically (free, no LLM call)
- **Most-confused pair:** [A vs B], because [reason]

**Taxonomy validation story:** I defined the eight categories a priori from known
agent failure modes. Running real failures through them, the OTHER rate was [X]%
and [A]/[B] were frequently confused, so I [added/merged/redefined ...] and bumped
to v[Y]. The before/after is documented in `docs/EVAL_NOTES.md`.

## 4. Three design decisions I'd defend

1. **Deterministic signals before the model.** Exit codes, error fingerprints,
   repetition, premature-finish — all extracted in code. The LLM only does
   genuinely ambiguous judgment. Cheaper, faster, auditable.
2. **Model-agnostic by design.** The engine depends on an `LLMProvider` protocol,
   not a vendor SDK — so it routes across providers and runs fully offline in
   tests. Mirrors how production agent systems actually route models.
3. **Evidence-grounded, auditable output.** Every verdict cites specific step
   indices and carries rule/llm provenance, so a human verifies rather than
   trusts — and the card doubles as the escalation context for engineering.

## 5. Limitations & next steps

- Evaluated on OpenHands as an open stand-in for the failure *category*, not on
  any specific proprietary agent.
- Small gold set, single labeler → wide CIs; numbers are directional. Next:
  inter-annotator agreement, larger batch.
- Next features: clustering the OTHER bucket to surface new categories
  automatically; trend view across run batches over time; a "fix suggestion" pass
  for the agent-framework-owned categories.

---

*Built [dates]. Code: [repo URL]. Stack: Python · FastAPI · Next.js · TypeScript ·
Docker · GitHub Actions · Anthropic Claude (model-agnostic).*
