"""Aider -> AgentRun adapter.

Aider (paul-gauthier/aider) logs its sessions to `.aider.chat.history.md`
(conversation transcript) and optionally writes a `.aider.tags.cache.v3/`
directory for repo-map caching. For evaluation purposes, the most useful
artifact is the `--json` output produced by `aider --json`:

    {
      "model": "gpt-4o",
      "edit_format": "udiff",
      "cost": 0.012,
      "tokens": {"send": 4100, "recv": 320},
      "files_edited": ["src/utils.py"],
      "commits": [{"hash": "abc123", "message": "fix: ..."}],
      "error": null,   # or "error: ..." string if aider crashed
      "exit_status": 0
    }

When `--json` is not available (older aider), we parse the markdown chat
history for action/observation pairs.

Supported input formats
-----------------------
1. `aider --json` output dict (preferred)
2. `.aider.chat.history.md` transcript text
3. A minimal dict with at least `files_edited` and optional `error`
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_triage.schema.trace import (
    ActionType,
    AgentRun,
    Observation,
    Step,
    TaskSpec,
)

_AIDER_CMD = re.compile(r"^> (.+)$", re.MULTILINE)
_AIDER_REPLY = re.compile(r"^([A-Z][a-z]+)\n(.+?)(?=\n>|\Z)", re.DOTALL | re.MULTILINE)
_EDIT_MARKER = re.compile(r"(?:Applied edit|Edited|Updated|Modified)\s+`?([^`\n]+)`?", re.I)
_ERROR_MARKER = re.compile(r"(?:Error|Failed|Traceback|Aider v\S+ is not installed)", re.I)


def _steps_from_json(record: dict[str, Any]) -> list[Step]:
    """Build a minimal but informative step list from aider --json output."""
    steps: list[Step] = []
    idx = 0

    files = record.get("files_edited") or []
    for f in files:
        steps.append(Step(
            index=idx,
            action_type=ActionType.FILE_EDIT,
            content=f"edit {f}",
            observation=Observation(content=f"Applied edit to {f}", exit_code=0),
        ))
        idx += 1

    error = record.get("error")
    if error:
        steps.append(Step(
            index=idx,
            action_type=ActionType.COMMAND,
            content="(aider internal)",
            observation=Observation(content=str(error), exit_code=1),
        ))
        idx += 1

    commits = record.get("commits") or []
    if commits:
        steps.append(Step(
            index=idx,
            action_type=ActionType.FINISH,
            content=f"git commit: {commits[-1].get('message', '')}",
            observation=Observation(content="committed", exit_code=0),
        ))

    return steps


def _steps_from_history(text: str) -> list[Step]:
    """Parse an aider chat history markdown file into Steps."""
    steps: list[Step] = []
    idx = 0
    lines = text.splitlines()
    current_action: str = ""
    current_obs_lines: list[str] = []

    for line in lines:
        if line.startswith("> "):
            if current_action:
                obs_text = "\n".join(current_obs_lines).strip()
                is_edit = bool(_EDIT_MARKER.search(obs_text))
                action_type = ActionType.FILE_EDIT if is_edit else ActionType.COMMAND
                steps.append(Step(
                    index=idx,
                    action_type=action_type,
                    content=current_action[:2000],
                    observation=Observation(
                        content=obs_text[:4000],
                        exit_code=1 if _ERROR_MARKER.search(obs_text) else 0,
                    ) if obs_text else None,
                ))
                idx += 1
            current_action = line[2:].strip()
            current_obs_lines = []
        elif current_action:
            current_obs_lines.append(line)

    if current_action:
        obs_text = "\n".join(current_obs_lines).strip()
        steps.append(Step(
            index=idx,
            action_type=ActionType.FINISH if "commit" in current_action.lower() else ActionType.COMMAND,
            content=current_action[:2000],
            observation=Observation(content=obs_text[:4000], exit_code=0) if obs_text else None,
        ))

    return steps


def from_aider(
    record: dict[str, Any],
    *,
    run_id: str | None = None,
    task: TaskSpec | None = None,
) -> AgentRun:
    """Convert one aider session record into an AgentRun.

    Parameters
    ----------
    record:
        Either an `aider --json` output dict, or a dict with at least:
        - `files_edited` (list[str])
        - `error` (str | None)
        - `exit_status` (int)
        Optional: `model`, `cost`, `tokens`, `commits`, `instance_id`
    run_id:
        Optional run ID override.
    task:
        Optional TaskSpec. If omitted, built from record metadata.
    """
    instance_id = str(record.get("instance_id", record.get("task_id", "aider-run")))
    rid = run_id or f"aider-{instance_id}"

    if task is None:
        task = TaskSpec(
            task_id=instance_id,
            source="aider",
            repo=str(record.get("repo", "")),
            problem_statement=str(record.get("problem_statement", "No problem statement provided.")),
        )

    history = record.get("chat_history", "")
    if history:
        steps = _steps_from_history(str(history))
    else:
        steps = _steps_from_json(record)

    files_edited = record.get("files_edited") or []
    commits = record.get("commits") or []
    error = record.get("error")
    exit_status = int(record.get("exit_status", 1 if error else 0))

    return AgentRun(
        run_id=rid,
        agent="aider",
        model=str(record.get("model", "")) or None,
        task=task,
        steps=steps,
        final_patch=record.get("patch") or (commits[-1].get("diff") if commits else None),
        resolved=exit_status == 0 and not error and bool(files_edited),
        metadata={
            "cost": record.get("cost"),
            "tokens": record.get("tokens"),
            "files_edited": files_edited,
            "edit_format": record.get("edit_format"),
            "error": error,
            "exit_status": exit_status,
        },
    )


def load_aider_file(path: str | Path) -> list[AgentRun]:
    """Load all aider records from a JSONL or JSON array file."""
    p = Path(path)
    text = p.read_text()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    runs: list[AgentRun] = []

    if lines and lines[0].startswith("{"):
        for line in lines:
            try:
                runs.append(from_aider(json.loads(line)))
            except Exception:
                continue
    else:
        try:
            records = json.loads(text)
            if isinstance(records, list):
                for r in records:
                    runs.append(from_aider(r))
        except json.JSONDecodeError:
            pass

    return runs
