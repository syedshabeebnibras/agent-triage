# Design notes

## Why deterministic signals before the LLM

Most agent failures have hard, machine-detectable fingerprints: a non-zero exit
code, a `ModuleNotFoundError`, three identical failed commands, a `finish` with no
test run. Extracting these in code (not via the model) makes the system cheaper
(skips an LLM call on unambiguous cases), faster, and auditable (a human can see
the exact signal). The LLM is reserved for the genuinely ambiguous judgment —
distinguishing REASONING from CONTEXT_RETRIEVAL from TOOL_USE — where it adds real
value.

## Why a model-agnostic provider

Production coding-agent systems route across model providers for cost/performance.
Hard-coupling the triage engine to one SDK would be a design smell. The
`LLMProvider` protocol keeps the engine vendor-neutral and makes the whole system
testable offline via `MockProvider`. The mock is deliberately labeled as
not-a-real-classifier so demo output is never mistaken for measured accuracy.

## Why ownership-tagged categories

A classification is only useful if it drives an action. Tagging each category with
the owner of the fix (task author / environment / agent framework / model) maps the
taxonomy directly onto the support decision: educate the user, fix the sandbox,
escalate to engineering, or change the routing/model. The dashboard's color logic
encodes ownership for exactly this reason.

## Why evidence-grounded output

A root-cause verdict the consumer can't verify is just a guess with confidence.
Every card cites specific step indices with excerpts, so a support engineer can
confirm the verdict and hand it to engineering as "complete technical context"
rather than "the tool said so."

## Extending to other agents

Supporting a new agent (SWE-agent, Devin, a custom scaffold) is one adapter in
`harness/` that maps its output into the normalized `AgentRun`. The engine, eval,
API, and dashboard need zero changes. That separation is the point.
