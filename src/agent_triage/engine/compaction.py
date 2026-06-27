"""Trace compaction for classification prompts.

Real agent runs can be hundreds of steps and far exceed a sane prompt budget.
Naively truncating loses the failure (which usually lives at the *end*). We
compact intelligently: always keep the task spec, the failed steps, the
fingerprinted steps, the finish, and the tail — and summarize the rest. This
keeps the evidence the classifier needs while controlling cost.
"""

from __future__ import annotations

from agent_triage.engine.signals import Signals
from agent_triage.schema.trace import ActionType, AgentRun, Step


def _fmt_step(step: Step, max_chars: int = 600) -> str:
    obs = ""
    if step.observation is not None:
        body = step.observation.content or ""
        if len(body) > max_chars:
            body = body[: max_chars // 2] + "\n...[truncated]...\n" + body[-max_chars // 2 :]
        ec = step.observation.exit_code
        obs = f"\n    -> exit={ec} | {body}" if ec is not None else f"\n    -> {body}"
    content = step.content
    if len(content) > max_chars:
        content = content[:max_chars] + "...[truncated]"
    return f"[{step.index}] {step.action_type.value}: {content}{obs}"


def compact_trace(run: AgentRun, sig: Signals, *, keep_tail: int = 6) -> str:
    """Produce an evidence-dense textual view of the run for the LLM."""
    keep: set[int] = set()
    keep.update(sig.failed_step_indices)
    keep.update(s for s, _, _ in sig.error_fingerprints)
    # keep file edits so the LLM can see what was changed (and attribute
    # post-edit errors to the edit, not to the environment)
    keep.update(step.index for step in run.steps if step.action_type == ActionType.FILE_EDIT)
    # always keep the tail
    keep.update(range(max(0, run.step_count - keep_tail), run.step_count))
    # keep the first couple of steps for setup context
    keep.update(range(min(2, run.step_count)))

    parts: list[str] = []
    parts.append("=== TASK ===")
    parts.append(f"task_id: {run.task.task_id}")
    if run.task.repo:
        parts.append(f"repo: {run.task.repo}")
    parts.append("problem_statement:")
    ps = run.task.problem_statement
    parts.append(ps[:1500] + ("...[truncated]" if len(ps) > 1500 else ""))

    parts.append("\n=== DETERMINISTIC SIGNALS ===")
    parts.append(str(sig.to_dict()))

    parts.append("\n=== TRAJECTORY (salient steps) ===")
    last_kept = -1
    for step in run.steps:
        if step.index in keep:
            if last_kept != -1 and step.index - last_kept > 1:
                skipped = step.index - last_kept - 1
                parts.append(f"... [{skipped} step(s) omitted] ...")
            parts.append(_fmt_step(step))
            last_kept = step.index

    if run.final_patch:
        patch = run.final_patch
        parts.append("\n=== FINAL PATCH ===")
        parts.append(patch[:2000] + ("...[truncated]" if len(patch) > 2000 else ""))
    else:
        parts.append("\n=== FINAL PATCH ===\n(none produced)")

    if run.test_result is not None:
        parts.append("\n=== TEST RESULT ===")
        tr = run.test_result
        parts.append(
            f"passed={tr.passed} total={tr.total_tests} "
            f"passed_tests={tr.passed_tests} failed_tests={tr.failed_tests}"
        )
        if tr.raw_log:
            parts.append(tr.raw_log[:800])

    return "\n".join(parts)
