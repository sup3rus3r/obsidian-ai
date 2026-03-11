"""
Sandbox tools — Docker-proxied file/shell tools injected into agents with sandbox_enabled=True.

All subprocess calls use run_in_executor + subprocess.Popen to avoid asyncio.create_subprocess_exec
raising NotImplementedError on Windows (SelectorEventLoop). Paths use // prefix to prevent
Git Bash MSYS path mangling on Windows.
"""

import asyncio
import json
import subprocess
import sys


def _double_slash(path: str) -> str:
    """Convert /path to //path to prevent Git Bash MSYS path mangling on Windows."""
    if sys.platform == "win32" and path.startswith("/") and not path.startswith("//"):
        return "/" + path
    return path


async def _docker_exec(container_id: str, *args: str, stdin_data: bytes | None = None) -> tuple[str, int]:
    """
    Run: docker exec -i [-e TERM=xterm-256color] [-w //workspace] <container> <args...>
    Returns (stdout_text, exit_code).
    Uses run_in_executor so it works on Windows SelectorEventLoop.
    """
    loop = asyncio.get_event_loop()

    cmd = ["docker", "exec", "-i", "-e", "TERM=xterm-256color", "-w", "//workspace", container_id, *args]

    def _run():
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        out, _ = proc.communicate(input=stdin_data, timeout=30)
        return out.decode("utf-8", errors="replace"), proc.returncode

    try:
        output, code = await loop.run_in_executor(None, _run)
    except subprocess.TimeoutExpired:
        output, code = "Error: command timed out after 30s", 1
    except Exception as e:
        output, code = f"Error: {e}", 1

    return output, code


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI-compatible)
# ---------------------------------------------------------------------------

SANDBOX_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "sandbox_bash",
            "description": "Run a shell command inside the Docker sandbox. Working directory is /workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_read",
            "description": "Read the contents of a file inside the Docker sandbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or /workspace-relative file path."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_write",
            "description": "Write content to a file inside the Docker sandbox. Creates parent dirs if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path inside the sandbox."},
                    "content": {"type": "string", "description": "Content to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_ls",
            "description": "List files and directories inside the Docker sandbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list. Defaults to /workspace."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_glob",
            "description": "Find files matching a pattern inside the Docker sandbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Shell glob pattern, e.g. '**/*.py' or 'src/*.ts'."},
                    "directory": {"type": "string", "description": "Directory to search from. Defaults to /workspace."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_grep",
            "description": "Search file contents for a pattern inside the Docker sandbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex or literal string to search for."},
                    "path": {"type": "string", "description": "File or directory to search. Defaults to /workspace."},
                    "recursive": {"type": "boolean", "description": "Search recursively. Default true."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_delete",
            "description": "Delete a file or directory inside the Docker sandbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to delete."},
                    "recursive": {"type": "boolean", "description": "Delete directory recursively. Default false."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_python",
            "description": "Execute Python code inside the Docker sandbox and return stdout/stderr. Uses Python 3.12. Has access to numpy, pandas, matplotlib, scikit-learn, requests, httpx, pytest.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute."},
                    "timeout": {"type": "integer", "description": "Execution timeout in seconds. Default 30."},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_node",
            "description": "Execute JavaScript/TypeScript code inside the Docker sandbox using Node.js 20 (JS) or ts-node (TS). Has access to standard Node.js APIs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "JavaScript or TypeScript code to execute."},
                    "typescript": {"type": "boolean", "description": "Run as TypeScript using ts-node. Default false (plain Node.js)."},
                    "timeout": {"type": "integer", "description": "Execution timeout in seconds. Default 30."},
                },
                "required": ["code"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------

async def execute_sandbox_tool(tool_name: str, arguments_str: str, container_id: str) -> str:
    """Dispatch a sandbox_* tool call to the container and return the result string."""
    try:
        args = json.loads(arguments_str) if arguments_str else {}
    except json.JSONDecodeError:
        args = {}

    if tool_name == "sandbox_bash":
        command = args.get("command", "")
        if not command:
            return json.dumps({"error": "No command provided"})
        out, code = await _docker_exec(container_id, "//bin/sh", "-c", command)
        return json.dumps({"output": out, "exit_code": code})

    elif tool_name == "sandbox_read":
        path = _double_slash(args.get("path", ""))
        if not path:
            return json.dumps({"error": "No path provided"})
        out, code = await _docker_exec(container_id, "cat", path)
        if code != 0:
            return json.dumps({"error": out.strip()})
        return out

    elif tool_name == "sandbox_write":
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            return json.dumps({"error": "No path provided"})
        # Create parent dirs then write via tee
        dir_path = "/".join(path.split("/")[:-1])
        if dir_path:
            await _docker_exec(container_id, "//bin/sh", "-c", f"mkdir -p {_double_slash(dir_path)}")
        _, code = await _docker_exec(
            container_id, "tee", _double_slash(path),
            stdin_data=content.encode("utf-8"),
        )
        return json.dumps({"success": code == 0, "path": path})

    elif tool_name == "sandbox_ls":
        path = _double_slash(args.get("path", "//workspace"))
        out, code = await _docker_exec(container_id, "ls", "-la", path)
        if code != 0:
            return json.dumps({"error": out.strip()})
        return out

    elif tool_name == "sandbox_glob":
        pattern = args.get("pattern", "")
        directory = _double_slash(args.get("directory", "//workspace"))
        if not pattern:
            return json.dumps({"error": "No pattern provided"})
        cmd = f"find {directory} -name '{pattern}' 2>/dev/null | head -100"
        out, code = await _docker_exec(container_id, "//bin/sh", "-c", cmd)
        return out or "(no matches)"

    elif tool_name == "sandbox_grep":
        pattern = args.get("pattern", "")
        path = _double_slash(args.get("path", "//workspace"))
        recursive = args.get("recursive", True)
        if not pattern:
            return json.dumps({"error": "No pattern provided"})
        flags = "-rn" if recursive else "-n"
        cmd = f"grep {flags} '{pattern}' {path} 2>/dev/null | head -100"
        out, code = await _docker_exec(container_id, "//bin/sh", "-c", cmd)
        return out or "(no matches)"

    elif tool_name == "sandbox_delete":
        path = _double_slash(args.get("path", ""))
        recursive = args.get("recursive", False)
        if not path:
            return json.dumps({"error": "No path provided"})
        flag = "-rf" if recursive else "-f"
        out, code = await _docker_exec(container_id, "rm", flag, path)
        return json.dumps({"success": code == 0, "output": out.strip()})

    elif tool_name == "sandbox_python":
        code = args.get("code", "")
        timeout = min(int(args.get("timeout", 30)), 120)
        if not code:
            return json.dumps({"error": "No code provided"})
        loop = asyncio.get_event_loop()

        def _run_python():
            proc = subprocess.Popen(
                ["docker", "exec", "-i", "-w", "//workspace", container_id, "python3", "-c", code],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            try:
                out, _ = proc.communicate(timeout=timeout)
                return out.decode("utf-8", errors="replace"), proc.returncode
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return f"Error: execution timed out after {timeout}s", 1

        try:
            out, code_ = await loop.run_in_executor(None, _run_python)
        except Exception as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"output": out, "exit_code": code_})

    elif tool_name == "sandbox_node":
        code = args.get("code", "")
        use_ts = args.get("typescript", False)
        timeout = min(int(args.get("timeout", 30)), 120)
        if not code:
            return json.dumps({"error": "No code provided"})

        # Write code to a temp file and run it — avoids shell quoting issues with -e flag
        ext = ".ts" if use_ts else ".js"
        tmp_file = f"/workspace/.sandbox_repl_tmp{ext}"
        _, _ = await _docker_exec(
            container_id, "//bin/sh", "-c",
            f"cat > {tmp_file}",
            stdin_data=code.encode("utf-8"),
        )

        runner = "ts-node" if use_ts else "node"
        loop = asyncio.get_event_loop()

        def _run_node():
            proc = subprocess.Popen(
                ["docker", "exec", "-i", "-w", "//workspace", container_id, runner, tmp_file],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            try:
                out, _ = proc.communicate(timeout=timeout)
                return out.decode("utf-8", errors="replace"), proc.returncode
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return f"Error: execution timed out after {timeout}s", 1

        try:
            out, code_ = await loop.run_in_executor(None, _run_node)
        except Exception as e:
            return json.dumps({"error": str(e)})

        # Clean up temp file (best effort)
        await _docker_exec(container_id, "rm", "-f", tmp_file)

        return json.dumps({"output": out, "exit_code": code_})

    return json.dumps({"error": f"Unknown sandbox tool: {tool_name}"})


def is_sandbox_tool(tool_name: str) -> bool:
    """Return True if the tool name is a sandbox tool."""
    return tool_name.startswith("sandbox_")
