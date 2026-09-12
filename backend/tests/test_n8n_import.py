"""
Tests for the n8n → DAG workflow import (`n8n_import.convert_n8n_workflow`).

Pure logic, no DB and no network — the converter takes an n8n export dict and
returns step dicts. What is asserted here is the structural contract the rest
of the app depends on: every emitted graph is a valid DAG with one start node,
every `depends_on` names a real step, branch labels line up with the condition
node's `config.branches`, and nothing the executor cannot resolve is left in a
task string without a warning.
"""
import pytest

from n8n_import import (
    convert_n8n_workflow,
    slugify,
    short_type,
    is_trigger,
    translate_expressions,
    extract_cron,
    switch_branch_labels,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _node(name, type_, position=(0, 0), **kwargs):
    node = {"id": name.lower().replace(" ", "-"), "name": name, "type": type_,
            "typeVersion": 1, "position": list(position), "parameters": kwargs.pop("parameters", {})}
    node.update(kwargs)
    return node


def _steps_by_id(result):
    return {s["id"]: s for s in result.steps}


def _assert_valid_dag(result):
    """Every invariant `workflows_router._validate_steps` and the executor rely on."""
    ids = [s["id"] for s in result.steps]
    assert len(ids) == len(set(ids)), "duplicate step ids"
    known = set(ids)
    for step in result.steps:
        for dep in step["depends_on"] or []:
            assert dep in known, f"step '{step['id']}' depends on unknown node '{dep}'"

    # acyclic
    adj = {s["id"]: list(s["depends_on"] or []) for s in result.steps}
    state = {i: 0 for i in ids}

    def visit(node):
        state[node] = 1
        for dep in adj[node]:
            assert state[dep] != 1, f"cycle through '{dep}'"
            if state[dep] == 0:
                visit(dep)
        state[node] = 2

    for node in ids:
        if state[node] == 0:
            visit(node)

    starts = [s for s in result.steps if s["node_type"] == "start"]
    assert len(starts) == 1
    assert not starts[0]["depends_on"]

    # Every branch label must be one its condition parent actually offers — the
    # executor compares `input_branch` against the chosen branch verbatim, so a
    # label that isn't in `config.branches` means that step can never run.
    by_id = {s["id"]: s for s in result.steps}
    for step in result.steps:
        label = step["input_branch"]
        if not label:
            continue
        parents = [by_id[d] for d in step["depends_on"] if by_id[d]["node_type"] == "condition"]
        assert parents, f"step '{step['id']}' has a branch label but no condition parent"
        assert any(label in (p["config"] or {}).get("branches", []) for p in parents), (
            f"step '{step['id']}' waits on branch '{label}', which no parent offers"
        )


LINEAR_WORKFLOW = {
    "name": "Daily digest",
    "nodes": [
        _node("Schedule Trigger", "n8n-nodes-base.scheduleTrigger", (0, 0),
              parameters={"rule": {"interval": [{"field": "days", "triggerAtHour": 9, "triggerAtMinute": 30}]}}),
        _node("HTTP Request", "n8n-nodes-base.httpRequest", (200, 0),
              parameters={"method": "GET", "url": "https://api.example.com/items"}),
        _node("Send Email", "n8n-nodes-base.emailSend", (400, 0),
              parameters={"sendTo": "me@example.com", "subject": "Digest"}),
    ],
    "connections": {
        "Schedule Trigger": {"main": [[{"node": "HTTP Request", "type": "main", "index": 0}]]},
        "HTTP Request": {"main": [[{"node": "Send Email", "type": "main", "index": 0}]]},
    },
}


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

def test_short_type_strips_known_prefixes():
    assert short_type("n8n-nodes-base.httpRequest") == "httpRequest"
    assert short_type("@n8n/n8n-nodes-langchain.agent") == "agent"
    assert short_type("customNode") == "customNode"


def test_is_trigger_covers_the_long_tail_by_suffix():
    assert is_trigger("n8n-nodes-base.scheduleTrigger")
    assert is_trigger("n8n-nodes-base.gmailTrigger")
    assert is_trigger("n8n-nodes-base.webhook")
    assert not is_trigger("n8n-nodes-base.httpRequest")


def test_slugify_produces_ids_the_interpolation_grammar_accepts():
    import re
    for name in ["HTTP Request", "Send  Email!!", "Node (v2) — final", "  "]:
        assert re.fullmatch(r"[\w-]+", slugify(name)), name


def test_extract_cron_from_both_trigger_shapes():
    assert extract_cron({"parameters": {"rule": {"interval": [
        {"field": "days", "triggerAtHour": 9, "triggerAtMinute": 30}]}}}) == "30 9 * * *"
    assert extract_cron({"parameters": {"triggerTimes": {"item": [{"mode": "everyHour", "minute": 15}]}}}) == "15 * * * *"
    assert extract_cron({"parameters": {"rule": {"interval": [
        {"field": "cronExpression", "expression": "0 */2 * * *"}]}}}) == "0 */2 * * *"
    assert extract_cron({"parameters": {}}) is None


# ---------------------------------------------------------------------------
# Expression translation
# ---------------------------------------------------------------------------

def test_translates_json_reference_against_the_sole_predecessor():
    out, untranslated = translate_expressions("Subject: {{ $json.title }}", {}, "http-request")
    assert out == "Subject: {{ nodes.http-request.output.title }}"
    assert untranslated == []


def test_json_reference_with_a_fan_in_is_reported_not_guessed():
    out, untranslated = translate_expressions("{{ $json.title }}", {}, None)
    assert out == "{{ $json.title }}"          # left verbatim for the agent to read
    assert untranslated == ["$json.title"]


def test_translates_named_node_references_in_both_syntaxes():
    name_to_id = {"HTTP Request": "http-request"}
    old, _ = translate_expressions('{{ $node["HTTP Request"].json.data[0].id }}', name_to_id, None)
    new, _ = translate_expressions("{{ $('HTTP Request').item.json.data[0].id }}", name_to_id, None)
    assert old == "{{ nodes.http-request.output.data[0].id }}"
    assert new == old


def test_bracket_keys_normalize_to_dot_path():
    out, _ = translate_expressions("{{ $json['user']['name'] }}", {}, "src")
    assert out == "{{ nodes.src.output.user.name }}"


def test_javascript_expressions_are_left_alone_and_reported():
    out, untranslated = translate_expressions("{{ $json.items.map(i => i.id).join(',') }}", {}, "src")
    assert out == "{{ $json.items.map(i => i.id).join(',') }}"
    assert untranslated


# ---------------------------------------------------------------------------
# Conversion — structure
# ---------------------------------------------------------------------------

def test_linear_workflow_converts_to_start_agents_end():
    result = convert_n8n_workflow(LINEAR_WORKFLOW)
    _assert_valid_dag(result)

    steps = _steps_by_id(result)
    assert result.name == "Daily digest"
    assert [s["node_type"] for s in result.steps] == ["start", "agent", "agent", "end"]
    assert steps["http-request"]["depends_on"] == ["start"]
    assert steps["send-email"]["depends_on"] == ["http-request"]
    assert steps["end"]["depends_on"] == ["send-email"]


def test_trigger_becomes_start_and_its_cron_is_reported_not_created():
    result = convert_n8n_workflow(LINEAR_WORKFLOW)
    assert result.schedules == [{"cron_expr": "30 9 * * *", "source_node": "Schedule Trigger"}]
    assert any(w.code == "schedule_not_created" for w in result.warnings)


def test_integration_nodes_keep_their_original_parameters():
    result = convert_n8n_workflow(LINEAR_WORKFLOW)
    http = _steps_by_id(result)["http-request"]
    assert "https://api.example.com/items" in http["task"]
    assert http["config"]["n8n"]["type"] == "n8n-nodes-base.httpRequest"
    assert http["config"]["n8n"]["parameters"]["url"] == "https://api.example.com/items"
    assert any(w.code == "integration_as_agent" for w in result.warnings)


def test_default_agent_is_applied_and_otherwise_reported():
    assigned = convert_n8n_workflow(LINEAR_WORKFLOW, default_agent_id="42")
    assert all(s["agent_id"] == "42" for s in assigned.steps if s["node_type"] == "agent")
    assert assigned.needs_agent == []

    unassigned = convert_n8n_workflow(LINEAR_WORKFLOW)
    assert sorted(unassigned.needs_agent) == ["http-request", "send-email"]


def test_missing_trigger_still_gets_a_start_node():
    workflow = {
        "nodes": [_node("A", "n8n-nodes-base.set"), _node("B", "n8n-nodes-base.set", (200, 0))],
        "connections": {"A": {"main": [[{"node": "B", "type": "main", "index": 0}]]}},
    }
    result = convert_n8n_workflow(workflow)
    _assert_valid_dag(result)
    assert _steps_by_id(result)["a"]["depends_on"] == ["start"]
    assert any(w.code == "start_synthesized" for w in result.warnings)


def test_every_terminal_branch_feeds_the_end_node():
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("A", "n8n-nodes-base.set", (200, 0)),
            _node("B", "n8n-nodes-base.set", (200, 200)),
        ],
        "connections": {"Trigger": {"main": [[
            {"node": "A", "type": "main", "index": 0},
            {"node": "B", "type": "main", "index": 0},
        ]]}},
    }
    result = convert_n8n_workflow(workflow)
    _assert_valid_dag(result)
    assert sorted(_steps_by_id(result)["end"]["depends_on"]) == ["a", "b"]


# ---------------------------------------------------------------------------
# Conversion — branching
# ---------------------------------------------------------------------------

IF_WORKFLOW = {
    "name": "Route by status",
    "nodes": [
        _node("Trigger", "n8n-nodes-base.manualTrigger"),
        _node("IF", "n8n-nodes-base.if", (200, 0), parameters={"conditions": {
            "combinator": "and",
            "conditions": [{"leftValue": "={{ $json.status }}", "rightValue": "open",
                            "operator": {"type": "string", "operation": "equals"}}],
        }}),
        _node("Handle open", "n8n-nodes-base.set", (400, 0)),
        _node("Handle closed", "n8n-nodes-base.set", (400, 200)),
    ],
    "connections": {
        "Trigger": {"main": [[{"node": "IF", "type": "main", "index": 0}]]},
        "IF": {"main": [
            [{"node": "Handle open", "type": "main", "index": 0}],
            [{"node": "Handle closed", "type": "main", "index": 0}],
        ]},
    },
}


def test_if_node_becomes_a_condition_with_true_false_branches():
    result = convert_n8n_workflow(IF_WORKFLOW)
    _assert_valid_dag(result)

    steps = _steps_by_id(result)
    cond = steps["if"]
    assert cond["node_type"] == "condition"
    assert cond["config"]["branches"] == ["true", "false"]
    assert steps["handle-open"]["input_branch"] == "true"
    assert steps["handle-closed"]["input_branch"] == "false"
    # the branch labels the downstream steps carry must exist on the condition
    for step in result.steps:
        if step["input_branch"]:
            assert step["input_branch"] in cond["config"]["branches"]


def test_condition_prompt_describes_the_original_test():
    result = convert_n8n_workflow(IF_WORKFLOW)
    prompt = _steps_by_id(result)["if"]["config"]["condition_prompt"]
    assert "equals" in prompt and "open" in prompt
    assert prompt == _steps_by_id(result)["if"]["task"]


def test_switch_branch_labels_come_from_the_rules():
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("Switch", "n8n-nodes-base.switch", (200, 0), parameters={"rules": {"values": [
                {"outputKey": "urgent"}, {"outputKey": "normal"},
            ]}}),
            _node("Fast", "n8n-nodes-base.set", (400, 0)),
            _node("Slow", "n8n-nodes-base.set", (400, 200)),
        ],
        "connections": {
            "Trigger": {"main": [[{"node": "Switch", "type": "main", "index": 0}]]},
            "Switch": {"main": [
                [{"node": "Fast", "type": "main", "index": 0}],
                [{"node": "Slow", "type": "main", "index": 0}],
            ]},
        },
    }
    result = convert_n8n_workflow(workflow)
    _assert_valid_dag(result)
    steps = _steps_by_id(result)
    assert steps["switch"]["config"]["branches"] == ["urgent", "normal"]
    assert steps["fast"]["input_branch"] == "urgent"
    assert steps["slow"]["input_branch"] == "normal"


def test_a_node_wired_to_both_if_outputs_runs_on_either_branch():
    """n8n runs such a node whichever way the IF goes. Pinning it to one label
    would make the executor skip it on the other."""
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("IF", "n8n-nodes-base.if", (200, 0)),
            _node("Always", "n8n-nodes-base.set", (400, 0)),
        ],
        "connections": {
            "Trigger": {"main": [[{"node": "IF", "type": "main", "index": 0}]]},
            "IF": {"main": [
                [{"node": "Always", "type": "main", "index": 0}],
                [{"node": "Always", "type": "main", "index": 0}],
            ]},
        },
    }
    result = convert_n8n_workflow(workflow)
    _assert_valid_dag(result)
    assert _steps_by_id(result)["always"]["input_branch"] is None
    assert any(w.code == "branch_unconditional" for w in result.warnings)


def test_switch_branches_cover_every_output_the_graph_wires():
    """A Switch with more wired outputs than readable rules still has to offer a
    label for each one, or the extra branches' steps could never run."""
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("Switch", "n8n-nodes-base.switch", (200, 0),
                  parameters={"rules": {"values": [{"outputKey": "a"}]}}),
            _node("First", "n8n-nodes-base.set", (400, 0)),
            _node("Third", "n8n-nodes-base.set", (400, 400)),
        ],
        "connections": {
            "Trigger": {"main": [[{"node": "Switch", "type": "main", "index": 0}]]},
            "Switch": {"main": [
                [{"node": "First", "type": "main", "index": 0}],
                [],
                [{"node": "Third", "type": "main", "index": 0}],
            ]},
        },
    }
    result = convert_n8n_workflow(workflow)
    _assert_valid_dag(result)   # enforces the label/branches invariant
    steps = _steps_by_id(result)
    assert steps["switch"]["config"]["branches"] == ["a", "output_1", "output_2"]
    assert steps["third"]["input_branch"] == "output_2"


def test_switch_v1_rule_shape_is_read():
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("Switch", "n8n-nodes-base.switch", (200, 0),
                  parameters={"rules": {"rules": [{"outputKey": "Urgent"}, {"outputKey": "Normal"}]}}),
            _node("Fast", "n8n-nodes-base.set", (400, 0)),
        ],
        "connections": {
            "Trigger": {"main": [[{"node": "Switch", "type": "main", "index": 0}]]},
            "Switch": {"main": [[{"node": "Fast", "type": "main", "index": 0}]]},
        },
    }
    result = convert_n8n_workflow(workflow)
    assert _steps_by_id(result)["switch"]["config"]["branches"] == ["urgent", "normal"]


def test_fallback_output_adds_a_branch_only_when_it_is_extra():
    extra = {"rules": {"values": [{"outputKey": "a"}]}, "options": {"fallbackOutput": "extra"}}
    routed = {"rules": {"values": [{"outputKey": "a"}]}, "options": {"fallbackOutput": 0}}
    assert switch_branch_labels(extra) == ["a", "fallback"]
    assert switch_branch_labels(routed) == ["a"]


# ---------------------------------------------------------------------------
# Conversion — nodes that are removed or reshaped
# ---------------------------------------------------------------------------

def test_disabled_node_is_skipped_and_its_neighbours_reconnect():
    workflow = {
        "nodes": [
            _node("A", "n8n-nodes-base.set"),
            _node("B", "n8n-nodes-base.set", (200, 0), disabled=True),
            _node("C", "n8n-nodes-base.set", (400, 0)),
        ],
        "connections": {
            "A": {"main": [[{"node": "B", "type": "main", "index": 0}]]},
            "B": {"main": [[{"node": "C", "type": "main", "index": 0}]]},
        },
    }
    result = convert_n8n_workflow(workflow)
    _assert_valid_dag(result)
    steps = _steps_by_id(result)
    assert "b" not in steps
    assert steps["c"]["depends_on"] == ["a"]
    assert any(w.code == "disabled_node_skipped" for w in result.warnings)


def test_noop_node_is_removed_as_a_passthrough():
    workflow = {
        "nodes": [
            _node("A", "n8n-nodes-base.set"),
            _node("NoOp", "n8n-nodes-base.noOp", (200, 0)),
            _node("C", "n8n-nodes-base.set", (400, 0)),
        ],
        "connections": {
            "A": {"main": [[{"node": "NoOp", "type": "main", "index": 0}]]},
            "NoOp": {"main": [[{"node": "C", "type": "main", "index": 0}]]},
        },
    }
    result = convert_n8n_workflow(workflow)
    steps = _steps_by_id(result)
    assert "noop" not in steps
    assert steps["c"]["depends_on"] == ["a"]


def test_sticky_notes_become_description_not_nodes():
    workflow = dict(LINEAR_WORKFLOW)
    workflow = {**LINEAR_WORKFLOW, "nodes": LINEAR_WORKFLOW["nodes"] + [
        _node("Note", "n8n-nodes-base.stickyNote", (0, 400), parameters={"content": "Runs every morning"})
    ]}
    result = convert_n8n_workflow(workflow)
    assert all(s["id"] != "note" for s in result.steps)
    assert "Runs every morning" in (result.description or "")


def test_ai_subnodes_fold_into_their_parent_agent():
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("AI Agent", "@n8n/n8n-nodes-langchain.agent", (200, 0), parameters={"text": "Summarise this"}),
            _node("OpenAI Chat Model", "@n8n/n8n-nodes-langchain.lmChatOpenAi", (200, 200)),
        ],
        "connections": {
            "Trigger": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
            "OpenAI Chat Model": {"ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]},
        },
    }
    result = convert_n8n_workflow(workflow)
    _assert_valid_dag(result)
    steps = _steps_by_id(result)
    assert "openai-chat-model" not in steps
    assert steps["ai-agent"]["task"] == "Summarise this"
    assert steps["ai-agent"]["config"]["n8n"]["attachments"][0]["name"] == "OpenAI Chat Model"
    assert any(w.code == "ai_subnode_folded" for w in result.warnings)


def test_loop_back_edge_is_broken_and_reported():
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("Loop", "n8n-nodes-base.splitInBatches", (200, 0)),
            _node("Body", "n8n-nodes-base.set", (400, 0)),
        ],
        "connections": {
            "Trigger": {"main": [[{"node": "Loop", "type": "main", "index": 0}]]},
            "Loop": {"main": [[], [{"node": "Body", "type": "main", "index": 0}]]},
            "Body": {"main": [[{"node": "Loop", "type": "main", "index": 0}]]},   # the loop back-edge
        },
    }
    result = convert_n8n_workflow(workflow)
    _assert_valid_dag(result)   # would raise on the cycle
    steps = _steps_by_id(result)
    assert steps["loop"]["node_type"] == "map"
    assert steps["loop"]["config"]["input_source"] == "start.output"
    assert any(w.code == "loop_broken" for w in result.warnings)
    assert any(w.code == "loop_to_map" for w in result.warnings)


def test_a_map_step_without_an_agent_is_reported():
    """The executor fails a Map node outright when it has no agent, so it has to
    show up in needs_agent the same way an agent step does."""
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("Loop", "n8n-nodes-base.splitInBatches", (200, 0)),
        ],
        "connections": {"Trigger": {"main": [[{"node": "Loop", "type": "main", "index": 0}]]}},
    }
    result = convert_n8n_workflow(workflow)
    assert "loop" in result.needs_agent
    assert convert_n8n_workflow(workflow, default_agent_id="9").needs_agent == []


def test_a_node_with_both_main_and_ai_outputs_stays_in_the_graph():
    """A sub-node is one that only ever feeds a parent over an ai_* connection.
    Anything with a main output does real work and must not be folded away."""
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("Fetch", "n8n-nodes-base.httpRequest", (200, 0), parameters={"url": "https://x.test"}),
            _node("AI Agent", "@n8n/n8n-nodes-langchain.agent", (400, 0), parameters={"text": "Go"}),
        ],
        "connections": {
            "Trigger": {"main": [[{"node": "Fetch", "type": "main", "index": 0}]]},
            "Fetch": {
                "main": [[{"node": "AI Agent", "type": "main", "index": 0}]],
                "ai_tool": [[{"node": "AI Agent", "type": "ai_tool", "index": 0}]],
            },
        },
    }
    result = convert_n8n_workflow(workflow)
    _assert_valid_dag(result)
    steps = _steps_by_id(result)
    assert "fetch" in steps
    assert steps["ai-agent"]["depends_on"] == ["fetch"]


def test_wait_node_becomes_an_approval_with_a_bounded_timeout():
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("Wait", "n8n-nodes-base.wait", (200, 0), parameters={"resume": "webhook"}),
        ],
        "connections": {"Trigger": {"main": [[{"node": "Wait", "type": "main", "index": 0}]]}},
    }
    result = convert_n8n_workflow(workflow)
    step = _steps_by_id(result)["wait"]
    assert step["node_type"] == "approval"
    assert step["config"]["timeout_seconds"] == 600
    assert step["config"]["on_timeout"] == "fail"
    assert any(w.code == "wait_as_approval" for w in result.warnings)


def test_credentials_are_reported_and_never_copied():
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("Gmail", "n8n-nodes-base.gmail", (200, 0),
                  parameters={"sendTo": "a@example.com"},
                  credentials={"gmailOAuth2": {"id": "7", "name": "Gmail account"}}),
        ],
        "connections": {"Trigger": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]}},
    }
    result = convert_n8n_workflow(workflow)
    stored = _steps_by_id(result)["gmail"]["config"]["n8n"]["credentials"]
    assert stored == ["gmailOAuth2"]          # the name of the credential type only
    assert "7" not in str(stored)
    assert any(w.code == "credentials_required" for w in result.warnings)


# ---------------------------------------------------------------------------
# Conversion — expressions end to end, ids, positions, rejections
# ---------------------------------------------------------------------------

def test_expressions_in_parameters_are_rewritten_to_upstream_step_ids():
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("Fetch", "n8n-nodes-base.httpRequest", (200, 0),
                  parameters={"method": "GET", "url": "https://api.example.com"}),
            _node("Notify", "n8n-nodes-base.slack", (400, 0),
                  parameters={"channel": "#ops", "text": "=Got {{ $json.count }} items"}),
        ],
        "connections": {
            "Trigger": {"main": [[{"node": "Fetch", "type": "main", "index": 0}]]},
            "Fetch": {"main": [[{"node": "Notify", "type": "main", "index": 0}]]},
        },
    }
    result = convert_n8n_workflow(workflow)
    assert "{{ nodes.fetch.output.count }}" in _steps_by_id(result)["notify"]["task"]


def test_json_after_a_condition_resolves_past_it_to_the_real_data():
    """A condition step outputs its branch label, not the items an n8n IF passed
    through — so `$json` downstream of one must point at the condition's own
    upstream, or the agent gets handed the word "true"."""
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("Fetch", "n8n-nodes-base.httpRequest", (200, 0), parameters={"url": "https://x.test"}),
            _node("IF", "n8n-nodes-base.if", (400, 0)),
            _node("Notify", "n8n-nodes-base.slack", (600, 0),
                  parameters={"channel": "#ops", "text": "=Found {{ $json.count }}"}),
        ],
        "connections": {
            "Trigger": {"main": [[{"node": "Fetch", "type": "main", "index": 0}]]},
            "Fetch": {"main": [[{"node": "IF", "type": "main", "index": 0}]]},
            "IF": {"main": [[{"node": "Notify", "type": "main", "index": 0}]]},
        },
    }
    result = convert_n8n_workflow(workflow)
    task = _steps_by_id(result)["notify"]["task"]
    assert "{{ nodes.fetch.output.count }}" in task
    assert "nodes.if.output" not in task


def test_json_on_an_entry_node_resolves_to_the_start_step():
    """The start step's output is the workflow input — the analogue of the
    trigger payload `$json` refers to at the top of an n8n flow."""
    workflow = {
        "nodes": [
            _node("Trigger", "n8n-nodes-base.manualTrigger"),
            _node("First", "n8n-nodes-base.slack", (200, 0),
                  parameters={"channel": "#ops", "text": "=Hello {{ $json.name }}"}),
        ],
        "connections": {"Trigger": {"main": [[{"node": "First", "type": "main", "index": 0}]]}},
    }
    result = convert_n8n_workflow(workflow)
    assert "{{ nodes.start.output.name }}" in _steps_by_id(result)["first"]["task"]
    assert not any(w.code == "expression_not_translated" for w in result.warnings)


def test_duplicate_slugs_get_distinct_ids():
    workflow = {
        "nodes": [
            _node("Send Email", "n8n-nodes-base.set"),
            _node("send email", "n8n-nodes-base.set", (200, 0)),
        ],
        "connections": {"Send Email": {"main": [[{"node": "send email", "type": "main", "index": 0}]]}},
    }
    result = convert_n8n_workflow(workflow)
    _assert_valid_dag(result)
    assert {"send-email", "send-email-2"} <= {s["id"] for s in result.steps}


def test_positions_are_transposed_for_a_top_down_canvas():
    result = convert_n8n_workflow(LINEAR_WORKFLOW)
    steps = _steps_by_id(result)
    # n8n lays out left-to-right (x grows); here the flow runs top-to-bottom (y grows)
    assert steps["send-email"]["position"]["y"] > steps["http-request"]["position"]["y"]
    assert all(s["position"]["x"] >= 0 and s["position"]["y"] >= 0 for s in result.steps)


@pytest.mark.parametrize("bad, message", [
    ([], "top level"),
    ({"foo": "bar"}, "no 'nodes' array"),
    ({"nodes": []}, "no nodes"),
])
def test_input_that_is_not_an_n8n_workflow_is_rejected(bad, message):
    with pytest.raises(ValueError) as excinfo:
        convert_n8n_workflow(bad)
    assert message in str(excinfo.value)


def test_a_workflow_of_only_triggers_is_rejected():
    workflow = {"nodes": [_node("Trigger", "n8n-nodes-base.manualTrigger")], "connections": {}}
    with pytest.raises(ValueError):
        convert_n8n_workflow(workflow)


def test_node_count_is_bounded():
    workflow = {
        "nodes": [_node(f"N{i}", "n8n-nodes-base.set", (i * 10, 0)) for i in range(501)],
        "connections": {},
    }
    with pytest.raises(ValueError) as excinfo:
        convert_n8n_workflow(workflow)
    assert "limit" in str(excinfo.value)
