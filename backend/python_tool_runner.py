"""
Runs user-authored Python tool handlers in a separate, locked-down interpreter.

Tool code used to be exec()'d inside the server process, where it could read the
decrypted provider keys and the JWT/encryption secrets in os.environ, and could
hang or crash the server. Each call now gets its own short-lived interpreter:

- isolated mode with no site-packages: standard library only, which is what the
  create_tool instructions already tell agents to write
- an environment with no secrets in it
- a fresh temporary working directory, deleted afterwards
- a wall-clock timeout, plus CPU and memory limits where the OS supports them

This is process isolation, not a filesystem sandbox: the child runs as the same
OS user and can still open any file that user can. Code that must not touch the
host belongs in the Docker sandbox (sandbox_tools.py).
"""

import json
import os
import signal
import subprocess
import sys
import tempfile

TIMEOUT_SECONDS = 30
MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
MAX_OUTPUT_BYTES = 1_000_000

# The base interpreter, not the venv's: -S already hides site-packages, and on
# Windows the venv python.exe is a redirector whose child a kill can miss.
_INTERPRETER = getattr(sys, "_base_executable", None) or sys.executable

# Runs in the child. Reads {"code", "arguments"} from stdin and writes
# {"result": str} or {"error": str} to stdout. The tool's own print() output is
# sent to stderr so it can't corrupt that result.
_BOOTSTRAP = r'''
import json, sys

_result_out = sys.stdout
sys.stdout = sys.stderr

try:
    import resource
    _cpu, _mem = int(sys.argv[1]), int(sys.argv[2])
    resource.setrlimit(resource.RLIMIT_CPU, (_cpu, _cpu))
    resource.setrlimit(resource.RLIMIT_AS, (_mem, _mem))
except (ImportError, ValueError, OSError):
    pass

def _run():
    payload = json.loads(sys.stdin.read())
    namespace = {"__name__": "tool"}
    exec(payload["code"], namespace)
    handler = namespace.get("handler")
    if not handler:
        return {"error": "No 'handler' function found in tool code"}
    result = handler(payload["arguments"])
    return {"result": json.dumps(result) if isinstance(result, (dict, list)) else str(result)}

try:
    _out = _run()
except BaseException as e:
    _out = {"error": str(e)}
_result_out.write(json.dumps(_out))
_result_out.flush()
'''


def _child_env(workdir: str) -> dict:
    if sys.platform == "win32":
        # Winsock and parts of the stdlib need SYSTEMROOT; nothing else is passed through.
        keep = ("SYSTEMROOT", "WINDIR")
    else:
        keep = ("PATH", "LANG", "LC_ALL")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update(TMP=workdir, TEMP=workdir, TMPDIR=workdir)
    return env


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the tool process and anything it spawned."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.kill()
    proc.wait()


def run_python_tool(code: str, arguments: dict) -> str:
    """Execute a tool's `handler(params)` out of process and return its result string.

    Returns the handler's result as a JSON string (dict/list) or str(), or
    json.dumps({"error": ...}) on failure, the same contract the in-process
    exec() versions had.
    """
    payload = json.dumps({"code": code, "arguments": arguments}).encode("utf-8")
    platform_kwargs = (
        {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32"
        else {"start_new_session": True}
    )

    with tempfile.TemporaryDirectory(prefix="pytool-", ignore_cleanup_errors=True) as workdir:
        result_path = os.path.join(workdir, ".result")
        with open(result_path, "wb") as result_file:
            proc = subprocess.Popen(
                [_INTERPRETER, "-I", "-S", "-X", "utf8", "-c", _BOOTSTRAP,
                 str(TIMEOUT_SECONDS), str(MEMORY_LIMIT_BYTES)],
                stdin=subprocess.PIPE,
                stdout=result_file,
                stderr=subprocess.DEVNULL,
                cwd=workdir,
                env=_child_env(workdir),
                **platform_kwargs,
            )
            try:
                proc.communicate(payload, timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                return json.dumps({"error": f"Tool timed out after {TIMEOUT_SECONDS}s"})

        with open(result_path, "rb") as f:
            raw = f.read(MAX_OUTPUT_BYTES + 1)

    if len(raw) > MAX_OUTPUT_BYTES:
        return json.dumps({"error": f"Tool output exceeded {MAX_OUTPUT_BYTES} bytes"})
    try:
        out = json.loads(raw)
    except ValueError:
        out = None
    if not isinstance(out, dict) or not isinstance(out.get("result", out.get("error")), str):
        return json.dumps({"error": f"Tool process exited with code {proc.returncode} without returning a result"})
    if "error" in out:
        return json.dumps({"error": out["error"]})
    return out["result"]
