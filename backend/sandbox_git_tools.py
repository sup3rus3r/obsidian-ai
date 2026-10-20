"""git operations inside a running Docker sandbox container. Rides along
with the existing sandbox tool machinery (sandbox_tools.py) — no separate
opt-in toggle, since is_sandbox_tool's "sandbox_" prefix check already
matches sandbox_git and it only makes sense when sandbox is already active,
same gating as the other 12 sandbox tools."""

import json
import shlex

SANDBOX_GIT_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "sandbox_git",
            "description": "Run a git operation inside the sandbox container (clone, status, add, commit, push, pull, diff, log, branch, checkout).",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["clone", "status", "add", "commit", "push", "pull", "diff", "log", "branch", "checkout"],
                    },
                    "args": {
                        "type": "string",
                        "description": "Arguments for the operation, e.g. for clone: the repo URL; for commit: the message; for checkout: the branch name.",
                    },
                },
                "required": ["operation"],
            },
        },
    },
]

SANDBOX_GIT_TOOL_NAMES = {s["function"]["name"] for s in SANDBOX_GIT_TOOL_SCHEMAS}

_ALLOWED_OPS = {
    "clone": ["clone"],
    "status": ["status"],
    "add": ["add"],
    "commit": ["commit", "-m"],
    "push": ["push"],
    "pull": ["pull"],
    "diff": ["diff"],
    "log": ["log", "--oneline", "-20"],
    "branch": ["branch"],
    "checkout": ["checkout"],
}


async def execute_sandbox_git_tool(arguments: dict, container_id: str) -> str:
    from sandbox_tools import _docker_exec

    operation = arguments.get("operation", "")
    extra = arguments.get("args", "")

    base = _ALLOWED_OPS.get(operation)
    if base is None:
        return json.dumps({"error": f"Unknown git operation: {operation}"})

    try:
        extra_args = shlex.split(extra) if extra else []
    except ValueError as e:
        return json.dumps({"error": f"Could not parse args: {e}"})

    if operation == "commit":
        # commit message goes right after -m, not appended at the end
        cmd_args = ["git", "commit", "-m", extra] if extra else ["git", "commit"]
    else:
        cmd_args = ["git", *base, *extra_args]

    out, code = await _docker_exec(container_id, *cmd_args)
    return json.dumps({"output": out, "exit_code": code})
