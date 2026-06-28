"""SWE-agent -> AgentRun adapter.

SWE-agent (princeton-nlp/SWE-agent) emits trajectories in a different format
from OpenHands. Each record in its evaluation output contains a `trajectory`
list of action/observation dicts plus an `info` block with the final patch and
exit status.

This adapter normalises that format into the agent-agnostic `AgentRun` schema
so the triage engine can process SWE-agent runs alongside OpenHands runs without
any engine changes.

Supported formats
-----------------
1. SWE-agent evaluation JSON (one dict per instance):
   {"instance_id": ..., "model_patch": ..., "trajectory": [...], "info": {...}}

2. SWE-agent JSONL files: one record per line in the above format.

3. A raw trajectory list (list of action/observation dicts) — useful for tests.
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

# SWE-agent action names -> our ActionType
_ACTION_MAP: dict[str, ActionType] = {
    "bash": ActionType.COMMAND,
    "execute_bash": ActionType.COMMAND,
    "python": ActionType.COMMAND,
    "edit": ActionType.FILE_EDIT,
    "create": ActionType.FILE_EDIT,
    "open": ActionType.FILE_READ,
    "read_file": ActionType.FILE_READ,
    "view": ActionType.FILE_READ,
    "scroll_down": ActionType.FILE_READ,
    "scroll_up": ActionType.FILE_READ,
    "search_file": ActionType.COMMAND,
    "search_dir": ActionType.COMMAND,
    "find_file": ActionType.COMMAND,
    "finish": ActionType.FINISH,
    "submit": ActionType.FINISH,
}


def _classify_action(raw_action: str) -> ActionType:
    """Determine ActionType from a SWE-agent action string.

    SWE-agent actions are multi-line strings where the first token is the
    command name: e.g. "bash\npython setup.py install" or "edit file.py\n...".
    """
    first_token = raw_action.strip().split()[0].lower() if raw_action.strip() else ""
    return _ACTION_MAP.get(first_token, ActionType.UNKNOWN)


def _parse_trajectory(trajectory: list[dict[str, Any]]) -> list[Step]:
    """Convert a SWE-agent trajectory list into normalised Steps."""
    steps: list[Step] = []
    for i, event in enumerate(trajectory):
        action_str = str(event.get("action") or "")
        obs_str = str(event.get("observation") or "")

        action_type = _classify_action(action_str)

        # SWE-agent doesn't always emit exit codes; infer from observation text
        exit_code: int | None = None
        if "exit code: 0" in obs_str or obs_str.strip() == "":
            exit_code = 0
        elif any(
            marker in obs_str
            for marker in ("Error", "error", "Traceback", "FAILED", "exit code: 1")
        ):
            exit_code = 1

        observation = Observation(content=obs_str[:4000], exit_code=exit_code) if obs_str else None

        steps.append(
            Step(
                index=i,
                action_type=action_type,
                content=action_str[:2000],
                observation=observation,
            )
        )
    return steps


def from_swebench(
    record: dict[str, Any],
    *,
    run_id: str | None = None,
    task: TaskSpec | None = None,
) -> AgentRun:
    """Convert one SWE-agent evaluation record into an AgentRun.

    Parameters
    ----------
    record:
        A single SWE-agent output record (dict).
    run_id:
        Optional override for the run identifier. Defaults to instance_id.
    task:
        Optional TaskSpec override. If not provided, built from the record's
        instance metadata.
    """
    instance_id = str(record.get("instance_id", "unknown"))
    rid = run_id or f"swe-agent-{instance_id}"

    if task is None:
        swe_instance = record.get("swe_instance") or record.get("instance") or {}
        task = TaskSpec(
            task_id=instance_id,
            source="swe-bench",
            repo=str(swe_instance.get("repo", "")),
            base_commit=str(swe_instance.get("base_commit", "")) or None,
            problem_statement=str(
                swe_instance.get("problem_statement")
                or record.get("problem_statement")
                or "No problem statement provided."
            ),
        )

    trajectory = record.get("trajectory") or []
    steps = _parse_trajectory(trajectory)

    info = record.get("info") or {}
    patch = str(record.get("model_patch") or info.get("submission") or "").strip()
    resolved = bool(record.get("resolved") or info.get("resolved") or False)

    exit_status = str(info.get("exit_status", "")).lower()
    # SWE-agent exit statuses: "submitted", "exit_cost", "exit_context", "exit_error"
    if "error" in exit_status or "cost" in exit_status or "context" in exit_status:
        resolved = False

    model_stats = info.get("model_stats") or {}
    model_name = str(record.get("model_name_or_path") or record.get("model") or "")

    return AgentRun(
        run_id=rid,
        agent="swe-agent",
        model=model_name or None,
        task=task,
        steps=steps,
        final_patch=patch or None,
        resolved=resolved,
        metadata={
            "exit_status": exit_status,
            "api_calls": model_stats.get("api_calls"),
            "tokens_sent": model_stats.get("tokens_sent"),
            "tokens_received": model_stats.get("tokens_received"),
        },
    )


def load_swebench_file(path: str | Path) -> list[AgentRun]:
    """Load all records from a SWE-agent JSONL or JSON file."""
    p = Path(path)
    text = p.read_text()

    # detect JSONL vs JSON array
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    runs: list[AgentRun] = []

    if lines and lines[0].startswith("{"):
        # JSONL: one record per line
        for line in lines:
            try:
                record = json.loads(line)
                runs.append(from_swebench(record))
            except (json.JSONDecodeError, Exception):
                continue
    else:
        # JSON array
        try:
            records = json.loads(text)
            if isinstance(records, list):
                for record in records:
                    runs.append(from_swebench(record))
        except json.JSONDecodeError:
            pass

    return runs
