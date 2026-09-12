"""
Executor tests for what happens *downstream* of a condition node.

A condition node skips its direct dependents on the branches it didn't choose,
but everything further down — most commonly the End node joining both arms of
an if/else, which is the shape the built-in "conditional" template and every
imported n8n IF workflow produce — used to wait forever on a node that would
never run, and the whole run was then reported failed.

These drive `execute_dag` with stub callables: no DB, no provider, no network.
"""
import asyncio
from dataclasses import dataclass
from typing import Optional

from dag_executor import DagContext, execute_dag


@dataclass
class _Chunk:
    type: str
    content: str = ""
    tool_call: Optional[object] = None
    error: Optional[str] = None


class _StubLLM:
    """Emits one content chunk naming the node, then done."""
    def __init__(self, reply="ok"):
        self.reply = reply

    async def chat_stream(self, messages, system_prompt=None, tools=None):
        yield _Chunk("content", self.reply)
        yield _Chunk("done")


def _context(chosen_branch="true"):
    agent = {"_id": "1", "name": "Stub agent", "provider_id": "p1", "model_id": "m", "system_prompt": None}

    async def get_agent(_agent_id):
        return agent

    async def get_provider(_agent):
        return {"id": "p1"}

    async def build_tools(_agent):
        return None

    async def load_mcp_configs(_agent):
        return []

    async def execute_native_tool(_name, _args):
        return ""

    async def evaluate_condition(_upstream, _user_input, _branches, _prompt):
        return chosen_branch

    async def update_run(_payload):
        return None

    return DagContext(
        get_agent=get_agent,
        get_provider=get_provider,
        create_llm=lambda provider, model_id: _StubLLM(),
        build_tools=build_tools,
        load_mcp_configs=load_mcp_configs,
        execute_native_tool=execute_native_tool,
        evaluate_condition=evaluate_condition,
        update_run=update_run,
        agent_name=lambda a: a["name"],
        agent_id_str=lambda a: a["_id"],
        agent_provider_id=lambda a: a["provider_id"],
        agent_model_id=lambda a: a["model_id"],
        agent_system_prompt=lambda a: a["system_prompt"],
    )


def _agent_step(node_id, depends_on, order, input_branch=None):
    return {"id": node_id, "node_type": "agent", "agent_id": "1", "task": f"do {node_id}",
            "order": order, "depends_on": depends_on, "input_branch": input_branch}


def _run(steps, chosen_branch="true"):
    async def _collect():
        return [ev async for ev in execute_dag(steps, "test", "input", _context(chosen_branch), run_id="r1")]
    events = asyncio.run(_collect())
    done = events[-1]
    assert done["event"] == "workflow_done"
    return done, {r["node_id"]: r for r in done["step_results"]}


IF_ELSE_JOINED = [
    {"id": "start", "node_type": "start", "task": "", "order": 1, "depends_on": []},
    {"id": "cond", "node_type": "condition", "task": "pick", "order": 2, "depends_on": ["start"],
     "config": {"branches": ["true", "false"]}},
    _agent_step("yes", ["cond"], 3, input_branch="true"),
    _agent_step("no", ["cond"], 4, input_branch="false"),
    {"id": "end", "node_type": "end", "task": "", "order": 5, "depends_on": ["yes", "no"]},
]


def test_end_node_joining_both_arms_completes():
    done, results = _run(IF_ELSE_JOINED, chosen_branch="true")
    assert done["status"] == "completed"
    assert results["yes"]["status"] == "completed"
    assert results["no"]["status"] == "skipped"
    assert results["end"]["status"] == "completed"


def test_the_other_branch_behaves_the_same():
    done, results = _run(IF_ELSE_JOINED, chosen_branch="false")
    assert done["status"] == "completed"
    assert results["yes"]["status"] == "skipped"
    assert results["no"]["status"] == "completed"


def test_end_output_carries_only_the_branch_that_ran():
    done, _ = _run(IF_ELSE_JOINED, chosen_branch="true")
    assert done["outputs"]["end"] == done["outputs"]["yes"]
    assert "no" not in done["outputs"]


def test_skips_propagate_down_a_whole_unchosen_branch():
    steps = [
        {"id": "start", "node_type": "start", "task": "", "order": 1, "depends_on": []},
        {"id": "cond", "node_type": "condition", "task": "pick", "order": 2, "depends_on": ["start"],
         "config": {"branches": ["true", "false"]}},
        _agent_step("yes", ["cond"], 3, input_branch="true"),
        _agent_step("no", ["cond"], 4, input_branch="false"),
        _agent_step("no_2", ["no"], 5),        # no branch label of its own
        _agent_step("no_3", ["no_2"], 6),
        {"id": "end", "node_type": "end", "task": "", "order": 7, "depends_on": ["yes", "no_3"]},
    ]
    done, results = _run(steps, chosen_branch="true")
    assert done["status"] == "completed"
    assert [results[n]["status"] for n in ("no", "no_2", "no_3")] == ["skipped"] * 3
    assert results["end"]["status"] == "completed"


def test_a_node_with_one_live_and_one_skipped_parent_still_runs():
    """Fan-in where only one arm was taken: the node runs on what it has."""
    steps = [
        {"id": "start", "node_type": "start", "task": "", "order": 1, "depends_on": []},
        {"id": "cond", "node_type": "condition", "task": "pick", "order": 2, "depends_on": ["start"],
         "config": {"branches": ["true", "false"]}},
        _agent_step("yes", ["cond"], 3, input_branch="true"),
        _agent_step("no", ["cond"], 4, input_branch="false"),
        _agent_step("join", ["yes", "no"], 5),
        {"id": "end", "node_type": "end", "task": "", "order": 6, "depends_on": ["join"]},
    ]
    done, results = _run(steps, chosen_branch="true")
    assert done["status"] == "completed"
    assert results["join"]["status"] == "completed"


def test_a_linear_run_is_unaffected():
    steps = [
        {"id": "start", "node_type": "start", "task": "", "order": 1, "depends_on": []},
        _agent_step("a", ["start"], 2),
        _agent_step("b", ["a"], 3),
        {"id": "end", "node_type": "end", "task": "", "order": 4, "depends_on": ["b"]},
    ]
    done, results = _run(steps)
    assert done["status"] == "completed"
    assert done["skipped"] == 0
    assert all(r["status"] == "completed" for r in results.values())
