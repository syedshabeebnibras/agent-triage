"""Lightweight SWE-bench Lite smoke runner.

Runs N instances from SWE-bench Lite through a tool-use coding agent backed by
Anthropic, and writes output.jsonl in the OpenHands trajectory format that
agent_triage's adapter consumes.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python scripts/run_swebench_smoke.py --n 10 --out data/openhands_output/output.jsonl

Output per line:
    {"instance_id": ..., "instance": {...}, "history": [...], "git_patch": ..., "resolved": false}
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import anthropic

# ── constants ────────────────────────────────────────────────────────────────

MODEL = os.environ.get("OPENHANDS_MODEL", "claude-haiku-4-5-20251001")
MAX_TURNS = 20
DATASET = "princeton-nlp/SWE-bench_Lite"
SPLIT = "test"

SYSTEM_PROMPT = """You are a world-class software engineer fixing a bug in a Python repository.

You have access to these tools:
- bash: run a shell command in the repo workspace
- view_file: read a file
- edit_file: replace a file's content

Work methodically:
1. Read the problem statement carefully.
2. Explore the repo to find the relevant code.
3. Make the minimal change that fixes the bug.
4. Verify by running the relevant tests.

When you are done, call the finish tool with a brief summary.
"""

TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command in the repository root. Returns stdout+stderr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "view_file",
        "description": "Read the contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": "Overwrite a file with new content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to file"},
                "content": {"type": "string", "description": "New file content"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "finish",
        "description": "Signal that you are done.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What you did"},
            },
            "required": ["summary"],
        },
    },
]


# ── git helpers ───────────────────────────────────────────────────────────────

def _run(cmd: str, cwd: str, timeout: int = 30) -> tuple[str, int]:
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=timeout
    )
    return (result.stdout + result.stderr).strip(), result.returncode


def setup_workspace(instance: dict, tmpdir: str) -> str | None:
    """Clone the repo at the base commit. Returns workspace path or None on failure."""
    repo = instance["repo"]
    commit = instance["base_commit"]
    workspace = os.path.join(tmpdir, repo.replace("/", "__"))

    out, rc = _run(
        f"git clone --depth 200 https://github.com/{repo}.git {workspace}",
        cwd=tmpdir,
        timeout=120,
    )
    if rc != 0:
        return None

    out, rc = _run(f"git checkout {commit}", cwd=workspace, timeout=30)
    if rc != 0:
        # shallow clone may not have the commit; try unshallow
        _run("git fetch --unshallow", cwd=workspace, timeout=120)
        out, rc = _run(f"git checkout {commit}", cwd=workspace, timeout=30)
        if rc != 0:
            return None

    # Install in editable mode so tests can run
    _run("pip install -e . --quiet 2>/dev/null", cwd=workspace, timeout=120)
    return workspace


def get_git_patch(workspace: str) -> str:
    patch, _ = _run("git diff HEAD", cwd=workspace, timeout=10)
    return patch


# ── tool execution ────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict, workspace: str) -> tuple[str, int]:
    if name == "bash":
        return _run(args["command"], cwd=workspace, timeout=60)
    elif name == "view_file":
        path = os.path.join(workspace, args["path"])
        try:
            content = Path(path).read_text(errors="replace")[:8000]
            return content, 0
        except Exception as e:
            return str(e), 1
    elif name == "edit_file":
        path = os.path.join(workspace, args["path"])
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(args["content"])
            return f"Wrote {path}", 0
        except Exception as e:
            return str(e), 1
    elif name == "finish":
        return args.get("summary", ""), 0
    return f"Unknown tool: {name}", 1


# ── OpenHands event helpers ───────────────────────────────────────────────────

def action_event(action: str, **kwargs) -> dict:
    return {"action": action, "source": "agent", **kwargs}


def obs_event(observation: str, content: str, exit_code: int | None = None) -> dict:
    ev = {"observation": observation, "source": "environment", "content": content}
    if exit_code is not None:
        ev["exit_code"] = exit_code
    return ev


# tool → OpenHands action type mapping
_TOOL_TO_ACTION = {
    "bash": "run",
    "view_file": "read",
    "edit_file": "edit",
    "finish": "finish",
}


# ── single-instance runner ────────────────────────────────────────────────────

def run_instance(client: anthropic.Anthropic, instance: dict, workspace: str) -> list[dict]:
    """Run the agent on one instance and return the history event list."""
    problem = instance.get("problem_statement", "Fix the bug described above.")
    history: list[dict] = []
    messages: list[dict] = [{"role": "user", "content": problem}]

    for _turn in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Record what the model said
        for block in response.content:
            if block.type == "text" and block.text.strip():
                history.append(action_event("think", thought=block.text))
            elif block.type == "tool_use":
                action_name = _TOOL_TO_ACTION.get(block.name, "run")
                tool_args = block.input or {}
                cmd_content = tool_args.get("command") or tool_args.get("path") or tool_args.get("summary") or json.dumps(tool_args)[:200]
                history.append(action_event(action_name, command=cmd_content, args=tool_args))

        if response.stop_reason == "end_turn":
            history.append(action_event("finish", summary="Agent stopped (end_turn)"))
            break

        # Execute all tool calls in this turn
        tool_results = []
        done = False
        for block in response.content:
            if block.type != "tool_use":
                continue

            output, exit_code = execute_tool(block.name, block.input or {}, workspace)
            history.append(obs_event(
                "run" if block.name == "bash" else "read",
                content=output[:4000],
                exit_code=exit_code,
            ))

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output[:4000],
            })

            if block.name == "finish":
                done = True

        # Continue the conversation
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        if done:
            break
        time.sleep(0.5)  # gentle rate-limit buffer

    return history


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10, help="Number of instances to run")
    parser.add_argument("--out", default="data/openhands_output/output.jsonl")
    parser.add_argument("--split", default=SPLIT)
    parser.add_argument("--start", type=int, default=0, help="Start index in the dataset")
    parser.add_argument("--append", action="store_true", help="Append to existing output file instead of overwriting")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY is not set.")

    # Import here so we get a clear error if datasets isn't installed
    try:
        from datasets import load_dataset
    except ImportError:
        sys.exit("ERROR: 'datasets' not installed. Run: pip install datasets")

    client = anthropic.Anthropic(api_key=api_key)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading {DATASET} ({args.split} split)...")
    ds = load_dataset(DATASET, split=args.split)
    instances = list(ds)[args.start : args.start + args.n]
    print(f"Running {len(instances)} instances with {MODEL}")

    mode = "a" if args.append else "w"
    with out_path.open(mode) as f_out:
        for i, inst in enumerate(instances):
            iid = inst.get("instance_id", f"unknown-{i}")
            print(f"\n[{i+1}/{len(instances)}] {iid}")

            with tempfile.TemporaryDirectory() as tmpdir:
                workspace = setup_workspace(inst, tmpdir)
                if workspace is None:
                    print(f"  SKIP: could not clone/checkout {inst.get('repo')}")
                    record = {
                        "instance_id": iid,
                        "instance": dict(inst),
                        "history": [],
                        "git_patch": "",
                        "resolved": False,
                        "error": "workspace setup failed",
                    }
                    f_out.write(json.dumps(record) + "\n")
                    f_out.flush()
                    continue

                print(f"  workspace: {workspace}")
                history = run_instance(client, inst, workspace)
                patch = get_git_patch(workspace)

            record = {
                "instance_id": iid,
                "instance": dict(inst),
                "history": history,
                "git_patch": patch,
                "resolved": False,  # would require running the test suite
                "model": MODEL,
            }
            f_out.write(json.dumps(record) + "\n")
            f_out.flush()
            print(f"  done — {len(history)} events, patch length {len(patch)}")

    total = sum(1 for _ in out_path.open())
    print(f"\nWrote {total} records to {out_path}")
    print("Next: python scripts/ingest_openhands.py")


if __name__ == "__main__":
    main()
