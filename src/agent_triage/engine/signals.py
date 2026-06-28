"""Deterministic signal extraction.

Principle: never ask an LLM to do what code can determine deterministically.
Before the model reasons about *why* a run failed, we extract hard, auditable
facts from the trace: non-zero exit codes, known error fingerprints, command
repetition, premature finishes, resource caps, and whether tests ever ran.

These signals do two jobs:
  1. They are fed to the classifier as structured evidence (grounding).
  2. They power a fast, free, rule-based pre-classifier that can short-circuit
     obvious cases (e.g. a rate-limit traceback is INFRA_ERROR with no LLM call).

This makes the system cheaper, faster, and more auditable — and gives the
support engineer concrete step indices to point at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent_triage.schema.trace import ActionType, AgentRun

# Error fingerprints -> (taxonomy code, human label). Order matters: more
# specific patterns first.
ERROR_FINGERPRINTS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"rate.?limit|\b429\b|overloaded_error", re.I), "INFRA_ERROR", "rate limit"),
    (re.compile(r"\b5\d\d\b.*(error|server)|service unavailable", re.I), "INFRA_ERROR", "5xx"),
    (re.compile(r"connection (reset|refused|aborted)|ECONNRESET|read timed out", re.I), "INFRA_ERROR", "network"),
    (re.compile(r"context.?(window|length).*(exceed|too long)|maximum context", re.I),
     "RESOURCE_LIMIT", "context overflow"),
    (re.compile(r"max(imum)?.{0,12}iteration|step limit|reached the limit", re.I), "RESOURCE_LIMIT", "iteration cap"),
    (re.compile(r"\btime(d)?.?out\b|wall.?clock", re.I), "RESOURCE_LIMIT", "timeout"),
    (re.compile(r"modulenotfounderror|no module named|importerror", re.I), "ENVIRONMENT", "missing module"),
    (re.compile(r"could not find a version|no matching distribution|pip.*(error|failed)", re.I),
     "ENVIRONMENT", "dependency install"),
    (re.compile(r"command not found|: not found\b", re.I), "ENVIRONMENT", "missing binary"),
    (re.compile(r"patch (does not|failed to) apply|hunk failed|malformed patch", re.I),
     "TOOL_USE", "patch apply failed"),
    (re.compile(r"IndentationError|SyntaxError:.*unexpected indent", re.I),
     "TOOL_USE", "syntax error in edit"),
    (re.compile(r"no such file or directory", re.I), "CONTEXT_RETRIEVAL", "wrong path"),
    (re.compile(r"assertionerror|assert .*==|expected .* but got", re.I), "REASONING", "assertion failure"),
]


@dataclass
class Signals:
    """Structured, deterministic evidence extracted from a run."""

    produced_patch: bool = False
    no_file_edits: bool = True   # True when no FILE_EDIT actions appear in the trajectory
    ran_tests: bool = False
    tests_passed: bool | None = None
    finished_explicitly: bool = False
    finished_without_testing: bool = False
    finished_on_red: bool = False
    failed_step_indices: list[int] = field(default_factory=list)
    repeated_commands: list[tuple[str, int]] = field(default_factory=list)  # (cmd, count)
    error_fingerprints: list[tuple[int, str, str]] = field(default_factory=list)  # (step, code, label)
    hit_resource_limit: bool = False
    framework_error: bool = False
    catastrophic_edit: bool = False  # patch removes >70% more than it adds (file was gutted)
    verified_without_editing: bool = False  # ran test suite near end with no file edits (VERIFICATION pattern)
    max_step_count: int = 0

    # Level 2 signals — added for REASONING and CONTEXT_RETRIEVAL detection
    unique_files_opened: int = 0       # distinct file paths seen in FILE_READ actions
    edited_files: list[str] = field(default_factory=list)  # files touched by FILE_EDIT actions
    assertion_after_edit: bool = False # test assertion fails AFTER at least one FILE_EDIT → REASONING
    narrow_file_search: bool = False   # <3 unique files opened in a long (>=20 step) run → CONTEXT_RETRIEVAL
    last_edit_step_index: int = -1     # index of the most recent FILE_EDIT step

    def to_dict(self) -> dict:
        return {
            "produced_patch": self.produced_patch,
            "no_file_edits": self.no_file_edits,
            "ran_tests": self.ran_tests,
            "tests_passed": self.tests_passed,
            "finished_explicitly": self.finished_explicitly,
            "finished_without_testing": self.finished_without_testing,
            "finished_on_red": self.finished_on_red,
            "failed_step_indices": self.failed_step_indices,
            "repeated_commands": [
                {"command": c, "count": n} for c, n in self.repeated_commands
            ],
            "error_fingerprints": [
                {"step": s, "code": c, "label": lab} for s, c, lab in self.error_fingerprints
            ],
            "hit_resource_limit": self.hit_resource_limit,
            "framework_error": self.framework_error,
            "catastrophic_edit": self.catastrophic_edit,
            "verified_without_editing": self.verified_without_editing,
            "step_count": self.max_step_count,
            "unique_files_opened": self.unique_files_opened,
            "edited_files": self.edited_files,
            "assertion_after_edit": self.assertion_after_edit,
            "narrow_file_search": self.narrow_file_search,
        }


_FILE_PATH = re.compile(r"(?:^|\s)([a-zA-Z0-9_./-]+\.[a-zA-Z]{1,6})(?:\s|$|:)")
_TEST_CMD = re.compile(r"\b(pytest|tox|unittest|python -m pytest|npm test|go test|nose)\b", re.I)
_RUNTESTS_CMD = re.compile(r"\bruntest(s)?\b", re.I)
_TEST_PASS = re.compile(r"\b(\d+) passed\b|all tests passed|OK\b", re.I)
_TEST_FAIL = re.compile(r"\b(\d+) failed\b|\b(\d+) error(s)?\b|FAILED\b", re.I)


def extract_signals(run: AgentRun) -> Signals:
    """Pull all deterministic signals from a normalized run."""
    sig = Signals()
    sig.produced_patch = run.produced_patch
    sig.max_step_count = run.step_count

    if run.error:
        sig.framework_error = True

    command_counts: dict[str, int] = {}
    last_test_step_passed: bool | None = None
    last_runtests_step_index: int = -1
    last_runtests_exit_ok: bool = False
    files_opened: set[str] = set()
    had_edit_before: bool = False
    _assertion_pat = re.compile(r"assertionerror|assert .*==|expected .* but got", re.I)

    for step in run.steps:
        obs_text = step.observation.content if step.observation else ""

        # file edit tracking (absence = IMPLEMENTATION_STALL signal)
        if step.action_type == ActionType.FILE_EDIT:
            sig.no_file_edits = False
            sig.last_edit_step_index = step.index
            had_edit_before = True
            # extract edited file path from content (first token that looks like a path)
            m = _FILE_PATH.search(step.content or "")
            if m:
                sig.edited_files.append(m.group(1))

        # track unique files opened in FILE_READ actions
        if step.action_type == ActionType.FILE_READ:
            m = _FILE_PATH.search(step.content or "")
            if m:
                files_opened.add(m.group(1))

        # failed steps (non-zero exit / error action)
        if step.failed:
            sig.failed_step_indices.append(step.index)

        # REASONING signal: assertion failure that appears AFTER a file edit.
        # This distinguishes REASONING (right file edited, wrong logic) from
        # IMPLEMENTATION_STALL (never edited) and TOOL_USE (edit failed to apply).
        if had_edit_before and step.failed and _assertion_pat.search(obs_text):
            sig.assertion_after_edit = True

        # Error fingerprints — two constraints eliminate the most common false positives:
        # 1. Only search obs_text (not the command itself): prevents matching "timeout"
        #    when the agent runs `timeout 30 python3 …` as a deliberate shell tool.
        # 2. Only fire on failed steps (exit_code != 0): prevents matching error-like
        #    strings that appear incidentally in successful output — grep line numbers
        #    (e.g. "429:  # comment" or "561:  check_errors(…)"), commit messages
        #    that mention timeout-related features, etc.
        if step.failed:
            for pattern, code, label in ERROR_FINGERPRINTS:
                if pattern.search(obs_text):
                    sig.error_fingerprints.append((step.index, code, label))
                    if code == "RESOURCE_LIMIT":
                        sig.hit_resource_limit = True
                    break  # one fingerprint per step is enough

        # test execution detection
        if step.action_type == ActionType.COMMAND and _TEST_CMD.search(step.content):
            sig.ran_tests = True
            passed = bool(_TEST_PASS.search(obs_text)) and not _TEST_FAIL.search(obs_text)
            failed = bool(_TEST_FAIL.search(obs_text))
            if failed:
                last_test_step_passed = False
            elif passed:
                last_test_step_passed = True

        # runtests harness tracking (for VERIFICATION detection)
        if step.action_type == ActionType.COMMAND and _RUNTESTS_CMD.search(step.content or ""):
            last_runtests_step_index = step.index
            last_runtests_exit_ok = (
                step.observation is not None and step.observation.exit_code == 0
            )

        # command repetition (thrashing signal)
        if step.action_type == ActionType.COMMAND:
            key = step.content.strip()
            command_counts[key] = command_counts.get(key, 0) + 1

        # explicit finish
        if step.action_type == ActionType.FINISH:
            sig.finished_explicitly = True

    # unique files opened (for CONTEXT_RETRIEVAL detection)
    sig.unique_files_opened = len(files_opened)
    # narrow_file_search: long run, no edits, opened very few distinct files
    if sig.max_step_count >= 20 and sig.no_file_edits and sig.unique_files_opened < 3:
        sig.narrow_file_search = True

    # prefer the run's authoritative test result if present
    if run.test_result is not None:
        sig.tests_passed = run.test_result.passed
    else:
        sig.tests_passed = last_test_step_passed

    # repeated commands: 3+ identical invocations is thrashing
    sig.repeated_commands = [(c, n) for c, n in command_counts.items() if n >= 3]

    # finish-quality signals
    if sig.finished_explicitly and not sig.ran_tests:
        sig.finished_without_testing = True
    if sig.finished_explicitly and sig.tests_passed is False:
        sig.finished_on_red = True

    # catastrophic-edit detection: patch removes >70% more content than it adds.
    # A legitimate refactor adds significant content; a catastrophic overwrite adds
    # almost nothing. Threshold: >10 removed lines, and added < 30% of removed.
    if run.final_patch:
        minus_lines = run.final_patch.count("\n-")
        plus_lines = run.final_patch.count("\n+")
        if minus_lines > 10 and plus_lines < minus_lines * 0.3:
            sig.catastrophic_edit = True

    # verified-without-editing: ran the test harness (runtests.py) near the end
    # of the trajectory without making any file edit, and the last runtests
    # invocation succeeded. This is the canonical VERIFICATION pattern: the agent
    # verified the *unmodified* codebase instead of verifying its own fix.
    # Guard: last runtests step must exit 0 (distinguishes from exploration-then-
    # fail runs where the last runtests call fails, e.g. IMPLEMENTATION_STALL).
    if (
        sig.no_file_edits
        and last_runtests_step_index >= 0
        and last_runtests_exit_ok
        and last_runtests_step_index >= sig.max_step_count - max(1, sig.max_step_count // 5)
    ):
        sig.verified_without_editing = True

    return sig


def rule_based_guess(sig: Signals) -> tuple[str, float, str] | None:
    """Cheap, high-precision pre-classification for unambiguous cases.

    Returns (code, confidence, rationale) or None if the case needs the LLM.
    Only fires when the deterministic evidence is strong enough that an LLM
    would add cost without adding accuracy. Confidence is deliberately capped
    below 1.0 — these are heuristics, not ground truth.
    """
    # Catastrophic edit: the patch gutted the file (removed far more than added).
    # This is always a TOOL_USE failure regardless of what errors follow.
    if sig.catastrophic_edit:
        return (
            "TOOL_USE",
            0.78,
            "Catastrophic file edit: patch removes >70% more content than it adds. "
            "The edit deleted critical code (imports, classes, functions) instead of "
            "modifying the target logic.",
        )

    # Infra errors are retryable platform problems — highest precision.
    infra = [f for f in sig.error_fingerprints if f[1] == "INFRA_ERROR"]
    if infra and not sig.produced_patch:
        labels = ", ".join(sorted({f[2] for f in infra}))
        return ("INFRA_ERROR", 0.85, f"Platform error fingerprint(s): {labels}; no patch produced.")

    # Hard resource cap with a clear fingerprint.
    if sig.hit_resource_limit:
        labels = ", ".join(sorted({f[2] for f in sig.error_fingerprints if f[1] == "RESOURCE_LIMIT"}))
        return ("RESOURCE_LIMIT", 0.8, f"Resource-limit fingerprint(s): {labels}.")

    # Bad-edit rule: a TOOL_USE fingerprint (IndentationError, patch failed)
    # when file edits were made but produced no clean patch → the edit itself
    # broke the file. Only fires when no_file_edits=False so it doesn't catch
    # exploration SyntaxErrors in runs that never touched the target file.
    tool_fps = [f for f in sig.error_fingerprints if f[1] == "TOOL_USE"]
    if tool_fps and not sig.no_file_edits and not sig.produced_patch:
        labels = ", ".join(sorted({f[2] for f in tool_fps}))
        return (
            "TOOL_USE",
            0.72,
            f"Tool-use fingerprint(s) after file edit: {labels}; "
            "edit likely corrupted the target file (syntax error or patch failure).",
        )

    # Late-step broken-command rule: if a "missing binary" or "wrong path" error
    # appears in the final 10% of steps with no file edits, a broken command
    # (wrong interpreter name, hardcoded wrong workspace path) explains why the
    # agent never edited. That's TOOL_USE, not IMPLEMENTATION_STALL.
    # "missing module" (import error) is excluded — that's an env issue that
    # appears during mid-exploration testing and doesn't prevent editing.
    late_cutoff = sig.max_step_count - max(2, sig.max_step_count // 10)
    late_cmd_errors = [
        f for f in sig.error_fingerprints
        if f[0] >= late_cutoff and f[2] in {"missing binary", "wrong path"}
    ]
    if late_cmd_errors and sig.no_file_edits and not sig.hit_resource_limit:
        labels = ", ".join(sorted({f[2] for f in late_cmd_errors}))
        return (
            "TOOL_USE",
            0.65,
            f"Broken command in final steps prevented any file edit: {labels}. "
            "Agent used a wrong binary name or hardcoded workspace path.",
        )

    # Produced-patch-with-broken-runner: agent made file edits AND produced a
    # patch while also hitting an ENVIRONMENT "missing binary" fingerprint.
    # A fundamentally broken environment cannot produce a patch — the binary
    # error was a test-execution issue (wrong interpreter name, e.g. "python"
    # vs "python3"), not a setup failure. Root cause: broken verification loop.
    if (
        sig.produced_patch
        and not sig.no_file_edits
        and any(f[1] == "ENVIRONMENT" and f[2] == "missing binary" for f in sig.error_fingerprints)
        and not sig.catastrophic_edit
    ):
        return (
            "VERIFICATION",
            0.65,
            "Agent produced a patch despite a 'missing binary' environment error. "
            "The environment was functional enough to make the fix; the broken "
            "test runner (wrong binary name, e.g. 'python' not found) is a "
            "verification failure, not an environment setup failure.",
        )

    # Verification without editing: agent ran the test harness (runtests.py)
    # near end of run with no file edits and the last runtests call succeeded.
    # This is the "verified unmodified code" VERIFICATION pattern — the agent
    # spent the run running tests on the baseline instead of making a fix.
    if sig.verified_without_editing:
        return (
            "VERIFICATION",
            0.70,
            "Agent ran the test harness near the end of the run without making "
            "any file edit, and tests passed. This indicates the agent verified "
            "the unmodified codebase rather than applying and verifying a fix.",
        )

    # Implementation stall: agent explored extensively but never committed a file
    # edit. Distinguished from RESOURCE_LIMIT by the absence of any edit actions
    # (more turns wouldn't help if the agent never transitions to editing).
    # Requires >= 10 steps so early-failing runs aren't caught here.
    if (
        not sig.produced_patch
        and sig.no_file_edits
        and sig.max_step_count >= 10
        and not any(f[1] == "INFRA_ERROR" for f in sig.error_fingerprints)
    ):
        return (
            "IMPLEMENTATION_STALL",
            0.72,
            f"No file edits in {sig.max_step_count} steps; no patch produced. "
            "Agent explored without committing any change.",
        )

    # Environment broke before the agent could meaningfully work. Only fire if
    # the fingerprint appears early (first quarter of steps) to avoid false
    # positives from import errors encountered mid-exploration.
    early_cutoff = max(3, sig.max_step_count // 4)
    env = [f for f in sig.error_fingerprints if f[1] == "ENVIRONMENT" and f[0] < early_cutoff]
    if env and not sig.produced_patch:
        labels = ", ".join(sorted({f[2] for f in env}))
        return ("ENVIRONMENT", 0.75, f"Environment fingerprint(s) in early steps: {labels}.")

    # REASONING: agent made at least one file edit but a test assertion still fails
    # after the edit. The agent is in the right place but the logic is wrong.
    # Guard: must have actually edited (no_file_edits=False) and assertion fires
    # AFTER the edit (assertion_after_edit=True). Confidence capped at 0.65 because
    # the LLM can sometimes find TOOL_USE evidence in the same trajectory.
    if sig.assertion_after_edit and not sig.no_file_edits and not sig.catastrophic_edit:
        edited = ", ".join(sig.edited_files[:3]) if sig.edited_files else "unknown"
        return (
            "REASONING",
            0.65,
            f"Test assertion failed after file edit on [{edited}]. "
            "Agent reached and modified the correct file but the logic in the edit "
            "does not satisfy the failing test assertion.",
        )

    # CONTEXT_RETRIEVAL: long run, no edits, very few files opened.
    # Agent never explored enough of the repo to find the right location.
    # Confidence is lower (0.60) — a narrow search could also indicate stall-like
    # paralysis where the agent knows what to look for but times out. The LLM can
    # weigh this more carefully when it does not get caught by the stall rule above.
    if sig.narrow_file_search and not sig.hit_resource_limit:
        return (
            "CONTEXT_RETRIEVAL",
            0.60,
            f"Agent opened only {sig.unique_files_opened} distinct file(s) across "
            f"{sig.max_step_count} steps without making any edit. The run likely "
            "failed because the agent never located the relevant code to modify.",
        )

    # Everything else is nuanced — let the LLM weigh the full trajectory.
    return None
