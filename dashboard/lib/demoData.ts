// AUTO-GENERATED from backend output by scripts/generate_fixtures.py + export.
// Illustrative demo data so the deployed dashboard works without a live API.
// Real triage output comes from the FastAPI backend with a real model.

import type { TriageCard, TaxonomyCategory } from './api';

export const DEMO_CARDS: TriageCard[] = [
  {
    "run_id": "oh-env-001",
    "task_id": "pallets__flask-4992",
    "agent": "openhands",
    "model": "claude-sonnet-4-6",
    "primary_category": "ENVIRONMENT",
    "secondary_category": null,
    "confidence": 0.92,
    "classifier": "rule",
    "root_cause": "The sandbox Python runtime lacks tomllib and the tomli backport could not be installed, so the test suite never ran. This is an environment provisioning gap, not an agent error.",
    "evidence": [
      {
        "step_index": 0,
        "excerpt": "ImportError: cannot import name 'tomllib'",
        "why": "environment missing before any edit"
      },
      {
        "step_index": 1,
        "excerpt": "Could not find a version that satisfies the requirement tomli",
        "why": "dependency install blocked"
      }
    ],
    "owner": "environment",
    "recommended_action": "Fix the environment image / setup script. Capture the exact missing dependency and pin it. Escalate to infra if the base image is wrong.",
    "prevention": "Harden the sandbox base image; add a dependency pre-check step; snapshot known-good environments per repo.",
    "taxonomy_version": "0.1.0",
    "provider": "anthropic:claude-sonnet-4-6 (illustrative)"
  },
  {
    "run_id": "oh-infra-001",
    "task_id": "django__django-15789",
    "agent": "openhands",
    "model": "claude-sonnet-4-6",
    "primary_category": "INFRA_ERROR",
    "secondary_category": null,
    "confidence": 0.95,
    "classifier": "rule",
    "root_cause": "Two consecutive 429 rate-limit errors from the model provider stalled planning before any code change. This is a retryable platform failure and should not count against agent quality.",
    "evidence": [
      {
        "step_index": 1,
        "excerpt": "anthropic.RateLimitError: Error code 429",
        "why": "provider rate limit"
      },
      {
        "step_index": 2,
        "excerpt": "anthropic.RateLimitError: Error code 429",
        "why": "repeated on retry"
      }
    ],
    "owner": "environment",
    "recommended_action": "Escalate to infra/platform on-call. These are retryable and should not count against the agent's quality metrics.",
    "prevention": "Add retries with backoff; multi-provider failover; health checks; separate infra failures from quality failures in dashboards.",
    "taxonomy_version": "0.1.0",
    "provider": "anthropic:claude-sonnet-4-6 (illustrative)"
  },
  {
    "run_id": "oh-res-001",
    "task_id": "sympy__sympy-21055",
    "agent": "openhands",
    "model": "claude-sonnet-4-6",
    "primary_category": "RESOURCE_LIMIT",
    "secondary_category": null,
    "confidence": 0.88,
    "classifier": "rule",
    "root_cause": "The agent spent all 18 iterations grepping the assumptions module and hit the step cap before attempting a fix. The task likely needed decomposition or a larger budget.",
    "evidence": [
      {
        "step_index": 18,
        "excerpt": "Agent reached maximum iterations (18) without finishing",
        "why": "hard iteration cap"
      }
    ],
    "owner": "agent_framework",
    "recommended_action": "Assess whether the task was too large for the budget (educate user on decomposition) or the agent was inefficient (escalate). Report ACU/cost so spend surprises are visible.",
    "prevention": "Right-size budgets per task complexity; add task decomposition; compress context; surface spend estimates before long runs.",
    "taxonomy_version": "0.1.0",
    "provider": "anthropic:claude-sonnet-4-6 (illustrative)"
  },
  {
    "run_id": "oh-ctx-001",
    "task_id": "scikit-learn__scikit-learn-13496",
    "agent": "openhands",
    "model": "claude-sonnet-4-6",
    "primary_category": "CONTEXT_RETRIEVAL",
    "secondary_category": null,
    "confidence": 0.86,
    "classifier": "llm",
    "root_cause": "The agent edited bagging.py, but the IsolationForest implementation lives in _iforest.py. It never located the correct file, so warm_start was added in the wrong place.",
    "evidence": [
      {
        "step_index": 0,
        "excerpt": "grep -rn 'warm_start' sklearn/ensemble/_iforest.py -> (no match found, exit 1)",
        "why": "failed to locate target"
      },
      {
        "step_index": 1,
        "excerpt": "edited sklearn/ensemble/bagging.py",
        "why": "wrong file edited"
      }
    ],
    "owner": "agent_framework",
    "recommended_action": "Escalate to engineering with the trajectory showing the missed file. Note where retrieval broke down (search vs ranking vs read).",
    "prevention": "Improve code-search/indexing; add repo-map priming; raise read budget for large repos.",
    "taxonomy_version": "0.1.0",
    "provider": "anthropic:claude-sonnet-4-6 (illustrative)"
  },
  {
    "run_id": "oh-reason-001",
    "task_id": "django__django-11099",
    "agent": "openhands",
    "model": "claude-sonnet-4-6",
    "primary_category": "REASONING",
    "secondary_category": null,
    "confidence": 0.82,
    "classifier": "llm",
    "root_cause": "The agent edited the correct validator but used \\Z anchoring whose semantics still admit the trailing newline the test rejects. Right location, subtly wrong logic.",
    "evidence": [
      {
        "step_index": 1,
        "excerpt": "changed regex to r'^[\\w.@+-]+\\Z'",
        "why": "correct file, flawed anchor"
      },
      {
        "step_index": 2,
        "excerpt": "AssertionError: regex still matches 'abc\\n'",
        "why": "logic error confirmed by test"
      }
    ],
    "owner": "model",
    "recommended_action": "Candidate for a stronger/different model or a routing change. Capture as a reasoning-eval case; consider model escalation.",
    "prevention": "Route hard-reasoning tasks to a stronger model; add a self-review / test-first step before finishing.",
    "taxonomy_version": "0.1.0",
    "provider": "anthropic:claude-sonnet-4-6 (illustrative)"
  },
  {
    "run_id": "oh-verify-001",
    "task_id": "matplotlib__matplotlib-23987",
    "agent": "openhands",
    "model": "claude-sonnet-4-6",
    "primary_category": "VERIFICATION",
    "secondary_category": null,
    "confidence": 0.9,
    "classifier": "llm",
    "root_cause": "The agent declared the fix complete without ever running the test suite. The loop should not be allowed to finish on an unverified state.",
    "evidence": [
      {
        "step_index": 2,
        "excerpt": "The warning is now fixed; the change is complete.",
        "why": "finished without running tests"
      }
    ],
    "owner": "agent_framework",
    "recommended_action": "Escalate to engineering: the agent loop should not finish on a red or unverified state. Provide the step where it gave up checking.",
    "prevention": "Make 'tests green' a hard gate before finish; align the agent's test command with the grading harness.",
    "taxonomy_version": "0.1.0",
    "provider": "anthropic:claude-sonnet-4-6 (illustrative)"
  },
  {
    "run_id": "oh-tool-001",
    "task_id": "psf__requests-2317",
    "agent": "openhands",
    "model": "claude-sonnet-4-6",
    "primary_category": "TOOL_USE",
    "secondary_category": null,
    "confidence": 0.89,
    "classifier": "llm",
    "root_cause": "The same patch failed to apply three times due to context-line mismatch; the agent repeated the identical action instead of re-reading the file. A tool-use/thrashing failure.",
    "evidence": [
      {
        "step_index": 0,
        "excerpt": "patch does not apply; hunk #1 FAILED at 428",
        "why": "first failure"
      },
      {
        "step_index": 2,
        "excerpt": "patch does not apply; hunk #1 FAILED at 428",
        "why": "identical 3rd failure = thrashing"
      }
    ],
    "owner": "agent_framework",
    "recommended_action": "Escalate to engineering with the repeated-failure step indices. Distinguish from REASONING: here the *plan* may be fine.",
    "prevention": "Add edit-application validation with retry/repair; detect command repetition and force a strategy change.",
    "taxonomy_version": "0.1.0",
    "provider": "anthropic:claude-sonnet-4-6 (illustrative)"
  },
  {
    "run_id": "oh-scope-001",
    "task_id": "internal__ticket-8842",
    "agent": "openhands",
    "model": "claude-sonnet-4-6",
    "primary_category": "SCOPING",
    "secondary_category": null,
    "confidence": 0.78,
    "classifier": "llm",
    "root_cause": "The spec ('make the export faster') was underspecified. The agent optimized file IO while the test expected a parallel DB-fetch optimization. A scoping problem owned by the task author.",
    "evidence": [
      {
        "step_index": 2,
        "excerpt": "test expects parallel DB fetch optimization, not file IO change",
        "why": "agent solved wrong problem"
      }
    ],
    "owner": "task_author",
    "recommended_action": "Educate the task author: provide a scoping template (acceptance criteria, target files, reproduction steps). Do not escalate to eng.",
    "prevention": "Add a pre-flight task-quality check that flags vague specs before a run starts; offer a task template in the product.",
    "taxonomy_version": "0.1.0",
    "provider": "anthropic:claude-sonnet-4-6 (illustrative)"
  },
  {
    "run_id": "oh-other-001",
    "task_id": "astropy__astropy-14182",
    "agent": "openhands",
    "model": "claude-sonnet-4-6",
    "primary_category": "OTHER",
    "secondary_category": null,
    "confidence": 0.4,
    "classifier": "llm",
    "root_cause": "Mixed failures (2 failed, 1 error) with a truncated traceback provide insufficient evidence to attribute a single root cause. Flagged for human review.",
    "evidence": [
      {
        "step_index": 2,
        "excerpt": "mixed: 2 failed, 1 error, traceback truncated",
        "why": "insufficient evidence"
      }
    ],
    "owner": "unknown",
    "recommended_action": "Flag for human review. Capture as a candidate for a future taxonomy category if the pattern recurs.",
    "prevention": "Monitor OTHER rate; promote recurring patterns to new categories.",
    "taxonomy_version": "0.1.0",
    "provider": "anthropic:claude-sonnet-4-6 (illustrative)"
  }
];

export const DEMO_TAXONOMY: TaxonomyCategory[] = [
  {
    "code": "SCOPING",
    "name": "Task scoping / underspecification",
    "definition": "The task as given was ambiguous, under-constrained, or missing context the agent needed. The agent solved the wrong problem, or a plausible-but-incorrect interpretation of the problem.",
    "owner": "task_author",
    "signals": [
      "agent's solution addresses a different symptom than the test checks",
      "agent asks no clarifying questions on an ambiguous prompt",
      "final patch is plausible but tests assert different behavior",
      "problem statement references files/behavior not in the repo"
    ],
    "recommended_action": "Educate the task author: provide a scoping template (acceptance criteria, target files, reproduction steps). Do not escalate to eng.",
    "prevention": "Add a pre-flight task-quality check that flags vague specs before a run starts; offer a task template in the product."
  },
  {
    "code": "ENVIRONMENT",
    "name": "Environment / dependency setup",
    "definition": "The sandbox could not be brought to a working state: missing dependencies, wrong language/runtime version, build failures, or package-resolution errors unrelated to the agent's code changes.",
    "owner": "environment",
    "signals": [
      "ModuleNotFoundError / ImportError before any edit",
      "pip/npm/poetry install failures",
      "version mismatch errors (python, node, compiler)",
      "missing system library or binary"
    ],
    "recommended_action": "Fix the environment image / setup script. Capture the exact missing dependency and pin it. Escalate to infra if the base image is wrong.",
    "prevention": "Harden the sandbox base image; add a dependency pre-check step; snapshot known-good environments per repo."
  },
  {
    "code": "CONTEXT_RETRIEVAL",
    "name": "Context retrieval / navigation failure",
    "definition": "The agent failed to find or read the relevant code. It edited the wrong file, missed the actual implementation, or never located the symbol it needed despite it existing in the repo.",
    "owner": "agent_framework",
    "signals": [
      "agent edits a file unrelated to the failing test",
      "repeated failed grep/find/ls before giving up",
      "agent claims a symbol doesn't exist when it does",
      "never opens the file containing the bug"
    ],
    "recommended_action": "Escalate to engineering with the trajectory showing the missed file. Note where retrieval broke down (search vs ranking vs read).",
    "prevention": "Improve code-search/indexing; add repo-map priming; raise read budget for large repos."
  },
  {
    "code": "REASONING",
    "name": "Model reasoning / logic error",
    "definition": "The agent found the right place and understood the task, but the fix is logically wrong: incorrect algorithm, wrong edge-case handling, or a misunderstanding of the code's semantics.",
    "owner": "model",
    "signals": [
      "correct file edited, but tests fail on logic/assertion",
      "off-by-one, wrong condition, wrong return value",
      "fix addresses the happy path but breaks an edge case",
      "agent's stated plan is sound but implementation diverges"
    ],
    "recommended_action": "Candidate for a stronger/different model or a routing change. Capture as a reasoning-eval case; consider model escalation.",
    "prevention": "Route hard-reasoning tasks to a stronger model; add a self-review / test-first step before finishing."
  },
  {
    "code": "VERIFICATION",
    "name": "Verification / self-checking failure",
    "definition": "The agent produced a reasonable change but never ran (or misread) the tests, declared success prematurely, or its own verification disagreed with the grading harness.",
    "owner": "agent_framework",
    "signals": [
      "agent calls finish without running the test suite",
      "agent runs tests, sees failures, finishes anyway",
      "agent runs a different test command than the grader",
      "premature 'the fix is complete' with no green run"
    ],
    "recommended_action": "Escalate to engineering: the agent loop should not finish on a red or unverified state. Provide the step where it gave up checking.",
    "prevention": "Make 'tests green' a hard gate before finish; align the agent's test command with the grading harness."
  },
  {
    "code": "TOOL_USE",
    "name": "Tool-use / action-formatting error",
    "definition": "The agent's actions were malformed or misused tools: broken edit syntax, patches that don't apply, repeated identical failing commands, or thrashing without progress.",
    "owner": "agent_framework",
    "signals": [
      "edit/patch repeatedly fails to apply",
      "same command issued 3+ times with identical failure",
      "malformed diff / wrong file path in edit action",
      "agent loops on a tool error without adapting"
    ],
    "recommended_action": "Escalate to engineering with the repeated-failure step indices. Distinguish from REASONING: here the *plan* may be fine.",
    "prevention": "Add edit-application validation with retry/repair; detect command repetition and force a strategy change."
  },
  {
    "code": "RESOURCE_LIMIT",
    "name": "Resource / budget exhaustion",
    "definition": "The run hit a hard limit before finishing: step/iteration cap, context-window overflow, wall-clock timeout, or token/cost budget.",
    "owner": "agent_framework",
    "signals": [
      "run terminates at max iterations",
      "context-window / token-limit errors",
      "timeout / wall-clock cap reached mid-task",
      "truncated observations causing lost context"
    ],
    "recommended_action": "Assess whether the task was too large for the budget (educate user on decomposition) or the agent was inefficient (escalate). Report ACU/cost so spend surprises are visible.",
    "prevention": "Right-size budgets per task complexity; add task decomposition; compress context; surface spend estimates before long runs."
  },
  {
    "code": "INFRA_ERROR",
    "name": "Infrastructure / platform error",
    "definition": "A failure in the platform itself, not the agent's decisions: API rate limits, provider 5xx, network errors, sandbox crashes, or framework exceptions/stack traces.",
    "owner": "environment",
    "signals": [
      "429 / rate-limit from model provider",
      "500/503 from API; connection reset; DNS failure",
      "framework traceback unrelated to task code",
      "sandbox container died / OOM-killed"
    ],
    "recommended_action": "Escalate to infra/platform on-call. These are retryable and should not count against the agent's quality metrics.",
    "prevention": "Add retries with backoff; multi-provider failover; health checks; separate infra failures from quality failures in dashboards."
  },
  {
    "code": "OTHER",
    "name": "Unclassified / mixed",
    "definition": "The failure does not fit a single category above, or the evidence is insufficient to attribute a root cause with confidence.",
    "owner": "unknown",
    "signals": [
      "ambiguous evidence",
      "multiple co-occurring causes"
    ],
    "recommended_action": "Flag for human review. Capture as a candidate for a future taxonomy category if the pattern recurs.",
    "prevention": "Monitor OTHER rate; promote recurring patterns to new categories."
  }
];

export const DEMO_RUNS: unknown[] = [{"run_id": "oh-env-001", "agent": "openhands", "model": "claude-sonnet-4-6", "task": {"task_id": "pallets__flask-4992", "source": "swe-bench", "repo": "pallets/flask", "base_commit": null, "problem_statement": "Config.from_file should support custom loaders.", "gold_patch": null, "test_directives": []}, "steps": [{"index": 0, "action_type": "command", "content": "python -m pytest tests/test_config.py", "observation": {"content": "ImportError: cannot import name 'tomllib'", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}, {"index": 1, "action_type": "command", "content": "pip install tomli", "observation": {"content": "ERROR: Could not find a version that satisfies the requirement tomli", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}, {"index": 2, "action_type": "error", "content": "Unable to set up environment; aborting.", "observation": null, "timestamp": null, "metadata": {}, "failed": false}], "final_patch": null, "test_result": {"passed": false, "total_tests": null, "passed_tests": null, "failed_tests": null, "error_tests": null, "raw_log": ""}, "resolved": false, "wall_time_seconds": null, "total_tokens": null, "total_cost_usd": null, "error": null, "metadata": {}, "step_count": 3, "produced_patch": false, "failed": true, "content_hash": "b584d84f4dee7646"}, {"run_id": "oh-infra-001", "agent": "openhands", "model": "claude-sonnet-4-6", "task": {"task_id": "django__django-15789", "source": "swe-bench", "repo": "django/django", "base_commit": null, "problem_statement": "Add encoder parameter to django.utils.html.json_script.", "gold_patch": null, "test_directives": []}, "steps": [{"index": 0, "action_type": "file_read", "content": "django/utils/html.py", "observation": {"content": "<file contents>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 1, "action_type": "model_call", "content": "plan the fix", "observation": {"content": "anthropic.RateLimitError: Error code 429 - overloaded_error", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}, {"index": 2, "action_type": "model_call", "content": "retry plan", "observation": {"content": "anthropic.RateLimitError: Error code 429 - overloaded_error", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}], "final_patch": null, "test_result": {"passed": false, "total_tests": null, "passed_tests": null, "failed_tests": null, "error_tests": null, "raw_log": ""}, "resolved": false, "wall_time_seconds": null, "total_tokens": null, "total_cost_usd": null, "error": null, "metadata": {}, "step_count": 3, "produced_patch": false, "failed": true, "content_hash": "f4c727a178e0e3bf"}, {"run_id": "oh-res-001", "agent": "openhands", "model": "claude-sonnet-4-6", "task": {"task_id": "sympy__sympy-21055", "source": "swe-bench", "repo": "sympy/sympy", "base_commit": null, "problem_statement": "refine() does not simplify some complex expressions.", "gold_patch": null, "test_directives": []}, "steps": [{"index": 0, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 0", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 1, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 1", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 2, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 2", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 3, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 3", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 4, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 4", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 5, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 5", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 6, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 6", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 7, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 7", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 8, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 8", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 9, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 9", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 10, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 10", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 11, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 11", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 12, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 12", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 13, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 13", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 14, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 14", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 15, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 15", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 16, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 16", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 17, "action_type": "command", "content": "grep -rn refine sympy/assumptions/ # attempt 17", "observation": {"content": "<long output>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 18, "action_type": "error", "content": "Agent reached maximum iterations (18) without finishing the task.", "observation": null, "timestamp": null, "metadata": {}, "failed": false}], "final_patch": null, "test_result": {"passed": false, "total_tests": null, "passed_tests": null, "failed_tests": null, "error_tests": null, "raw_log": ""}, "resolved": false, "wall_time_seconds": null, "total_tokens": null, "total_cost_usd": null, "error": null, "metadata": {}, "step_count": 19, "produced_patch": false, "failed": true, "content_hash": "3ce9316c00a5c713"}, {"run_id": "oh-ctx-001", "agent": "openhands", "model": "claude-sonnet-4-6", "task": {"task_id": "scikit-learn__scikit-learn-13496", "source": "swe-bench", "repo": "scikit-learn/scikit-learn", "base_commit": null, "problem_statement": "Expose warm_start in IsolationForest.", "gold_patch": null, "test_directives": []}, "steps": [{"index": 0, "action_type": "command", "content": "grep -rn 'warm_start' sklearn/ensemble/_iforest.py", "observation": {"content": "", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}, {"index": 1, "action_type": "file_edit", "content": "edited sklearn/ensemble/bagging.py", "observation": {"content": "ok", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 2, "action_type": "command", "content": "pytest sklearn/ensemble/tests/test_iforest.py", "observation": {"content": "AssertionError: IsolationForest has no attribute warm_start", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}, {"index": 3, "action_type": "finish", "content": "I have added warm_start support.", "observation": null, "timestamp": null, "metadata": {}, "failed": false}], "final_patch": "diff --git a/sklearn/ensemble/bagging.py b/sklearn/ensemble/bagging.py", "test_result": {"passed": false, "total_tests": 12, "passed_tests": 11, "failed_tests": 1, "error_tests": null, "raw_log": ""}, "resolved": false, "wall_time_seconds": null, "total_tokens": null, "total_cost_usd": null, "error": null, "metadata": {}, "step_count": 4, "produced_patch": true, "failed": true, "content_hash": "bb61379a0610a53d"}, {"run_id": "oh-reason-001", "agent": "openhands", "model": "claude-sonnet-4-6", "task": {"task_id": "django__django-11099", "source": "swe-bench", "repo": "django/django", "base_commit": null, "problem_statement": "UsernameValidator should not allow trailing newline.", "gold_patch": null, "test_directives": []}, "steps": [{"index": 0, "action_type": "file_read", "content": "django/contrib/auth/validators.py", "observation": {"content": "<contents>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 1, "action_type": "file_edit", "content": "changed regex from r'^[\\w.@+-]+$' to r'^[\\w.@+-]+\\Z'", "observation": {"content": "ok", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 2, "action_type": "command", "content": "pytest tests/auth_tests/test_validators.py", "observation": {"content": "1 failed: AssertionError: regex still matches 'abc\\n' (used $ semantics in test)", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}, {"index": 3, "action_type": "finish", "content": "Fixed the validator regex.", "observation": null, "timestamp": null, "metadata": {}, "failed": false}], "final_patch": "diff --git a/django/contrib/auth/validators.py", "test_result": {"passed": false, "total_tests": 8, "passed_tests": 7, "failed_tests": 1, "error_tests": null, "raw_log": ""}, "resolved": false, "wall_time_seconds": null, "total_tokens": null, "total_cost_usd": null, "error": null, "metadata": {}, "step_count": 4, "produced_patch": true, "failed": true, "content_hash": "6aebf0339b3470a5"}, {"run_id": "oh-verify-001", "agent": "openhands", "model": "claude-sonnet-4-6", "task": {"task_id": "matplotlib__matplotlib-23987", "source": "swe-bench", "repo": "matplotlib/matplotlib", "base_commit": null, "problem_statement": "Fix UserWarning when constrained_layout=False.", "gold_patch": null, "test_directives": []}, "steps": [{"index": 0, "action_type": "file_read", "content": "lib/matplotlib/figure.py", "observation": {"content": "<contents>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 1, "action_type": "file_edit", "content": "guarded the warning behind a None check", "observation": {"content": "ok", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 2, "action_type": "finish", "content": "The warning is now fixed; the change is complete.", "observation": null, "timestamp": null, "metadata": {}, "failed": false}], "final_patch": "diff --git a/lib/matplotlib/figure.py", "test_result": {"passed": false, "total_tests": null, "passed_tests": null, "failed_tests": null, "error_tests": null, "raw_log": ""}, "resolved": false, "wall_time_seconds": null, "total_tokens": null, "total_cost_usd": null, "error": null, "metadata": {}, "step_count": 3, "produced_patch": true, "failed": true, "content_hash": "b573dbb931c21c26"}, {"run_id": "oh-tool-001", "agent": "openhands", "model": "claude-sonnet-4-6", "task": {"task_id": "psf__requests-2317", "source": "swe-bench", "repo": "psf/requests", "base_commit": null, "problem_statement": "method = builtin_str(method) breaks on binary method.", "gold_patch": null, "test_directives": []}, "steps": [{"index": 0, "action_type": "file_edit", "content": "apply patch to requests/sessions.py (context lines mismatch)", "observation": {"content": "ERROR: patch does not apply; hunk #1 FAILED at 428", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}, {"index": 1, "action_type": "file_edit", "content": "apply patch to requests/sessions.py (context lines mismatch)", "observation": {"content": "ERROR: patch does not apply; hunk #1 FAILED at 428", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}, {"index": 2, "action_type": "file_edit", "content": "apply patch to requests/sessions.py (context lines mismatch)", "observation": {"content": "ERROR: patch does not apply; hunk #1 FAILED at 428", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}, {"index": 3, "action_type": "error", "content": "Giving up after repeated patch failures.", "observation": null, "timestamp": null, "metadata": {}, "failed": false}], "final_patch": null, "test_result": {"passed": false, "total_tests": null, "passed_tests": null, "failed_tests": null, "error_tests": null, "raw_log": ""}, "resolved": false, "wall_time_seconds": null, "total_tokens": null, "total_cost_usd": null, "error": null, "metadata": {}, "step_count": 4, "produced_patch": false, "failed": true, "content_hash": "09eee4b13fef1648"}, {"run_id": "oh-scope-001", "agent": "openhands", "model": "claude-sonnet-4-6", "task": {"task_id": "internal__ticket-8842", "source": "swe-bench", "repo": "acme/widgets", "base_commit": null, "problem_statement": "Make the export faster.", "gold_patch": null, "test_directives": []}, "steps": [{"index": 0, "action_type": "file_read", "content": "exporter.py", "observation": {"content": "<contents>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 1, "action_type": "file_edit", "content": "added a CSV streaming buffer to speed up file write", "observation": {"content": "ok", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 2, "action_type": "command", "content": "pytest tests/test_export.py", "observation": {"content": "1 failed: test expects parallel DB fetch optimization, not file IO change", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}, {"index": 3, "action_type": "finish", "content": "Made the export faster by buffering writes.", "observation": null, "timestamp": null, "metadata": {}, "failed": false}], "final_patch": "diff --git a/exporter.py", "test_result": {"passed": false, "total_tests": 4, "passed_tests": 3, "failed_tests": 1, "error_tests": null, "raw_log": ""}, "resolved": false, "wall_time_seconds": null, "total_tokens": null, "total_cost_usd": null, "error": null, "metadata": {}, "step_count": 4, "produced_patch": true, "failed": true, "content_hash": "5e37515fdd524327"}, {"run_id": "oh-other-001", "agent": "openhands", "model": "claude-sonnet-4-6", "task": {"task_id": "astropy__astropy-14182", "source": "swe-bench", "repo": "astropy/astropy", "base_commit": null, "problem_statement": "Support header rows in RST writer.", "gold_patch": null, "test_directives": []}, "steps": [{"index": 0, "action_type": "file_read", "content": "astropy/io/ascii/rst.py", "observation": {"content": "<contents>", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 1, "action_type": "file_edit", "content": "partial edit", "observation": {"content": "ok", "exit_code": 0, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": false}, {"index": 2, "action_type": "command", "content": "pytest astropy/io/ascii/tests/test_rst.py", "observation": {"content": "mixed: 2 failed, 1 error, traceback truncated", "exit_code": 1, "truncated": false, "extra": {}}, "timestamp": null, "metadata": {}, "failed": true}], "final_patch": "diff --git a/astropy/io/ascii/rst.py", "test_result": {"passed": false, "total_tests": null, "passed_tests": null, "failed_tests": null, "error_tests": null, "raw_log": ""}, "resolved": false, "wall_time_seconds": null, "total_tokens": null, "total_cost_usd": null, "error": null, "metadata": {}, "step_count": 3, "produced_patch": true, "failed": true, "content_hash": "1c42dc083c207a39"}];
