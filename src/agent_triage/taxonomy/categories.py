"""Agent-run failure taxonomy.

This is the analytical heart of the project. A support engineer's value is not
"the agent failed" — it's *why* it failed, *who* should fix it, and *how to
prevent the whole class* next time. This module encodes that judgment as data.

The taxonomy is intentionally:
  - **Mutually distinguishable**: each category has a crisp definition and
    distinguishing signals so a human (and an LLM judge) can agree on labels.
  - **Ownership-tagged**: every category maps to who typically resolves it
    (user/task-author, environment/infra, agent-framework, or model). This is
    exactly the "escalate to engineering with complete technical context" vs
    "educate the customer on best practices" decision from the support role.
  - **Versioned**: `TAXONOMY_VERSION` lets eval results stay comparable as the
    taxonomy evolves. Categories were derived from real OpenHands runs on
    SWE-bench, not invented a priori.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

TAXONOMY_VERSION = "0.2.0"


class Owner(str, Enum):
    """Who is typically responsible for resolving a failure of this class."""

    TASK_AUTHOR = "task_author"      # scoping/prompt problem — educate the user
    ENVIRONMENT = "environment"      # infra/deps/CI — fix the sandbox or config
    AGENT_FRAMEWORK = "agent_framework"  # the scaffold/agent logic — escalate to eng
    MODEL = "model"                  # underlying LLM reasoning limit — model/route fix
    UNKNOWN = "unknown"


class FailureCategory(BaseModel):
    """A single failure mode in the taxonomy."""

    code: str
    name: str
    definition: str
    typical_owner: Owner
    # textual / structural signals that point toward this category
    signals: list[str]
    # what a support engineer should do about it (seed for playbook generation)
    recommended_action: str
    # how to stop this whole class from recurring
    prevention: str


# ---------------------------------------------------------------------------
# The taxonomy. Eight top-level categories covering the failure space we
# observed in real OpenHands/SWE-bench runs, plus an explicit catch-all.
# ---------------------------------------------------------------------------

TAXONOMY: dict[str, FailureCategory] = {
    "SCOPING": FailureCategory(
        code="SCOPING",
        name="Task scoping / underspecification",
        definition=(
            "The task as given was ambiguous, under-constrained, or missing "
            "context the agent needed. The agent solved the wrong problem, or a "
            "plausible-but-incorrect interpretation of the problem."
        ),
        typical_owner=Owner.TASK_AUTHOR,
        signals=[
            "agent's solution addresses a different symptom than the test checks",
            "agent asks no clarifying questions on an ambiguous prompt",
            "final patch is plausible but tests assert different behavior",
            "problem statement references files/behavior not in the repo",
        ],
        recommended_action=(
            "Educate the task author: provide a scoping template (acceptance "
            "criteria, target files, reproduction steps). Do not escalate to eng."
        ),
        prevention=(
            "Add a pre-flight task-quality check that flags vague specs before a "
            "run starts; offer a task template in the product."
        ),
    ),
    "ENVIRONMENT": FailureCategory(
        code="ENVIRONMENT",
        name="Environment / dependency setup",
        definition=(
            "The sandbox could not be brought to a working state: missing "
            "dependencies, wrong language/runtime version, build failures, or "
            "package-resolution errors unrelated to the agent's code changes."
        ),
        typical_owner=Owner.ENVIRONMENT,
        signals=[
            "ModuleNotFoundError / ImportError before any edit",
            "pip/npm/poetry install failures",
            "version mismatch errors (python, node, compiler)",
            "missing system library or binary",
        ],
        recommended_action=(
            "Fix the environment image / setup script. Capture the exact missing "
            "dependency and pin it. Escalate to infra if the base image is wrong."
        ),
        prevention=(
            "Harden the sandbox base image; add a dependency pre-check step; "
            "snapshot known-good environments per repo."
        ),
    ),
    "CONTEXT_RETRIEVAL": FailureCategory(
        code="CONTEXT_RETRIEVAL",
        name="Context retrieval / navigation failure",
        definition=(
            "The agent failed to find or read the relevant code. It edited the "
            "wrong file, missed the actual implementation, or never located the "
            "symbol it needed despite it existing in the repo."
        ),
        typical_owner=Owner.AGENT_FRAMEWORK,
        signals=[
            "agent edits a file unrelated to the failing test",
            "repeated failed grep/find/ls before giving up",
            "agent claims a symbol doesn't exist when it does",
            "never opens the file containing the bug",
        ],
        recommended_action=(
            "Escalate to engineering with the trajectory showing the missed file. "
            "Note where retrieval broke down (search vs ranking vs read)."
        ),
        prevention=(
            "Improve code-search/indexing; add repo-map priming; raise read "
            "budget for large repos."
        ),
    ),
    "REASONING": FailureCategory(
        code="REASONING",
        name="Model reasoning / logic error",
        definition=(
            "The agent found the right place and understood the task, but the "
            "fix is logically wrong: incorrect algorithm, wrong edge-case "
            "handling, or a misunderstanding of the code's semantics."
        ),
        typical_owner=Owner.MODEL,
        signals=[
            "correct file edited, but tests fail on logic/assertion",
            "off-by-one, wrong condition, wrong return value",
            "fix addresses the happy path but breaks an edge case",
            "agent's stated plan is sound but implementation diverges",
        ],
        recommended_action=(
            "Candidate for a stronger/different model or a routing change. "
            "Capture as a reasoning-eval case; consider model escalation."
        ),
        prevention=(
            "Route hard-reasoning tasks to a stronger model; add a self-review / "
            "test-first step before finishing."
        ),
    ),
    "VERIFICATION": FailureCategory(
        code="VERIFICATION",
        name="Verification / self-checking failure",
        definition=(
            "The agent produced a reasonable change but never ran (or "
            "misread) the tests, declared success prematurely, or its own "
            "verification disagreed with the grading harness."
        ),
        typical_owner=Owner.AGENT_FRAMEWORK,
        signals=[
            "agent calls finish without running the test suite",
            "agent runs tests, sees failures, finishes anyway",
            "agent runs a different test command than the grader",
            "premature 'the fix is complete' with no green run",
        ],
        recommended_action=(
            "Escalate to engineering: the agent loop should not finish on a red "
            "or unverified state. Provide the step where it gave up checking."
        ),
        prevention=(
            "Make 'tests green' a hard gate before finish; align the agent's test "
            "command with the grading harness."
        ),
    ),
    "TOOL_USE": FailureCategory(
        code="TOOL_USE",
        name="Tool-use / action-formatting error",
        definition=(
            "The agent's actions were malformed or misused tools: broken edit "
            "syntax, patches that don't apply, repeated identical failing "
            "commands, wrong command names, or hardcoded wrong paths."
        ),
        typical_owner=Owner.AGENT_FRAMEWORK,
        signals=[
            "edit/patch repeatedly fails to apply",
            "same command issued 3+ times with identical failure",
            "malformed diff / wrong file path in edit action",
            "agent loops on a tool error without adapting",
            "agent uses wrong interpreter name (python vs python3)",
            "agent uses hardcoded wrong workspace path (/repo, /home/user)",
            "agent calls file_read on a directory path and fails to self-correct",
        ],
        recommended_action=(
            "Escalate to engineering with the repeated-failure step indices. "
            "Distinguish from REASONING: here the *plan* may be fine."
        ),
        prevention=(
            "Add edit-application validation with retry/repair; detect command "
            "repetition and force a strategy change; inject workspace path at "
            "agent init so it never has to guess."
        ),
    ),
    "RESOURCE_LIMIT": FailureCategory(
        code="RESOURCE_LIMIT",
        name="Resource / budget exhaustion",
        definition=(
            "The task genuinely required more iterations, context, or wall-clock "
            "time than the configured budget allowed. Distinguishable from "
            "IMPLEMENTATION_STALL: here a larger budget would plausibly have "
            "helped; the agent was making real progress when it was cut off."
        ),
        typical_owner=Owner.AGENT_FRAMEWORK,
        signals=[
            "run terminates at max iterations with agent mid-task (open tools, partial edits)",
            "context-window / token-limit errors",
            "timeout / wall-clock cap reached while applying or verifying a change",
            "truncated observations causing lost context",
        ],
        recommended_action=(
            "Assess whether the task was too large for the budget (educate user "
            "on decomposition) or the agent was inefficient (escalate). Report "
            "ACU/cost so spend surprises are visible."
        ),
        prevention=(
            "Right-size budgets per task complexity; add task decomposition; "
            "compress context; surface spend estimates before long runs."
        ),
    ),
    "IMPLEMENTATION_STALL": FailureCategory(
        code="IMPLEMENTATION_STALL",
        name="Implementation stall — understood but never committed",
        definition=(
            "The agent correctly navigated to the relevant code and formed a "
            "plausible or verified understanding of the fix, but produced zero "
            "file edits. Exploration or verification loops consumed the entire "
            "turn budget without a single edit_file/write action. Distinguishable "
            "from RESOURCE_LIMIT because the agent's reasoning was sufficient; "
            "the failure is the absence of commitment, not the absence of time."
        ),
        typical_owner=Owner.AGENT_FRAMEWORK,
        signals=[
            "no file-edit actions appear anywhere in the trajectory",
            "agent explicitly states a correct plan or fix but does not execute it",
            "agent validates a fix in an isolated /tmp script but never applies it to the target file",
            "agent reads the same file 3+ times in later turns without editing it",
            "trajectory ends with agent re-reading the target file (preparing to edit, never arrives)",
        ],
        recommended_action=(
            "Escalate to engineering: the agent loop must gate 'finish' on having "
            "produced at least one file edit. Show the step where understanding "
            "was reached and the remaining turn count at that point."
        ),
        prevention=(
            "Add a hard rule: 'finish' is disallowed unless at least one file "
            "edit has been made; warn the agent after N exploration-only turns "
            "with no edits; consider a planning step that commits a skeleton edit "
            "early to anchor subsequent refinement."
        ),
    ),
    "INFRA_ERROR": FailureCategory(
        code="INFRA_ERROR",
        name="Infrastructure / platform error",
        definition=(
            "A failure in the platform itself, not the agent's decisions: API "
            "rate limits, provider 5xx, network errors, sandbox crashes, or "
            "framework exceptions/stack traces."
        ),
        typical_owner=Owner.ENVIRONMENT,
        signals=[
            "429 / rate-limit from model provider",
            "500/503 from API; connection reset; DNS failure",
            "framework traceback unrelated to task code",
            "sandbox container died / OOM-killed",
        ],
        recommended_action=(
            "Escalate to infra/platform on-call. These are retryable and should "
            "not count against the agent's quality metrics."
        ),
        prevention=(
            "Add retries with backoff; multi-provider failover; health checks; "
            "separate infra failures from quality failures in dashboards."
        ),
    ),
    "OTHER": FailureCategory(
        code="OTHER",
        name="Unclassified / mixed",
        definition=(
            "The failure does not fit a single category above, or the evidence "
            "is insufficient to attribute a root cause with confidence."
        ),
        typical_owner=Owner.UNKNOWN,
        signals=["ambiguous evidence", "multiple co-occurring causes"],
        recommended_action=(
            "Flag for human review. Capture as a candidate for a future "
            "taxonomy category if the pattern recurs."
        ),
        prevention="Monitor OTHER rate; promote recurring patterns to new categories.",
    ),
}


def all_codes() -> list[str]:
    """Stable, ordered list of category codes."""
    return list(TAXONOMY.keys())


def get(code: str) -> FailureCategory:
    """Look up a category, raising a clear error on unknown codes."""
    try:
        return TAXONOMY[code]
    except KeyError as exc:
        raise KeyError(
            f"Unknown failure code {code!r}. Valid codes: {all_codes()}"
        ) from exc


def is_valid(code: str) -> bool:
    return code in TAXONOMY
