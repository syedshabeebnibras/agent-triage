"""OpenHands -> AgentRun adapter.

OpenHands emits its trajectory as a list of events (actions and observations).
This adapter normalizes that into our agent-agnostic `AgentRun`. ALL
OpenHands-specific knowledge lives here; the engine never sees it.

OpenHands event shapes vary by version. This adapter targets the common
`history` / event-stream format where each event has an `action` or
`observation` field. It is defensive: unknown shapes degrade to UNKNOWN steps
rather than crashing, because real-world trace files are messy.

Pair this with the SWE-bench evaluation output, which provides ground-truth
resolution (`resolved`) and the test result. See docs/RUNBOOK_OPENHANDS.md for
how to generate these files.
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
    TestResult,
)

# Map OpenHands action/observation type strings to our ActionType.
_ACTION_MAP = {
    "message": ActionType.MESSAGE,
    "think": ActionType.MESSAGE,
    "run": ActionType.COMMAND,
    "cmd_run": ActionType.COMMAND,
    "run_ipython": ActionType.COMMAND,
    "edit": ActionType.FILE_EDIT,
    "file_edit": ActionType.FILE_EDIT,
    "str_replace_editor": ActionType.FILE_EDIT,
    "write": ActionType.FILE_EDIT,
    "read": ActionType.FILE_READ,
    "file_read": ActionType.FILE_READ,
    "browse": ActionType.BROWSE,
    "browse_interactive": ActionType.BROWSE,
    "finish": ActionType.FINISH,
    "error": ActionType.ERROR,
}


def _classify_event_type(raw_type: str) -> ActionType:
    return _ACTION_MAP.get((raw_type or "").lower(), ActionType.UNKNOWN)


def _event_content(event: dict[str, Any]) -> str:
    """Pull the human-meaningful content out of an OpenHands event."""
    for key in ("command", "code", "content", "thought", "message", "path", "args"):
        val = event.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, dict):
            # e.g. args: {"command": "..."} or {"path": "...", "content": "..."}
            for subkey in ("command", "code", "content", "path"):
                sub = val.get(subkey)
                if isinstance(sub, str) and sub.strip():
                    return sub
    return json.dumps(event.get("args", {}))[:500] if event.get("args") else ""


def _observation_from_event(event: dict[str, Any]) -> Observation | None:
    """Build an Observation from an observation event."""
    content = ""
    for key in ("content", "message", "output"):
        val = event.get(key)
        if isinstance(val, str):
            content = val
            break
    extras = event.get("extras", {}) or {}
    exit_code = None
    for src in (event, extras):
        if isinstance(src, dict) and "exit_code" in src:
            try:
                exit_code = int(src["exit_code"])
            except (TypeError, ValueError):
                pass
    if not content and exit_code is None:
        return None
    return Observation(content=content, exit_code=exit_code, extra=extras if isinstance(extras, dict) else {})


def _parse_history(history: list[dict[str, Any]]) -> list[Step]:
    """Convert an OpenHands event list into normalized Steps.

    Actions become steps; the immediately following observation (if any) is
    attached to its action.
    """
    steps: list[Step] = []
    pending_action: dict[str, Any] | None = None
    idx = 0

    for event in history:
        is_action = "action" in event or event.get("source") == "agent"
        is_observation = "observation" in event or event.get("source") == "environment"

        raw_type = event.get("action") or event.get("observation") or event.get("type") or ""

        if is_observation and pending_action is not None:
            # attach observation to the pending action
            action_type = _classify_event_type(
                pending_action.get("action") or pending_action.get("type") or ""
            )
            step = Step(
                index=idx,
                action_type=action_type,
                content=_event_content(pending_action),
                observation=_observation_from_event(event),
                metadata={"raw_action_type": pending_action.get("action")},
            )
            steps.append(step)
            idx += 1
            pending_action = None
        elif is_action:
            # flush a previous action that had no observation
            if pending_action is not None:
                action_type = _classify_event_type(
                    pending_action.get("action") or pending_action.get("type") or ""
                )
                steps.append(
                    Step(
                        index=idx,
                        action_type=action_type,
                        content=_event_content(pending_action),
                        observation=None,
                    )
                )
                idx += 1
            pending_action = event
        else:
            # standalone observation or unknown — record it
            steps.append(
                Step(
                    index=idx,
                    action_type=_classify_event_type(raw_type),
                    content=_event_content(event),
                    observation=_observation_from_event(event),
                )
            )
            idx += 1

    # flush trailing action
    if pending_action is not None:
        action_type = _classify_event_type(
            pending_action.get("action") or pending_action.get("type") or ""
        )
        steps.append(
            Step(
                index=idx,
                action_type=action_type,
                content=_event_content(pending_action),
                observation=None,
            )
        )

    return steps


def from_openhands(
    trajectory: dict[str, Any] | list[dict[str, Any]],
    *,
    run_id: str,
    task: TaskSpec,
    model: str | None = None,
    resolved: bool | None = None,
    test_result: TestResult | None = None,
    final_patch: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentRun:
    """Normalize one OpenHands trajectory into an AgentRun.

    `trajectory` may be the raw history list, or a dict containing a `history`
    key (the common OpenHands output forms).
    """
    if isinstance(trajectory, dict):
        history = trajectory.get("history") or trajectory.get("events") or []
        model = model or trajectory.get("model")
        final_patch = final_patch or trajectory.get("git_patch") or trajectory.get("test_result", {}).get("git_patch")
        if resolved is None:
            resolved = trajectory.get("resolved")
    else:
        history = trajectory

    steps = _parse_history(history)

    return AgentRun(
        run_id=run_id,
        agent="openhands",
        model=model,
        task=task,
        steps=steps,
        final_patch=final_patch,
        test_result=test_result,
        resolved=resolved,
        metadata=metadata or {},
    )


def load_openhands_output(
    path: str | Path,
    *,
    run_id: str | None = None,
    task: TaskSpec | None = None,
) -> AgentRun:
    """Load a single OpenHands JSON output file and normalize it.

    Convenience for the common case where a file contains one trajectory plus
    SWE-bench metadata. For batch SWE-bench reports, see the runbook.
    """
    with open(path) as f:
        data = json.load(f)

    instance_id = data.get("instance_id") or data.get("instance", {}).get("instance_id", "unknown")
    rid = run_id or f"openhands-{instance_id}"
    spec = task or TaskSpec(
        task_id=instance_id,
        source="swe-bench",
        repo=data.get("instance", {}).get("repo"),
        problem_statement=data.get("instance", {}).get("problem_statement", ""),
    )
    tr = None
    test_block = data.get("test_result") or {}
    if "resolved" in data or "resolved" in test_block:
        resolved = data.get("resolved", test_block.get("resolved"))
        tr = TestResult(passed=bool(resolved))
    else:
        resolved = None

    return from_openhands(
        data,
        run_id=rid,
        task=spec,
        resolved=resolved,
        test_result=tr,
        final_patch=data.get("git_patch") or test_block.get("git_patch"),
    )
