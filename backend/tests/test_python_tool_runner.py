"""Out-of-process execution of user-authored Python tool handlers.

Two things matter: tools that worked in-process keep returning the same
strings, and the child can't see the server's secrets or outlive its timeout.
"""

import json
import os

import pytest

import python_tool_runner
from python_tool_runner import run_python_tool


# ---------------------------------------------------------------- same contract

def test_string_result_is_returned_as_str():
    code = "def handler(params):\n    return params['text'][::-1]"
    assert run_python_tool(code, {"text": "abc"}) == "cba"


def test_dict_result_is_json_encoded():
    code = "def handler(params):\n    return {'sum': params['a'] + params['b']}"
    assert json.loads(run_python_tool(code, {"a": 2, "b": 3})) == {"sum": 5}


def test_non_str_scalar_is_stringified():
    assert run_python_tool("def handler(params):\n    return 42", {}) == "42"


def test_missing_handler_is_an_error():
    out = json.loads(run_python_tool("x = 1", {}))
    assert out == {"error": "No 'handler' function found in tool code"}


def test_empty_code_is_an_error():
    assert "error" in json.loads(run_python_tool("", {}))


def test_handler_exception_is_reported():
    code = "def handler(params):\n    raise ValueError('bad input')"
    assert json.loads(run_python_tool(code, {})) == {"error": "bad input"}


def test_syntax_error_is_reported():
    assert "error" in json.loads(run_python_tool("def handler(:", {}))


def test_print_does_not_corrupt_result():
    code = "def handler(params):\n    print('noise')\n    return 'ok'"
    assert run_python_tool(code, {}) == "ok"


def test_sys_exit_does_not_escape():
    code = "import sys\ndef handler(params):\n    sys.exit(3)"
    assert "error" in json.loads(run_python_tool(code, {}))


def test_top_level_imports_are_visible_in_handler():
    code = "import json\ndef handler(params):\n    return json.dumps([1])"
    assert run_python_tool(code, {}) == "[1]"


def test_unicode_round_trips():
    code = "def handler(params):\n    return params['s'] + ' ✓'"
    assert run_python_tool(code, {"s": "héllo"}) == "héllo ✓"


# ---------------------------------------------------------------- isolation

def test_server_environment_is_not_inherited(monkeypatch):
    monkeypatch.setenv("PROVIDER_KEY_SECRET", "must-not-leak")
    code = "import os\ndef handler(params):\n    return {'secret': os.environ.get('PROVIDER_KEY_SECRET'), 'keys': sorted(os.environ)}"
    out = json.loads(run_python_tool(code, {}))
    assert out["secret"] is None
    assert not any("SECRET" in k or "KEY" in k for k in out["keys"])


def test_third_party_packages_are_not_importable():
    # sqlalchemy is installed in the backend venv; tools get the stdlib only.
    code = "def handler(params):\n    import sqlalchemy\n    return 'imported'"
    assert "error" in json.loads(run_python_tool(code, {}))


def test_runs_in_a_temporary_working_directory():
    code = "import os\ndef handler(params):\n    return os.getcwd()"
    cwd = run_python_tool(code, {})
    assert os.path.basename(cwd).startswith("pytool-")
    assert not os.path.exists(cwd)


def test_server_process_state_is_untouched():
    code = "import os\ndef handler(params):\n    os.environ['LEAK'] = '1'\n    return 'ok'"
    assert run_python_tool(code, {}) == "ok"
    assert "LEAK" not in os.environ


def test_timeout_kills_the_tool(monkeypatch):
    monkeypatch.setattr(python_tool_runner, "TIMEOUT_SECONDS", 2)
    code = "import time\ndef handler(params):\n    time.sleep(30)\n    return 'late'"
    assert json.loads(run_python_tool(code, {})) == {"error": "Tool timed out after 2s"}


def test_oversized_output_is_rejected(monkeypatch):
    monkeypatch.setattr(python_tool_runner, "MAX_OUTPUT_BYTES", 100)
    code = "def handler(params):\n    return 'x' * 1000"
    assert "exceeded" in json.loads(run_python_tool(code, {}))["error"]


@pytest.mark.parametrize("module", ["routers.chat_router", "routers.workflow_runs_router", "scheduler_executor"])
def test_no_in_process_exec_left(module):
    import importlib
    import inspect
    source = inspect.getsource(importlib.import_module(module))
    assert "exec(code_str" not in source
    assert "run_python_tool(" in source
