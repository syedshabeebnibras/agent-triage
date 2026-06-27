"""Test suite for Agent Triage.

Covers the contracts that matter: schema computed fields, taxonomy integrity,
deterministic signal extraction, rule-based shortcuts, the classifier pipeline
(with the offline mock), evaluation math (including kappa against known values),
and the OpenHands adapter.
"""

from __future__ import annotations

from agent_triage.engine.classifier import TriageClassifier
from agent_triage.engine.signals import extract_signals, rule_based_guess
from agent_triage.eval.metrics import evaluate
from agent_triage.harness.openhands_adapter import from_openhands
from agent_triage.llm.provider import MockProvider, _extract_json
from agent_triage.schema.trace import (
    ActionType,
    AgentRun,
    Observation,
    Step,
    TaskSpec,
    TestResult,
)
from agent_triage.taxonomy.categories import TAXONOMY, all_codes, get, is_valid


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def make_run(steps, **kw) -> AgentRun:
    return AgentRun(
        run_id=kw.get("run_id", "r"),
        agent="openhands",
        model="claude-sonnet-4-6",
        task=TaskSpec(task_id=kw.get("task_id", "t"), problem_statement="p"),
        steps=steps,
        final_patch=kw.get("final_patch"),
        test_result=kw.get("test_result"),
        resolved=kw.get("resolved"),
    )


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #
def test_step_failed_on_nonzero_exit():
    s = Step(index=0, action_type=ActionType.COMMAND, content="x",
             observation=Observation(content="boom", exit_code=1))
    assert s.failed is True


def test_step_not_failed_on_zero_exit():
    s = Step(index=0, action_type=ActionType.COMMAND, content="x",
             observation=Observation(content="ok", exit_code=0))
    assert s.failed is False


def test_run_failed_uses_resolved_flag():
    run = make_run([], resolved=False)
    assert run.failed is True
    run2 = make_run([], resolved=True)
    assert run2.failed is False


def test_content_hash_stable():
    run = make_run([Step(index=0, action_type=ActionType.MESSAGE, content="hi")])
    assert run.content_hash == run.content_hash
    assert len(run.content_hash) == 16


# --------------------------------------------------------------------------- #
# taxonomy
# --------------------------------------------------------------------------- #
def test_taxonomy_codes_consistent():
    for code in all_codes():
        assert get(code).code == code
        assert is_valid(code)
    assert not is_valid("NOPE")


def test_every_category_has_action_and_prevention():
    for c in TAXONOMY.values():
        assert c.recommended_action.strip()
        assert c.prevention.strip()
        assert c.signals


# --------------------------------------------------------------------------- #
# signals
# --------------------------------------------------------------------------- #
def test_signals_detect_missing_module():
    run = make_run([
        Step(index=0, action_type=ActionType.COMMAND, content="pytest",
             observation=Observation(content="ModuleNotFoundError: No module named foo", exit_code=1)),
    ])
    sig = extract_signals(run)
    assert any(c == "ENVIRONMENT" for _, c, _ in sig.error_fingerprints)
    assert 0 in sig.failed_step_indices


def test_signals_detect_repetition():
    steps = [
        Step(index=i, action_type=ActionType.COMMAND, content="make build",
             observation=Observation(content="err", exit_code=1))
        for i in range(3)
    ]
    sig = extract_signals(make_run(steps))
    assert sig.repeated_commands
    assert sig.repeated_commands[0][1] == 3


def test_signals_finished_without_testing():
    run = make_run([
        Step(index=0, action_type=ActionType.FILE_EDIT, content="edit"),
        Step(index=1, action_type=ActionType.FINISH, content="done"),
    ])
    sig = extract_signals(run)
    assert sig.finished_without_testing is True


def test_signals_finished_on_red():
    run = make_run([
        Step(index=0, action_type=ActionType.COMMAND, content="pytest",
             observation=Observation(content="1 failed", exit_code=1)),
        Step(index=1, action_type=ActionType.FINISH, content="done"),
    ], test_result=TestResult(passed=False))
    sig = extract_signals(run)
    assert sig.ran_tests is True
    assert sig.finished_on_red is True


def test_rule_based_guess_infra():
    run = make_run([
        Step(index=0, action_type=ActionType.MODEL_CALL, content="call",
             observation=Observation(content="Error 429 rate limit exceeded", exit_code=1)),
    ])
    sig = extract_signals(run)
    guess = rule_based_guess(sig)
    assert guess is not None
    assert guess[0] == "INFRA_ERROR"


def test_rule_based_guess_returns_none_for_nuanced():
    run = make_run([
        Step(index=0, action_type=ActionType.FILE_EDIT, content="edit paginator.py"),
        Step(index=1, action_type=ActionType.COMMAND, content="pytest",
             observation=Observation(content="AssertionError", exit_code=1)),
    ], final_patch="diff")
    sig = extract_signals(run)
    # has a patch + reasoning-ish fingerprint -> should defer to LLM
    assert rule_based_guess(sig) is None


# --------------------------------------------------------------------------- #
# classifier (offline mock)
# --------------------------------------------------------------------------- #
def test_classifier_rule_path_for_env():
    run = make_run([
        Step(index=0, action_type=ActionType.COMMAND, content="pytest",
             observation=Observation(content="ModuleNotFoundError: No module named x", exit_code=1)),
    ])
    card = TriageClassifier(provider=MockProvider(), use_rules=True).classify(run)
    assert card.primary_category == "ENVIRONMENT"
    assert card.classifier == "rule"
    assert card.owner.value == "environment"


def test_classifier_llm_path_respects_taxonomy():
    run = make_run([
        Step(index=0, action_type=ActionType.FILE_EDIT, content="edit"),
        Step(index=1, action_type=ActionType.COMMAND, content="pytest",
             observation=Observation(content="AssertionError wrong value", exit_code=1)),
        Step(index=2, action_type=ActionType.FINISH, content="done"),
    ], final_patch="diff")
    card = TriageClassifier(provider=MockProvider(forced_code="REASONING"),
                            use_rules=False).classify(run)
    assert is_valid(card.primary_category)
    assert card.primary_category == "REASONING"


def test_classifier_invalid_llm_code_falls_back_to_other():
    run = make_run([Step(index=0, action_type=ActionType.MESSAGE, content="hi")])
    card = TriageClassifier(provider=MockProvider(forced_code="GARBAGE"),
                            use_rules=False).classify(run)
    assert card.primary_category == "OTHER"


def test_card_markdown_renders():
    run = make_run([
        Step(index=0, action_type=ActionType.COMMAND, content="pytest",
             observation=Observation(content="ModuleNotFoundError", exit_code=1)),
    ])
    card = TriageClassifier(provider=MockProvider()).classify(run)
    md = card.to_markdown()
    assert "Root cause" in md
    assert card.primary_category in md


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def test_perfect_accuracy_and_kappa():
    pairs = [("A", "A"), ("B", "B"), ("A", "A"), ("B", "B")]
    rep = evaluate(pairs, bootstrap=False)
    assert rep.accuracy == 1.0
    assert abs(rep.kappa - 1.0) < 1e-9


def test_kappa_zero_for_chance():
    # predictions independent of truth at base rates -> kappa ~ 0
    pairs = [("A", "A"), ("A", "B"), ("B", "A"), ("B", "B")]
    rep = evaluate(pairs, bootstrap=False)
    assert rep.accuracy == 0.5
    assert abs(rep.kappa) < 1e-9


def test_per_class_f1():
    pairs = [("A", "A"), ("A", "A"), ("B", "A"), ("B", "B")]
    rep = evaluate(pairs, bootstrap=False)
    assert "A" in rep.per_class
    assert rep.per_class["A"].support == 2


def test_bootstrap_ci_bounds():
    pairs = [("A", "A")] * 8 + [("B", "B")] * 8 + [("A", "B")] * 4
    rep = evaluate(pairs, bootstrap=True, iterations=200)
    assert rep.accuracy_ci is not None
    lo, hi = rep.accuracy_ci
    assert 0.0 <= lo <= rep.accuracy <= hi <= 1.0


# --------------------------------------------------------------------------- #
# provider json extraction
# --------------------------------------------------------------------------- #
def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_prose():
    assert _extract_json('Here you go: {"a": 1} done') == {"a": 1}


# --------------------------------------------------------------------------- #
# openhands adapter
# --------------------------------------------------------------------------- #
def test_openhands_adapter_basic():
    history = [
        {"action": "run", "command": "pytest", "source": "agent"},
        {"observation": "run", "content": "ModuleNotFoundError", "extras": {"exit_code": 1},
         "source": "environment"},
        {"action": "finish", "source": "agent"},
    ]
    run = from_openhands(history, run_id="oh-1",
                         task=TaskSpec(task_id="x", problem_statement="p"),
                         resolved=False)
    assert run.agent == "openhands"
    assert run.step_count >= 2
    sig = extract_signals(run)
    assert any(c == "ENVIRONMENT" for _, c, _ in sig.error_fingerprints)


def test_openhands_adapter_dict_form():
    traj = {
        "history": [
            {"action": "run", "command": "echo hi", "source": "agent"},
            {"observation": "run", "content": "hi", "extras": {"exit_code": 0},
             "source": "environment"},
        ],
        "model": "claude-sonnet-4-6",
        "git_patch": "diff --git a/x b/x",
        "resolved": False,
    }
    run = from_openhands(traj, run_id="oh-2",
                         task=TaskSpec(task_id="y", problem_statement="p"))
    assert run.model == "claude-sonnet-4-6"
    assert run.produced_patch is True
    assert run.failed is True
