"""AutoCodeRover -> AgentRun adapter.

AutoCodeRover (nus-apr/auto-code-rover) outputs a JSON report per instance
in its `output/` directory. Each report contains:

    {
      "instance_id": "django__django-12345",
      "trajectory": [
        {
          "role": "assistant" | "user" | "tool",
          "content": "...",
          "tool_calls": [...] | null,
          "tool_call_id": "..." | null
        },
        ...
      ],
      "patch": "diff --git ...",
      "test_output": "...",
      "resolved": true | false
    }

AutoCodeRover uses a message-based trajectory (OpenAI chat format) rather
than discrete action/observation pairs. We map tool_calls to actions and
the subsequent tool response messages to observations.

Supported tool call names:
  search_method_in_file, search_class_in_file, search_code_in_file  → FILE_READ
  search_method, search_class, search_code                           → COMMAND
  get_code_around_issue, get_relevant_code                           → FILE_READ
  write_patch                                                        → FILE_EDIT
  finish                                                             → FINISH
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_triage.schema.trace import (
    ActionType,
    AgentRun,
    Observation,
    Step,
    TaskSpec,
)

_READ_TOOLS = frozenset({
    "search_method_in_file",
    "search_class_in_file",
    "search_code_in_file",
    "get_code_around_issue",
    "get_relevant_code",
    "view_file",
    "open_file",
})

_CMD_TOOLS = frozenset({
    "search_method",
    "search_class",
    "search_code",
    "search_method_in_class",
    "run_test",
    "execute_command",
})

_EDIT_TOOLS = frozenset({
    "write_patch",
    "apply_patch",
    "edit_file",
    "create_file",
    "modify_code",
})

_FINISH_TOOLS = frozenset({"finish", "submit", "done"})


def _action_type_from_tool(tool_name: str) -> ActionType:
    name = tool_name.lower()
    if name in _READ_TOOLS:
        return ActionType.FILE_READ
    if name in _CMD_TOOLS:
        return ActionType.COMMAND
    if name in _EDIT_TOOLS:
        return ActionType.FILE_EDIT
    if name in _FINISH_TOOLS:
        return ActionType.FINISH
    return ActionType.UNKNOWN


def _parse_trajectory(messages: list[dict[str, Any]]) -> list[Step]:
    """Convert AutoCodeRover chat messages into normalised Steps.

    AutoCodeRover uses parallel tool_calls — one assistant message can carry
    multiple tool_calls. We emit one Step per tool call, then attach the
    corresponding tool response message as the observation.
    """
    steps: list[Step] = []
    # map tool_call_id -> observation content
    tool_responses: dict[str, str] = {}

    for msg in messages:
        role = msg.get("role", "")
        if role == "tool":
            tid = str(msg.get("tool_call_id", ""))
            tool_responses[tid] = str(msg.get("content", ""))

    idx = 0
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls") or []
        for tc in tool_calls:
            fn = tc.get("function") or {}
            tool_name = str(fn.get("name", "unknown"))
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {"raw": raw_args}

            action_type = _action_type_from_tool(tool_name)
            content = f"{tool_name}({json.dumps(args)[:300]})"

            tid = str(tc.get("id", ""))
            obs_text = tool_responses.get(tid, "")
            exit_code: int | None = None
            if obs_text:
                lower = obs_text.lower()
                if any(m in lower for m in ("error", "traceback", "not found", "failed")):
                    exit_code = 1
                else:
                    exit_code = 0

            steps.append(Step(
                index=idx,
                action_type=action_type,
                content=content,
                observation=Observation(content=obs_text[:4000], exit_code=exit_code) if obs_text else None,
            ))
            idx += 1

        # plain text assistant message with no tool calls (reasoning / summary)
        if not tool_calls and msg.get("content"):
            steps.append(Step(
                index=idx,
                action_type=ActionType.UNKNOWN,
                content=str(msg["content"])[:2000],
                observation=None,
            ))
            idx += 1

    return steps


def from_autocoderover(
    record: dict[str, Any],
    *,
    run_id: str | None = None,
    task: TaskSpec | None = None,
) -> AgentRun:
    """Convert one AutoCodeRover report into an AgentRun.

    Parameters
    ----------
    record:
        A single AutoCodeRover output record.
    run_id:
        Optional run ID override. Defaults to instance_id.
    task:
        Optional TaskSpec override.
    """
    instance_id = str(record.get("instance_id", "unknown"))
    rid = run_id or f"acr-{instance_id}"

    if task is None:
        task = TaskSpec(
            task_id=instance_id,
            source="swe-bench",
            repo=str(record.get("repo", "")),
            base_commit=str(record.get("base_commit", "")) or None,
            problem_statement=str(
                record.get("problem_statement") or "No problem statement provided."
            ),
        )

    messages = record.get("trajectory") or []
    steps = _parse_trajectory(messages)

    patch = str(record.get("patch", "")).strip()
    resolved = bool(record.get("resolved", False))

    return AgentRun(
        run_id=rid,
        agent="autocoderover",
        model=str(record.get("model", "")) or None,
        task=task,
        steps=steps,
        final_patch=patch or None,
        resolved=resolved,
        metadata={
            "test_output": str(record.get("test_output", ""))[:2000],
            "acr_version": record.get("acr_version"),
        },
    )


def load_autocoderover_file(path: str | Path) -> list[AgentRun]:
    """Load all AutoCodeRover reports from a JSONL or JSON array file."""
    p = Path(path)
    text = p.read_text()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    runs: list[AgentRun] = []

    if lines and lines[0].startswith("{"):
        for line in lines:
            try:
                runs.append(from_autocoderover(json.loads(line)))
            except Exception:
                continue
    else:
        try:
            records = json.loads(text)
            if isinstance(records, list):
                for r in records:
                    runs.append(from_autocoderover(r))
        except json.JSONDecodeError:
            pass

    return runs
