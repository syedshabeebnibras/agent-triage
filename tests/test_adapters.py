"""Tests for trajectory format adapters: Aider, AutoCodeRover, SWE-bench SDK."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agent_triage.schema.trace import ActionType


# ── Aider adapter ─────────────────────────────────────────────────────────── #

def test_aider_from_json_record_minimal():
    from agent_triage.harness.aider_adapter import from_aider

    record = {
        "instance_id": "django__django-1234",
        "repo": "django/django",
        "files_edited": ["django/db/models.py"],
        "commits": [{"hash": "abc123", "message": "fix: update models"}],
        "error": None,
        "exit_status": 0,
        "model": "gpt-4o",
        "cost": 0.012,
    }
    run = from_aider(record)
    assert run.agent == "aider"
    assert run.task.task_id == "django__django-1234"
    assert run.resolved is True
    assert any(s.action_type == ActionType.FILE_EDIT for s in run.steps)
    assert any(s.action_type == ActionType.FINISH for s in run.steps)


def test_aider_from_json_record_with_error():
    from agent_triage.harness.aider_adapter import from_aider

    record = {
        "instance_id": "astropy__astropy-999",
        "files_edited": [],
        "error": "ModuleNotFoundError: No module named 'astropy'",
        "exit_status": 1,
    }
    run = from_aider(record)
    assert run.resolved is False
    assert any(s.action_type == ActionType.COMMAND for s in run.steps)
    assert any(
        "ModuleNotFoundError" in (s.observation.content if s.observation else "")
        for s in run.steps
    )


def test_aider_from_history_text():
    from agent_triage.harness.aider_adapter import _steps_from_history

    history = """> read the file models.py
Assistant: Let me look at models.py.
Applied edit to models.py
> run pytest
Assistant: Running tests now.
Error: test_models.py::test_foo FAILED
"""
    steps = _steps_from_history(history)
    assert len(steps) >= 1
    action_types = {s.action_type for s in steps}
    assert ActionType.FILE_EDIT in action_types or ActionType.COMMAND in action_types


def test_aider_load_file_jsonl(tmp_path):
    from agent_triage.harness.aider_adapter import load_aider_file

    records = [
        {"instance_id": "repo__repo-1", "files_edited": ["a.py"], "exit_status": 0},
        {"instance_id": "repo__repo-2", "files_edited": [], "error": "crash", "exit_status": 1},
    ]
    p = tmp_path / "runs.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records))
    runs = load_aider_file(p)
    assert len(runs) == 2
    assert runs[0].task.task_id == "repo__repo-1"
    assert runs[1].task.task_id == "repo__repo-2"


def test_aider_load_file_json_array(tmp_path):
    from agent_triage.harness.aider_adapter import load_aider_file

    records = [
        {"instance_id": "repo__repo-3", "files_edited": ["b.py"], "exit_status": 0},
    ]
    p = tmp_path / "runs.json"
    p.write_text(json.dumps(records))
    runs = load_aider_file(p)
    assert len(runs) == 1


# ── AutoCodeRover adapter ─────────────────────────────────────────────────── #

def test_autocoderover_from_minimal_trajectory():
    from agent_triage.harness.autocoderover_adapter import from_autocoderover

    # adapter uses "trajectory" key, not "messages"
    record = {
        "instance_id": "sympy__sympy-12345",
        "model": "gpt-4o",
        "trajectory": [
            {"role": "user", "content": "Fix the bug in sympy/core/add.py"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "search_method_in_file",
                            "arguments": json.dumps({"method_name": "Add", "file_path": "sympy/core/add.py"}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "Found method Add in sympy/core/add.py at line 100",
            },
            {
                "role": "assistant",
                "content": "I found the issue. Let me write the patch.",
                "tool_calls": [
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "write_patch",
                            "arguments": json.dumps({"patch": "diff --git a/sympy/core/add.py"}),
                        },
                    }
                ],
            },
        ],
        "patch": "diff --git a/sympy/core/add.py ...",
        "resolved": False,
    }
    run = from_autocoderover(record)
    assert run.agent == "autocoderover"
    assert run.task.task_id == "sympy__sympy-12345"
    assert len(run.steps) >= 1
    assert run.final_patch == "diff --git a/sympy/core/add.py ..."


def test_autocoderover_write_patch_maps_to_file_edit():
    from agent_triage.harness.autocoderover_adapter import _action_type_from_tool, from_autocoderover

    # write_patch is the ACR equivalent of a file edit — the agent produces a patch
    assert _action_type_from_tool("write_patch") == ActionType.FILE_EDIT

    record = {
        "instance_id": "test__test-1",
        "trajectory": [
            {"role": "user", "content": "fix it"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "write_patch", "arguments": "{}"},
                    }
                ],
            },
        ],
    }
    run = from_autocoderover(record)
    assert any(s.action_type == ActionType.FILE_EDIT for s in run.steps)


def test_autocoderover_load_file(tmp_path):
    from agent_triage.harness.autocoderover_adapter import load_autocoderover_file

    records = [
        {
            "instance_id": "repo__repo-10",
            "trajectory": [
                {"role": "user", "content": "fix"},
                {"role": "assistant", "content": "done"},
            ],
        }
    ]
    p = tmp_path / "traj.json"
    p.write_text(json.dumps(records))
    runs = load_autocoderover_file(p)
    assert len(runs) == 1
    assert runs[0].task.task_id == "repo__repo-10"


def test_autocoderover_load_file_jsonl(tmp_path):
    from agent_triage.harness.autocoderover_adapter import load_autocoderover_file

    records = [
        {"instance_id": "repo__repo-11", "trajectory": [{"role": "user", "content": "fix"}]},
        {"instance_id": "repo__repo-12", "trajectory": [{"role": "user", "content": "fix"}]},
    ]
    p = tmp_path / "traj.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records))
    runs = load_autocoderover_file(p)
    assert len(runs) == 2


# ── OpenHands SDK traces (load_sdk_traces) ────────────────────────────────── #

def test_load_sdk_traces(tmp_path):
    from agent_triage.harness.openhands_adapter import load_sdk_traces

    record = {
        "run_id": "sdk-astropy__astropy-12907",
        "agent": "openhands-sdk",
        "model": "claude-haiku-4-5-20251001",
        "instance_id": "astropy__astropy-12907",
        "repo": "astropy/astropy",
        "problem_statement": "Fix separability_matrix for nested CompoundModels",
        "events": [
            {
                "id": "e1",
                "source": "agent",
                "thought": [{"type": "text", "text": "Let me explore the codebase."}],
                "action": {"kind": "ThinkAction", "thought": "exploring"},
                "tool_name": "think",
            },
            {
                "id": "e2",
                "source": "environment",
                "tool_name": "think",
                "observation": {"content": [{"type": "text", "text": "thought logged"}]},
            },
        ],
        "event_count": 2,
        "resolved": False,
    }
    p = tmp_path / "astropy__astropy-12907.jsonl"
    p.write_text(json.dumps(record) + "\n")
    runs = load_sdk_traces(tmp_path)
    assert len(runs) == 1
    assert runs[0].task.task_id == "astropy__astropy-12907"
    assert runs[0].agent == "openhands"  # load_sdk_traces uses from_openhands which sets agent="openhands"


def test_load_sdk_traces_skips_metadata(tmp_path):
    from agent_triage.harness.openhands_adapter import load_sdk_traces

    (tmp_path / "metadata.json").write_text(json.dumps({"model": "claude-haiku-4-5-20251001"}))
    (tmp_path / "run1.jsonl").write_text(json.dumps({
        "run_id": "sdk-run1",
        "instance_id": "repo__repo-1",
        "repo": "repo/repo",
        "problem_statement": "fix it",
        "events": [],
        "event_count": 0,
        "resolved": False,
    }) + "\n")
    runs = load_sdk_traces(tmp_path)
    assert len(runs) == 1
    assert runs[0].task.task_id == "repo__repo-1"
