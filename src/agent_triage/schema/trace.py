"""Normalized agent-run trace schema.

This is the central contract of the system. Every coding agent (OpenHands today,
Devin or SWE-agent tomorrow) emits its own idiosyncratic log format. We normalize
all of them into a single `AgentRun` shape so the triage engine never has to know
which agent produced a trace.

Design notes
------------
- The schema is deliberately *agent-agnostic*. Anything OpenHands-specific lives in
  the adapter (`harness/openhands_adapter.py`), never here.
- Steps are typed by `ActionType` so the classifier can reason over structured
  events (commands, edits, model calls) instead of raw text blobs.
- Every field that the engine keys off of (exit codes, test results, diffs) is a
  first-class attribute, because evidence-grounded classification requires pointing
  at *specific* events, not summarizing prose.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class ActionType(str, Enum):
    """The kind of action an agent took at a given step."""

    MESSAGE = "message"          # agent reasoning / natural-language output
    COMMAND = "command"          # shell command execution
    FILE_EDIT = "file_edit"      # a write/patch to a file
    FILE_READ = "file_read"      # reading a file or directory
    BROWSE = "browse"            # web / docs browsing
    MODEL_CALL = "model_call"    # an LLM inference call
    FINISH = "finish"            # agent declared completion
    ERROR = "error"              # framework-level error (crash, timeout, rate limit)
    UNKNOWN = "unknown"


class Observation(BaseModel):
    """The environment's response to an action (stdout, stderr, exit code, etc.)."""

    content: str = ""
    exit_code: int | None = None
    truncated: bool = False
    # free-form extras an adapter may attach (e.g. browser status, tokens used)
    extra: dict[str, Any] = Field(default_factory=dict)


class Step(BaseModel):
    """A single action+observation pair in the agent's trajectory."""

    index: int
    action_type: ActionType
    # the raw thing the agent did: a command string, a diff, a message
    content: str = ""
    observation: Observation | None = None
    timestamp: datetime | None = None
    # tokens, latency, model name, cost — whatever the adapter can supply
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[misc]
    @property
    def failed(self) -> bool:
        """Heuristic: did the environment reject this action?"""
        if self.observation is None:
            return False
        if self.observation.exit_code is not None and self.observation.exit_code != 0:
            return True
        return self.action_type == ActionType.ERROR


class TestResult(BaseModel):
    __test__ = False  # not a pytest class
    """Outcome of the task's verification (the SWE-bench test patch, in our case)."""

    passed: bool
    total_tests: int | None = None
    passed_tests: int | None = None
    failed_tests: int | None = None
    error_tests: int | None = None
    raw_log: str = ""


class TaskSpec(BaseModel):
    """What the agent was asked to do, and how success is judged."""

    task_id: str
    source: str = "swe-bench"          # provenance: swe-bench, synthetic, internal
    repo: str | None = None
    base_commit: str | None = None
    problem_statement: str = ""
    # the gold patch / test patch we grade against, when available
    gold_patch: str | None = None
    test_directives: list[str] = Field(default_factory=list)


class AgentRun(BaseModel):
    """A complete normalized agent run — the unit the triage engine consumes."""

    run_id: str
    agent: str                          # "openhands", "swe-agent", "devin", ...
    model: str | None = None            # underlying LLM, when known
    task: TaskSpec
    steps: list[Step] = Field(default_factory=list)
    final_patch: str | None = None      # the diff the agent ultimately produced
    test_result: TestResult | None = None
    resolved: bool | None = None        # ground truth: did the run solve the task?
    wall_time_seconds: float | None = None
    total_tokens: int | None = None
    total_cost_usd: float | None = None
    error: str | None = None            # framework-level fatal error, if any
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[misc]
    @property
    def step_count(self) -> int:
        return len(self.steps)

    @computed_field  # type: ignore[misc]
    @property
    def produced_patch(self) -> bool:
        return bool(self.final_patch and self.final_patch.strip())

    @computed_field  # type: ignore[misc]
    @property
    def failed(self) -> bool:
        """A run 'failed' if we have ground truth and it's unresolved."""
        if self.resolved is not None:
            return not self.resolved
        # fall back to test result if no explicit resolution flag
        if self.test_result is not None:
            return not self.test_result.passed
        return False

    @computed_field  # type: ignore[misc]
    @property
    def content_hash(self) -> str:
        """Stable hash of the run's salient content — used for dedup and caching."""
        basis = "|".join(
            [
                self.task.task_id,
                self.agent,
                self.model or "",
                self.final_patch or "",
                str(self.step_count),
            ]
        )
        return hashlib.sha256(basis.encode()).hexdigest()[:16]

    def failed_steps(self) -> list[Step]:
        """All steps the environment rejected — prime evidence for triage."""
        return [s for s in self.steps if s.failed]

    def last_steps(self, n: int = 5) -> list[Step]:
        """The tail of the trajectory, where failures usually surface."""
        return self.steps[-n:]
