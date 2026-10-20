"""
Sandbox tools — Docker-proxied file/shell tools injected into agents with sandbox_enabled=True.

All subprocess calls use asyncio.create_subprocess_exec (native async subprocess support,
available on Windows under the default ProactorEventLoop that uvicorn uses here) so a long
docker exec never blocks the event loop — critical for keeping the SSE chat stream flowing
live while a sandbox command is still running. Paths use // prefix to prevent Git Bash MSYS
path mangling on Windows.
"""

import asyncio
import json
import sys
import httpx


def _double_slash(path: str) -> str:
    """Convert /path to //path to prevent Git Bash MSYS path mangling on Windows."""
    if sys.platform == "win32" and path.startswith("/") and not path.startswith("//"):
        return "/" + path
    return path


async def _run_subprocess(cmd: list[str], stdin_data: bytes | None = None, timeout: float = 30) -> tuple[str, int]:
    """Run a command via native async subprocess, with a timeout. Never raises."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as e:
        return f"Error: {e}", 1

    try:
        out, _ = await asyncio.wait_for(proc.communicate(input=stdin_data), timeout=timeout)
        return out.decode("utf-8", errors="replace"), proc.returncode
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"Error: command timed out after {int(timeout)}s", 1
    except Exception as e:
        return f"Error: {e}", 1


async def _docker_exec(container_id: str, *args: str, stdin_data: bytes | None = None, timeout: float = 30) -> tuple[str, int]:
    """
    Run: docker exec -i [-e TERM=xterm-256color] [-w //workspace] <container> <args...>
    Returns (stdout_text, exit_code).
    """
    cmd = ["docker", "exec", "-i", "-e", "TERM=xterm-256color", "-w", "//workspace", container_id, *args]
    return await _run_subprocess(cmd, stdin_data=stdin_data, timeout=timeout)


async def run_docker_command_bytes(args: list[str], timeout: float = 120) -> tuple[bytes, bytes, int]:
    """
    Run a docker CLI command and return raw (stdout_bytes, stderr_bytes, exit_code).
    Unlike _docker_exec/_run_subprocess, stdout is never decoded or merged with
    stderr — required for piping binary data (e.g. a tar stream) through un-corrupted.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        return b"", str(e).encode(), 1
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return out, err, proc.returncode
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return b"", f"command timed out after {int(timeout)}s".encode(), 1


# ---------------------------------------------------------------------------
# Artifact <-> sandbox path bridging (backend-side, never exposed as a tool)
# ---------------------------------------------------------------------------

ARTIFACT_TYPE_TO_EXT = {
    "html": "html", "jsx": "jsx", "tsx": "tsx", "css": "css",
    "javascript": "js", "typescript": "ts", "python": "py",
    "markdown": "md", "json": "json", "svg": "svg",
    "latex": "tex", "text": "txt",
}


def artifact_workspace_path(artifact_id: str, artifact_type: str) -> str:
    """Convention: artifact id/type maps to a fixed file under /workspace."""
    ext = ARTIFACT_TYPE_TO_EXT.get(artifact_type, "txt")
    return f"/workspace/{artifact_id}.{ext}"


async def read_sandbox_file_direct(container_id: str, path: str) -> str | None:
    """Backend-side direct read (no SSE tool_call event). None on any failure/absence."""
    if not container_id:
        return None
    out, code = await _docker_exec(container_id, "cat", _double_slash(path))
    return out if code == 0 else None


async def write_sandbox_file_direct(container_id: str, path: str, content: str) -> bool:
    """Backend-side direct write. False on failure — never raises."""
    if not container_id:
        return False
    dir_path = "/".join(path.split("/")[:-1])
    if dir_path:
        await _docker_exec(container_id, "//bin/sh", "-c", f"mkdir -p {_double_slash(dir_path)}")
    _, code = await _docker_exec(
        container_id, "tee", _double_slash(path),
        stdin_data=content.encode("utf-8"),
    )
    return code == 0


async def wait_for_port_ready(host_port: int, attempts: int = 5, delay_s: float = 1.0) -> bool:
    """Poll http://localhost:{host_port}/ a few times; True once any HTTP response (even non-2xx) arrives."""
    for _ in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.get(f"http://localhost:{host_port}/")
            return True
        except httpx.RequestError:
            await asyncio.sleep(delay_s)
    return False


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI-compatible)
# ---------------------------------------------------------------------------

SANDBOX_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "sandbox_bash",
            "description": "Run a shell command inside the Docker sandbox. Working directory is /workspace. Use for one-shot commands (git clone, npm install, pip install, builds, tests). For commands that run forever (dev servers), use sandbox_start_process instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "timeout": {"type": "integer", "description": "Execution timeout in seconds. Default 30, max 600 (10 min). Raise this for npm install/build/clone of large repos."},
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
    {
        "type": "function",
        "function": {
            "name": "sandbox_start_process",
            "description": "Start a long-running command (dev server, e.g. 'npm run dev', 'uvicorn app:app --host 0.0.0.0 --port 8080 --reload') detached inside the sandbox. Returns immediately. The process must bind to port 8080 to be reachable via the live preview. Use sandbox_process_status / sandbox_read_log to check on it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run detached, must bind to port 8080."},
                    "name": {"type": "string", "description": "Short identifier for this process. Defaults to 'dev'."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_process_status",
            "description": "Check whether a process started with sandbox_start_process is still running, and whether port 8080 is accepting connections.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Process identifier. Defaults to 'dev'."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_read_log",
            "description": "Read the captured stdout/stderr log of a process started with sandbox_start_process.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Process identifier. Defaults to 'dev'."},
                    "lines": {"type": "integer", "description": "Trailing lines to return. Default 200."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_browser_action",
            "description": "Visually inspect a page served by your own running dev server (e.g. after sandbox_start_process) using headless Chromium. mode='screenshot' returns a PNG (base64); mode='snapshot' returns the accessibility tree as JSON — use snapshot to check structure/content, screenshot to visually verify layout/styling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path on your own dev server to visit, e.g. '/' or '/about'. Resolved against http://localhost:8080 (your own server, from inside the sandbox)."},
                    "mode": {"type": "string", "enum": ["screenshot", "snapshot"], "description": "Default 'screenshot'."},
                    "selector": {"type": "string", "description": "Optional CSS selector to scope the screenshot/snapshot to a single element instead of the full page."},
                },
                "required": ["path"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------

async def execute_sandbox_tool(tool_name: str, arguments_str: str, container_id: str, agent=None, db=None, is_mongo: bool = False) -> str:
    """Dispatch a sandbox_* tool call to the container and return the result
    string, with secret-placeholder resolution on the way in (step 4B) and
    exact-value redaction on the way out (step 5) — see secret_placeholder.py's
    module docstring for why building a shell command string is a safe
    injection point (no further code evaluation of the secret happens after
    this), and resolve_secret_placeholders/redact_resolved_values for the
    mechanism. The LLM never sees the real value, only the placeholder it
    wrote and, if the container's output happened to echo it back, a
    [SECRET_REDACTED] marker in its place."""
    from secret_placeholder import resolve_secret_placeholders, contains_secret_placeholder, redact_resolved_values

    try:
        args = json.loads(arguments_str) if arguments_str else {}
    except json.JSONDecodeError:
        args = {}

    resolved_secrets: list[str] = []
    if agent is not None and db is not None:
        _agent_id = agent.get("_id") if isinstance(agent, dict) else agent.id
        if not isinstance(_agent_id, (int, str)):
            _agent_id = str(_agent_id)
        _user_id = agent.get("user_id") if isinstance(agent, dict) else agent.user_id
        for _k, _v in list(args.items()):
            if isinstance(_v, str) and contains_secret_placeholder(_v):
                args[_k], _vals = await resolve_secret_placeholders(_v, _agent_id, _user_id, db, is_mongo=is_mongo)
                resolved_secrets.extend(_vals)

    result = await _execute_sandbox_tool_inner(tool_name, args, container_id)
    return redact_resolved_values(result, resolved_secrets) if resolved_secrets else result


async def _execute_sandbox_tool_inner(tool_name: str, args: dict, container_id: str) -> str:
    if tool_name == "sandbox_bash":
        command = args.get("command", "")
        timeout = min(max(int(args.get("timeout", 30)), 1), 600)
        if not command:
            return json.dumps({"error": "No command provided"})
        out, code = await _docker_exec(container_id, "//bin/sh", "-c", command, timeout=timeout)
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
        out, code_ = await _docker_exec(container_id, "python3", "-c", code, timeout=timeout)
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
        out, code_ = await _docker_exec(container_id, runner, tmp_file, timeout=timeout)

        # Clean up temp file (best effort)
        await _docker_exec(container_id, "rm", "-f", tmp_file)

        return json.dumps({"output": out, "exit_code": code_})

    elif tool_name == "sandbox_start_process":
        command = args.get("command", "")
        proc_name = args.get("name", "dev") or "dev"
        if not command:
            return json.dumps({"error": "No command provided"})
        log_path = f"//workspace/.sandbox/{proc_name}.log"
        pid_path = f"//workspace/.sandbox/{proc_name}.pid"
        await _docker_exec(container_id, "//bin/sh", "-c", "mkdir -p //workspace/.sandbox")
        wrapped = f"nohup {command} > {log_path} 2>&1 & echo $! > {pid_path}"
        _, code = await _docker_exec(container_id, "//bin/sh", "-c", wrapped)
        return json.dumps({"success": code == 0, "name": proc_name, "log_path": log_path})

    elif tool_name == "sandbox_process_status":
        proc_name = args.get("name", "dev") or "dev"
        pid_path = f"//workspace/.sandbox/{proc_name}.pid"
        out, _ = await _docker_exec(
            container_id, "//bin/sh", "-c",
            f"PID=$(cat {pid_path} 2>/dev/null); if [ -n \"$PID\" ] && kill -0 $PID 2>/dev/null; then echo running; else echo stopped; fi",
        )
        running = out.strip() == "running"
        port_out, _ = await _docker_exec(
            container_id, "//bin/bash", "-c",
            "exec 3<>/dev/tcp/127.0.0.1/8080 2>/dev/null && echo open || echo closed",
        )
        port_open = port_out.strip() == "open"
        return json.dumps({
            "name": proc_name,
            "process": "running" if running else "stopped",
            "port_8080": "open" if port_open else "closed",
        })

    elif tool_name == "sandbox_read_log":
        proc_name = args.get("name", "dev") or "dev"
        n = min(max(int(args.get("lines", 200)), 1), 2000)
        log_path = f"//workspace/.sandbox/{proc_name}.log"
        out, _ = await _docker_exec(container_id, "//bin/sh", "-c", f"tail -n {n} {log_path} 2>/dev/null || echo '(no log yet)'")
        return out

    elif tool_name == "sandbox_browser_action":
        path = args.get("path", "/")
        mode = args.get("mode", "screenshot")
        selector = args.get("selector")
        url = f"http://localhost:8080{path if path.startswith('/') else '/' + path}"
        # repr(...) produces valid Python literals (None, 'foo') — json.dumps would emit
        # JSON tokens like null/true that aren't valid Python and crash the generated script.
        script = (
            "import json, base64\n"
            "from playwright.sync_api import sync_playwright\n"
            "with sync_playwright() as p:\n"
            "    browser = p.chromium.launch()\n"
            "    page = browser.new_page()\n"
            f"    page.goto({url!r}, wait_until='networkidle', timeout=15000)\n"
            f"    selector = {selector!r}\n"
            "    target = page.locator(selector) if selector else page\n"
            f"    if {mode!r} == 'screenshot':\n"
            "        print(base64.b64encode(target.screenshot()).decode())\n"
            "    else:\n"
            "        print(json.dumps(page.accessibility.snapshot()))\n"
            "    browser.close()\n"
        )
        out, code = await _docker_exec(container_id, "python3", "-c", script, timeout=30)

        if code != 0:
            return json.dumps({"error": out.strip()})
        if mode == "screenshot":
            return json.dumps({"image_base64": out.strip(), "mime_type": "image/png"})
        return out.strip()

    return json.dumps({"error": f"Unknown sandbox tool: {tool_name}"})


def is_sandbox_tool(tool_name: str) -> bool:
    """Return True if the tool name is a sandbox tool."""
    return tool_name.startswith("sandbox_")
