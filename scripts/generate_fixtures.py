"""Generate realistic demo fixtures.

Produces a set of normalized AgentRun objects that resemble real OpenHands
failures on SWE-bench tasks — one or more per taxonomy category — plus a matching
gold set. These power the deployed demo and let the eval harness produce numbers
before you generate real traces.

IMPORTANT: these are *hand-authored realistic fixtures*, not real agent runs. The
demo labels them clearly as sample data. Real evaluation numbers must come from
real OpenHands traces (see docs/RUNBOOK_OPENHANDS.md).
"""

from __future__ import annotations

from pathlib import Path

from agent_triage.eval.gold import GoldLabel, GoldSet
from agent_triage.schema.trace import (
    ActionType,
    AgentRun,
    Observation,
    Step,
    TaskSpec,
    TestResult,
)

OUT_DIR = Path("data/traces")
GOLD_DIR = Path("data/gold")


def _step(i, atype, content, obs=None, exit_code=None):
    observation = None
    if obs is not None or exit_code is not None:
        observation = Observation(content=obs or "", exit_code=exit_code)
    return Step(index=i, action_type=atype, content=content, observation=observation)


def build_fixtures() -> tuple[list[AgentRun], GoldSet]:
    runs: list[AgentRun] = []
    labels: list[GoldLabel] = []

    def add(run: AgentRun, true_cat: str, notes: str = ""):
        runs.append(run)
        labels.append(GoldLabel(run_id=run.run_id, task_id=run.task.task_id,
                                true_category=true_cat, labeler="fixture", notes=notes))

    # ENVIRONMENT
    add(AgentRun(
        run_id="oh-env-001", agent="openhands", model="claude-sonnet-4-6",
        task=TaskSpec(task_id="pallets__flask-4992", repo="pallets/flask",
                      problem_statement="Config.from_file should support custom loaders."),
        steps=[
            _step(0, ActionType.COMMAND, "python -m pytest tests/test_config.py",
                  "ImportError: cannot import name 'tomllib'", 1),
            _step(1, ActionType.COMMAND, "pip install tomli",
                  "ERROR: Could not find a version that satisfies the requirement tomli", 1),
            _step(2, ActionType.ERROR, "Unable to set up environment; aborting."),
        ],
        resolved=False, test_result=TestResult(passed=False)),
        "ENVIRONMENT", "py version lacks tomllib; install blocked")

    # INFRA_ERROR
    add(AgentRun(
        run_id="oh-infra-001", agent="openhands", model="claude-sonnet-4-6",
        task=TaskSpec(task_id="django__django-15789", repo="django/django",
                      problem_statement="Add encoder parameter to django.utils.html.json_script."),
        steps=[
            _step(0, ActionType.FILE_READ, "django/utils/html.py", "<file contents>", 0),
            _step(1, ActionType.MODEL_CALL, "plan the fix",
                  "anthropic.RateLimitError: Error code 429 - overloaded_error", 1),
            _step(2, ActionType.MODEL_CALL, "retry plan",
                  "anthropic.RateLimitError: Error code 429 - overloaded_error", 1),
        ],
        resolved=False, test_result=TestResult(passed=False)),
        "INFRA_ERROR", "provider rate limit, no patch")

    # RESOURCE_LIMIT
    add(AgentRun(
        run_id="oh-res-001", agent="openhands", model="claude-sonnet-4-6",
        task=TaskSpec(task_id="sympy__sympy-21055", repo="sympy/sympy",
                      problem_statement="refine() does not simplify some complex expressions."),
        steps=[_step(i, ActionType.COMMAND, f"grep -rn refine sympy/assumptions/ # attempt {i}",
                     "<long output>", 0) for i in range(0, 18)] + [
            _step(18, ActionType.ERROR,
                  "Agent reached maximum iterations (18) without finishing the task."),
        ],
        resolved=False, test_result=TestResult(passed=False)),
        "RESOURCE_LIMIT", "hit iteration cap while exploring")

    # CONTEXT_RETRIEVAL
    add(AgentRun(
        run_id="oh-ctx-001", agent="openhands", model="claude-sonnet-4-6",
        task=TaskSpec(task_id="scikit-learn__scikit-learn-13496", repo="scikit-learn/scikit-learn",
                      problem_statement="Expose warm_start in IsolationForest."),
        steps=[
            _step(0, ActionType.COMMAND, "grep -rn 'warm_start' sklearn/ensemble/_iforest.py",
                  "", 1),
            _step(1, ActionType.FILE_EDIT, "edited sklearn/ensemble/bagging.py", "ok", 0),
            _step(2, ActionType.COMMAND, "pytest sklearn/ensemble/tests/test_iforest.py",
                  "AssertionError: IsolationForest has no attribute warm_start", 1),
            _step(3, ActionType.FINISH, "I have added warm_start support."),
        ],
        final_patch="diff --git a/sklearn/ensemble/bagging.py b/sklearn/ensemble/bagging.py",
        resolved=False, test_result=TestResult(passed=False, total_tests=12, passed_tests=11, failed_tests=1)),
        "CONTEXT_RETRIEVAL", "edited bagging.py instead of _iforest.py")

    # REASONING
    add(AgentRun(
        run_id="oh-reason-001", agent="openhands", model="claude-sonnet-4-6",
        task=TaskSpec(task_id="django__django-11099", repo="django/django",
                      problem_statement="UsernameValidator should not allow trailing newline."),
        steps=[
            _step(0, ActionType.FILE_READ, "django/contrib/auth/validators.py", "<contents>", 0),
            _step(1, ActionType.FILE_EDIT, "changed regex from r'^[\\w.@+-]+$' to r'^[\\w.@+-]+\\Z'",
                  "ok", 0),
            _step(2, ActionType.COMMAND, "pytest tests/auth_tests/test_validators.py",
                  "1 failed: AssertionError: regex still matches 'abc\\n' (used $ semantics in test)", 1),
            _step(3, ActionType.FINISH, "Fixed the validator regex."),
        ],
        final_patch="diff --git a/django/contrib/auth/validators.py",
        resolved=False, test_result=TestResult(passed=False, total_tests=8, passed_tests=7, failed_tests=1)),
        "REASONING", "right file, subtly wrong regex anchor logic")

    # VERIFICATION
    add(AgentRun(
        run_id="oh-verify-001", agent="openhands", model="claude-sonnet-4-6",
        task=TaskSpec(task_id="matplotlib__matplotlib-23987", repo="matplotlib/matplotlib",
                      problem_statement="Fix UserWarning when constrained_layout=False."),
        steps=[
            _step(0, ActionType.FILE_READ, "lib/matplotlib/figure.py", "<contents>", 0),
            _step(1, ActionType.FILE_EDIT, "guarded the warning behind a None check", "ok", 0),
            _step(2, ActionType.FINISH, "The warning is now fixed; the change is complete."),
        ],
        final_patch="diff --git a/lib/matplotlib/figure.py",
        resolved=False, test_result=TestResult(passed=False)),
        "VERIFICATION", "finished without ever running tests")

    # TOOL_USE
    add(AgentRun(
        run_id="oh-tool-001", agent="openhands", model="claude-sonnet-4-6",
        task=TaskSpec(task_id="psf__requests-2317", repo="psf/requests",
                      problem_statement="method = builtin_str(method) breaks on binary method."),
        steps=[
            _step(0, ActionType.FILE_EDIT,
                  "apply patch to requests/sessions.py (context lines mismatch)",
                  "ERROR: patch does not apply; hunk #1 FAILED at 428", 1),
            _step(1, ActionType.FILE_EDIT,
                  "apply patch to requests/sessions.py (context lines mismatch)",
                  "ERROR: patch does not apply; hunk #1 FAILED at 428", 1),
            _step(2, ActionType.FILE_EDIT,
                  "apply patch to requests/sessions.py (context lines mismatch)",
                  "ERROR: patch does not apply; hunk #1 FAILED at 428", 1),
            _step(3, ActionType.ERROR, "Giving up after repeated patch failures."),
        ],
        resolved=False, test_result=TestResult(passed=False)),
        "TOOL_USE", "patch repeatedly fails to apply; thrashing")

    # SCOPING
    add(AgentRun(
        run_id="oh-scope-001", agent="openhands", model="claude-sonnet-4-6",
        task=TaskSpec(task_id="internal__ticket-8842", repo="acme/widgets",
                      problem_statement="Make the export faster."),
        steps=[
            _step(0, ActionType.FILE_READ, "exporter.py", "<contents>", 0),
            _step(1, ActionType.FILE_EDIT, "added a CSV streaming buffer to speed up file write", "ok", 0),
            _step(2, ActionType.COMMAND, "pytest tests/test_export.py",
                  "1 failed: test expects parallel DB fetch optimization, not file IO change", 1),
            _step(3, ActionType.FINISH, "Made the export faster by buffering writes."),
        ],
        final_patch="diff --git a/exporter.py",
        resolved=False, test_result=TestResult(passed=False, total_tests=4, passed_tests=3, failed_tests=1)),
        "SCOPING", "vague spec; agent optimized the wrong layer")

    # OTHER (genuinely ambiguous / mixed)
    add(AgentRun(
        run_id="oh-other-001", agent="openhands", model="claude-sonnet-4-6",
        task=TaskSpec(task_id="astropy__astropy-14182", repo="astropy/astropy",
                      problem_statement="Support header rows in RST writer."),
        steps=[
            _step(0, ActionType.FILE_READ, "astropy/io/ascii/rst.py", "<contents>", 0),
            _step(1, ActionType.FILE_EDIT, "partial edit", "ok", 0),
            _step(2, ActionType.COMMAND, "pytest astropy/io/ascii/tests/test_rst.py",
                  "mixed: 2 failed, 1 error, traceback truncated", 1),
        ],
        final_patch="diff --git a/astropy/io/ascii/rst.py",
        resolved=False, test_result=TestResult(passed=False)),
        "OTHER", "mixed failures + truncated evidence")

    gold = GoldSet(labels=labels)
    return runs, gold


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    runs, gold = build_fixtures()

    with open(OUT_DIR / "demo_runs.jsonl", "w") as f:
        for r in runs:
            f.write(r.model_dump_json() + "\n")
    gold.to_jsonl(GOLD_DIR / "demo_gold.jsonl")

    # also emit a single pretty run for the API example
    (OUT_DIR / "example_run.json").write_text(runs[4].model_dump_json(indent=2))

    print(f"Wrote {len(runs)} runs to {OUT_DIR/'demo_runs.jsonl'}")
    print(f"Wrote gold set to {GOLD_DIR/'demo_gold.jsonl'}")


if __name__ == "__main__":
    main()
