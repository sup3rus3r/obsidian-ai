"""
n8n → Obsidian AI workflow import.

Converts an exported n8n workflow JSON into this app's DAG step list — the same
`steps` shape `WorkflowCreate` accepts and `dag_executor.execute_dag` runs.

The two models are not isomorphic, and the conversion is lossy in exactly one
direction: n8n is an *integration* engine (hundreds of typed nodes, each doing
one concrete API call) while this app is an *agent* engine (a small set of
control-flow node types plus LLM agents that call tools). So:

  * control flow maps structurally — triggers → start, IF/Switch/Filter →
    condition, splitInBatches → map, Wait → approval, fan-in stays fan-in;
  * every integration node (HTTP Request, Gmail, Set, Code, …) becomes an
    *agent* node whose `task` describes in plain language what the original
    node did, with the original type and `parameters` preserved verbatim under
    `config.n8n` so nothing is silently discarded and the step can be
    re-authored by hand afterwards.

Nothing here evaluates n8n expressions. `{{ $json.x }}` and `{{ $('Node').item.json.y }}`
are rewritten into this app's `{{ nodes.<id>.output.<path> }}` grammar where
that is a mechanical 1:1 translation, and left verbatim (with a warning) where
it is not — the same call `dag_executor.resolve_interpolations` makes: a string
substitution over a constrained grammar, never an evaluator.

Pure functions only: no DB, no network, no I/O. `routers/workflows_router.py`
wraps this and persists the result.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# An import is user-supplied JSON; bound the work it can ask for.
MAX_NODES = 500
MAX_JSON_PARAM_CHARS = 2000   # per-node parameter blob inlined into a task string

BASE_PREFIXES = ("n8n-nodes-base.", "@n8n/n8n-nodes-langchain.", "n8n-nodes-langchain.")

# Node types that start a workflow. Anything whose short type ends in "trigger"
# is treated as one too, which covers the long tail (gmailTrigger, slackTrigger,
# telegramTrigger, …) without enumerating every integration n8n ships.
TRIGGER_TYPES = {"start", "cron", "webhook", "interval", "manualTrigger", "formTrigger"}

# Short type → this app's node_type. Anything absent becomes an agent node.
CONTROL_FLOW_MAP = {
    "if": "condition",
    "switch": "condition",
    "filter": "condition",
    "splitInBatches": "map",
    "loopOverItems": "map",
    "wait": "approval",
}

# Structural no-ops: rewired out of the graph (predecessors joined straight to
# successors) rather than emitted, because this app has no pass-through node.
PASSTHROUGH_TYPES = {"noOp"}

LANGCHAIN_AGENT_TYPES = {"agent", "chainLlm", "chainSummarization", "openAi", "conversationalAgent"}


@dataclass
class ImportWarning:
    level: str                      # "info" | "warning"
    code: str                       # stable machine-readable slug
    message: str
    node: Optional[str] = None      # original n8n node name

    def to_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message, "node": self.node}


@dataclass
class N8nImportResult:
    name: str
    description: Optional[str]
    steps: list[dict]
    warnings: list[ImportWarning] = field(default_factory=list)
    schedules: list[dict] = field(default_factory=list)   # {"cron_expr", "source_node"} — never auto-created
    needs_agent: list[str] = field(default_factory=list)  # step ids left without an agent_id

    def warning_dicts(self) -> list[dict]:
        return [w.to_dict() for w in self.warnings]


# ---------------------------------------------------------------------------
# Names, ids, expressions
# ---------------------------------------------------------------------------

def short_type(node_type: str) -> str:
    """'n8n-nodes-base.httpRequest' -> 'httpRequest' (prefix-stripped, else as-is)."""
    for prefix in BASE_PREFIXES:
        if node_type.startswith(prefix):
            return node_type[len(prefix):]
    return node_type.rsplit(".", 1)[-1] if "." in node_type else node_type


def is_trigger(node_type: str) -> bool:
    st = short_type(node_type)
    return st in TRIGGER_TYPES or st.lower().endswith("trigger")


def slugify(name: str) -> str:
    """n8n node names are free text, but this app's node ids appear inside the
    `{{ nodes.<id>.output }}` grammar whose id group is `[\\w-]+`. Slugify into
    that character set, keeping the name readable rather than using n8n's UUID."""
    slug = re.sub(r"[^\w-]+", "-", name.strip()).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "node"


def _unique_id(base: str, taken: set[str]) -> str:
    candidate = base
    n = 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    taken.add(candidate)
    return candidate


_EXPR_BLOCK_RE = re.compile(r"\{\{(.*?)\}\}", re.S)
_PATH_SEGMENT_RE = re.compile(r"""\.([A-Za-z_]\w*)|\['([^']*)'\]|\["([^"]*)"\]|\[(\d+)\]""")
_JSON_REF_RE = re.compile(r"""^\s*\$json(?P<path>(?:\.[A-Za-z_]\w*|\['[^']*'\]|\["[^"]*"\]|\[\d+\])*)\s*$""")
_NODE_REF_RE = re.compile(
    r"""^\s*(?:
            \$node\[\s*(?P<q1>['"])(?P<n1>.*?)(?P=q1)\s*\]
          | \$\(\s*(?P<q2>['"])(?P<n2>.*?)(?P=q2)\s*\)
        )
        (?:\.item|\.first\(\)|\.last\(\)|\.all\(\)\[\d+\])?
        \.json
        (?P<path>(?:\.[A-Za-z_]\w*|\['[^']*'\]|\["[^"]*"\]|\[\d+\])*)\s*$""",
    re.X,
)


def _normalize_path(raw_path: str) -> Optional[str]:
    """`['items'][0].name` -> `items[0].name`, or None if a key falls outside the
    word-character path grammar `dag_executor._resolve_path` can walk."""
    out = ""
    for dotted, single, double, index in _PATH_SEGMENT_RE.findall(raw_path or ""):
        key = dotted or single or double
        if key:
            if not re.fullmatch(r"\w+", key):
                return None
            out += f".{key}" if out else key
        else:
            out += f"[{index}]"
    return out


def translate_expressions(
    text: str, name_to_id: dict[str, str], sole_predecessor: Optional[str]
) -> tuple[str, list[str]]:
    """Rewrite n8n expressions into this app's interpolation grammar.

    Returns (translated_text, untranslatable_expressions). `$json.x` resolves
    only when the node has exactly one predecessor — with a fan-in there is no
    single "incoming item" to point at, so it is reported rather than guessed.
    Untranslatable expressions are left verbatim: the agent then sees the
    original n8n source text, which is more useful than a blank.
    """
    if not text or "{{" not in text:
        return text, []

    untranslated: list[str] = []

    def _replace(m: "re.Match") -> str:
        inner = m.group(1)

        node_ref = _NODE_REF_RE.match(inner)
        if node_ref:
            src_name = node_ref.group("n1") or node_ref.group("n2")
            node_id = name_to_id.get(src_name)
            path = _normalize_path(node_ref.group("path"))
            if node_id and path is not None:
                return "{{ nodes." + node_id + ".output" + ("." + path if path else "") + " }}"
            untranslated.append(inner.strip())
            return m.group(0)

        json_ref = _JSON_REF_RE.match(inner)
        if json_ref:
            path = _normalize_path(json_ref.group("path"))
            if sole_predecessor and path is not None:
                return "{{ nodes." + sole_predecessor + ".output" + ("." + path if path else "") + " }}"
            untranslated.append(inner.strip())
            return m.group(0)

        untranslated.append(inner.strip())
        return m.group(0)

    return _EXPR_BLOCK_RE.sub(_replace, text), untranslated


def _param_str(value: Any) -> str:
    """Render one n8n parameter for inlining into a task sentence. n8n stores
    expression-valued parameters with a leading '=' — strip it."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value[1:] if value.startswith("=") else value
    if isinstance(value, (int, float, bool)):
        return str(value)
    blob = json.dumps(value, ensure_ascii=False)
    return blob if len(blob) <= MAX_JSON_PARAM_CHARS else blob[:MAX_JSON_PARAM_CHARS] + "…(truncated)"


# ---------------------------------------------------------------------------
# Task text: what the original node did, in a sentence an agent can act on
# ---------------------------------------------------------------------------

def _describe_http(p: dict) -> str:
    method = _param_str(p.get("method") or "GET").upper()
    url = _param_str(p.get("url") or "(no URL set)")
    body = p.get("bodyParameters") or p.get("jsonBody") or p.get("body")
    line = f"Make an HTTP {method} request to {url} and return the response body."
    if body:
        line += f" Request body: {_param_str(body)}"
    return line


def _describe_set(p: dict) -> str:
    # v3 ("assignments.assignments") and v2 ("values.string" / "fields.values") shapes.
    assignments = ((p.get("assignments") or {}).get("assignments")) or ((p.get("fields") or {}).get("values"))
    if assignments and isinstance(assignments, list):
        pairs = ", ".join(
            f"{_param_str(a.get('name'))} = {_param_str(a.get('value'))}"
            for a in assignments if isinstance(a, dict)
        )
        return f"Produce a JSON object with these fields set: {pairs}. Return only the JSON."
    values = p.get("values")
    if values:
        return f"Produce a JSON object with these fields set: {_param_str(values)}. Return only the JSON."
    return "Produce a JSON object with the fields the original n8n Set node defined. Return only the JSON."


def _describe_code(p: dict) -> str:
    code = _param_str(p.get("jsCode") or p.get("pythonCode") or p.get("functionCode") or "")
    lang = "Python" if p.get("pythonCode") else "JavaScript"
    return (
        "Apply the transformation this {lang} snippet performed, to the upstream input, "
        "and return the result as JSON:\n\n{code}"
    ).format(lang=lang, code=code)


def _describe_email(p: dict) -> str:
    to = _param_str(p.get("sendTo") or p.get("toEmail") or p.get("to") or "(recipient unset)")
    subject = _param_str(p.get("subject") or "")
    return f"Draft an email to {to}" + (f" with the subject '{subject}'" if subject else "") + ", then send it."


def _describe_slack(p: dict) -> str:
    channel = p.get("channel") or p.get("channelId")
    if isinstance(channel, dict):   # resource-locator form: {mode, value, cachedResultName}
        channel = channel.get("cachedResultName") or channel.get("value")
    channel = _param_str(channel) or "(channel unset)"
    text = _param_str(p.get("text") or "")
    return f"Post a message to the Slack channel {channel}" + (f": {text}" if text else ".")


def _describe_llm(p: dict) -> str:
    prompt = _param_str(
        p.get("text") or p.get("prompt") or ((p.get("messages") or {}).get("values") if isinstance(p.get("messages"), dict) else None) or ""
    )
    return prompt or "Answer the request from the upstream input."


def _describe_merge(p: dict) -> str:
    return "Combine the upstream outputs into a single result, preserving the information in each."


TASK_BUILDERS = {
    "httpRequest": _describe_http,
    "webhook": _describe_http,
    "set": _describe_set,
    "code": _describe_code,
    "function": _describe_code,
    "functionItem": _describe_code,
    "emailSend": _describe_email,
    "gmail": _describe_email,
    "slack": _describe_slack,
    "merge": _describe_merge,
    "agent": _describe_llm,
    "chainLlm": _describe_llm,
    "openAi": _describe_llm,
    "conversationalAgent": _describe_llm,
}


def build_task(node: dict) -> str:
    """A plain-language task for an agent node, derived from the original node."""
    name = node.get("name", "")
    node_type = node.get("type", "")
    st = short_type(node_type)
    params = node.get("parameters") or {}

    builder = TASK_BUILDERS.get(st)
    if builder:
        try:
            return builder(params)
        except Exception:  # noqa: BLE001 — a malformed export must not abort the import
            pass

    detail = _param_str(params) if params else ""
    task = f"Do what the n8n '{name}' node ({st}) did."
    if detail and detail != "{}":
        task += f"\n\nIts original configuration was:\n{detail}"
    return task


# ---------------------------------------------------------------------------
# Condition rendering (IF / Switch / Filter)
# ---------------------------------------------------------------------------

def _render_condition_clause(cond: dict) -> str:
    """One v2 filter-style condition -> readable text."""
    left = _param_str(cond.get("leftValue"))
    right = _param_str(cond.get("rightValue"))
    operator = cond.get("operator") or {}
    op = operator.get("operation") or operator.get("type") or "equals"
    return f"{left} {op} {right}".strip()


def describe_conditions(params: dict) -> str:
    """Best-effort English for an IF/Filter node's conditions, across the v1
    (typed buckets) and v2 (filter component) parameter shapes."""
    conditions = params.get("conditions")
    if isinstance(conditions, dict) and isinstance(conditions.get("conditions"), list):
        combinator = (conditions.get("combinator") or "and").upper()
        clauses = [_render_condition_clause(c) for c in conditions["conditions"] if isinstance(c, dict)]
        return f" {combinator} ".join(c for c in clauses if c)
    if isinstance(conditions, dict):
        clauses = []
        for bucket, entries in conditions.items():
            if bucket == "options" or not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                clauses.append(
                    f"{_param_str(entry.get('value1'))} {entry.get('operation', 'equals')} {_param_str(entry.get('value2'))}".strip()
                )
        if clauses:
            return " AND ".join(clauses)
    return ""


def switch_branch_labels(params: dict) -> list[str]:
    """Branch labels for a Switch node, in output-index order. Empty when the
    rules can't be read — the caller then names the outputs positionally."""
    rules = params.get("rules")
    # v3 keeps rules under `rules.values`; v1 under `rules.rules`.
    values = None
    if isinstance(rules, dict):
        values = rules.get("values") or rules.get("rules")
    elif isinstance(rules, list):
        values = rules

    if not (isinstance(values, list) and values):
        return []

    labels = []
    for i, rule in enumerate(values):
        if not isinstance(rule, dict):
            labels.append(f"output_{i}")
            continue
        label = rule.get("outputKey") or rule.get("renameOutput") or rule.get("output")
        labels.append(slugify(str(label)) if label not in (None, "") else f"output_{i}")
    # `fallbackOutput` only adds an output when it is literally "extra"; any
    # other value routes unmatched items to one of the outputs above.
    if (params.get("options") or {}).get("fallbackOutput") == "extra":
        labels.append("fallback")
    return labels


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

def extract_cron(node: dict) -> Optional[str]:
    """A cron expression for a schedule-style trigger, when one is expressible.
    Returns None when the trigger's timing has no cron equivalent here."""
    params = node.get("parameters") or {}

    rule = params.get("rule")
    if isinstance(rule, dict):
        for interval in rule.get("interval") or []:
            if not isinstance(interval, dict):
                continue
            if interval.get("field") == "cronExpression" and interval.get("expression"):
                return str(interval["expression"])
            field_name = interval.get("field")
            minute = interval.get("triggerAtMinute", 0)
            hour = interval.get("triggerAtHour", 0)
            if field_name == "days":
                return f"{minute} {hour} * * *"
            if field_name == "hours":
                return f"{minute} * * * *"
            if field_name == "weeks":
                day = interval.get("triggerAtDay", 1)
                return f"{minute} {hour} * * {day}"

    trigger_times = params.get("triggerTimes")
    if isinstance(trigger_times, dict):
        for item in trigger_times.get("item") or []:
            if not isinstance(item, dict):
                continue
            mode = item.get("mode")
            minute = item.get("minute", 0)
            hour = item.get("hour", 0)
            if mode == "everyMinute":
                return "* * * * *"
            if mode == "everyHour":
                return f"{minute} * * * *"
            if mode == "everyDay":
                return f"{minute} {hour} * * *"
            if mode == "everyWeek":
                return f"{minute} {hour} * * {item.get('weekday', 1)}"
            if mode == "custom" and item.get("cronExpression"):
                return str(item["cronExpression"])

    if params.get("cronExpression"):
        return str(params["cronExpression"])
    return None


# ---------------------------------------------------------------------------
# The conversion
# ---------------------------------------------------------------------------

def convert_n8n_workflow(
    raw: Any,
    name_override: Optional[str] = None,
    default_agent_id: Optional[str] = None,
) -> N8nImportResult:
    """Convert an n8n workflow export (or clipboard paste) into DAG steps.

    Raises ValueError on input that isn't an n8n workflow at all; every other
    problem becomes a warning on the result so a partly-translatable workflow
    still imports.
    """
    if not isinstance(raw, dict):
        raise ValueError("Expected an n8n workflow object at the top level")
    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, list):
        raise ValueError("Not an n8n workflow export: no 'nodes' array")
    if not nodes_raw:
        raise ValueError("This n8n workflow has no nodes")
    if len(nodes_raw) > MAX_NODES:
        raise ValueError(f"Workflow has {len(nodes_raw)} nodes; the import limit is {MAX_NODES}")

    warnings: list[ImportWarning] = []
    connections = raw.get("connections") if isinstance(raw.get("connections"), dict) else {}

    nodes: list[dict] = [n for n in nodes_raw if isinstance(n, dict) and n.get("name")]
    if len(nodes) != len(nodes_raw):
        warnings.append(ImportWarning("warning", "malformed_node",
                                      f"Skipped {len(nodes_raw) - len(nodes)} node(s) with no name."))

    by_name: dict[str, dict] = {n["name"]: n for n in nodes}

    # --- sticky notes become description text, never graph nodes -------------
    sticky_texts: list[str] = []
    for n in list(nodes):
        if short_type(n.get("type", "")) == "stickyNote":
            content = ((n.get("parameters") or {}).get("content") or "").strip()
            if content:
                sticky_texts.append(content)
            nodes.remove(n)
            by_name.pop(n["name"], None)

    # --- edges ---------------------------------------------------------------
    # main edges are the control flow; ai_* edges attach a sub-node (a chat
    # model, a tool, a memory) to its parent agent and are not graph edges.
    main_edges: list[tuple[str, str, int]] = []   # (source name, target name, output index)
    attachments: dict[str, list[str]] = {}        # parent node name -> sub-node names
    attachment_names: set[str] = set()

    for src_name, groups in connections.items():
        if not isinstance(groups, dict):
            continue
        for conn_type, outputs in groups.items():
            if not isinstance(outputs, list):
                continue
            for out_idx, conns in enumerate(outputs):
                for conn in conns or []:
                    if not isinstance(conn, dict) or not conn.get("node"):
                        continue
                    target = conn["node"]
                    if conn_type == "main":
                        if src_name in by_name and target in by_name:
                            main_edges.append((src_name, target, out_idx))
                    else:
                        attachments.setdefault(target, []).append(src_name)
                        attachment_names.add(src_name)

    for parent, subs in attachments.items():
        warnings.append(ImportWarning(
            "info", "ai_subnode_folded",
            f"Attached sub-node(s) {', '.join(sorted(set(subs)))} were folded into this step's "
            "config — pick the model and tools on the assigned agent instead.",
            node=parent,
        ))

    # --- drop nodes that are not part of the executable graph -----------------
    # disabled nodes, folded sub-nodes, and pass-throughs (NoOp) are all removed
    # by joining each of their predecessors straight to each of their successors,
    # so the surrounding flow keeps its shape.
    main_sources = {s for (s, _t, _i) in main_edges}

    def _removal_reason(n: dict) -> Optional[str]:
        if n.get("disabled"):
            return "disabled"
        # Only a node that feeds *nothing* through main is purely an attachment;
        # one with a main output does real work and has to stay in the graph.
        if n["name"] in attachment_names and n["name"] not in main_sources:
            return "attachment"
        if short_type(n.get("type", "")) in PASSTHROUGH_TYPES:
            return "passthrough"
        return None

    removed = {n["name"]: _removal_reason(n) for n in nodes if _removal_reason(n)}
    for name, reason in removed.items():
        if reason == "disabled":
            warnings.append(ImportWarning("info", "disabled_node_skipped",
                                          "Disabled in n8n — skipped, and its neighbours were reconnected.", node=name))
        elif reason == "passthrough":
            warnings.append(ImportWarning("info", "passthrough_removed",
                                          "A NoOp node has no equivalent here — removed, and its neighbours were reconnected.", node=name))

    edges = list(main_edges)
    for name in removed:
        incoming = [(s, i) for (s, t, i) in edges if t == name]
        outgoing = [t for (s, t, _i) in edges if s == name]
        edges = [(s, t, i) for (s, t, i) in edges if s != name and t != name]
        for (pred, pred_idx) in incoming:
            for succ in outgoing:
                if pred != succ and (pred, succ, pred_idx) not in edges:
                    edges.append((pred, succ, pred_idx))

    live_nodes = [n for n in nodes if n["name"] not in removed]
    if not live_nodes:
        raise ValueError("Nothing left to import: every node was disabled, a sticky note, or a sub-node")

    # --- classify ------------------------------------------------------------
    taken_ids: set[str] = set()
    name_to_id: dict[str, str] = {}
    node_type_by_name: dict[str, str] = {}
    triggers: list[dict] = []

    for n in live_nodes:
        st = short_type(n.get("type", ""))
        if is_trigger(n.get("type", "")):
            triggers.append(n)
            node_type_by_name[n["name"]] = "trigger"
            continue
        node_type_by_name[n["name"]] = CONTROL_FLOW_MAP.get(st, "agent")
        name_to_id[n["name"]] = _unique_id(slugify(n["name"]), taken_ids)

    start_id = _unique_id("start", taken_ids)
    end_id = _unique_id("end", taken_ids)

    # Triggers are entry points, not work: they collapse into the single start
    # node, and whatever they fed becomes a root of the DAG.
    schedules: list[dict] = []
    for trig in triggers:
        name_to_id[trig["name"]] = start_id
        cron = extract_cron(trig)
        if cron:
            schedules.append({"cron_expr": cron, "source_node": trig["name"]})
            warnings.append(ImportWarning(
                "info", "schedule_not_created",
                f"This trigger ran on '{cron}'. An import never creates a schedule — "
                "add one from the workflow's schedule dialog if you want it to keep running on a timer.",
                node=trig["name"],
            ))
    if len(triggers) > 1:
        warnings.append(ImportWarning(
            "info", "multiple_triggers",
            f"{len(triggers)} triggers ({', '.join(t['name'] for t in triggers)}) collapsed into one Start node.",
        ))
    if not triggers:
        warnings.append(ImportWarning("info", "start_synthesized",
                                      "No trigger node found — a Start node was added ahead of the entry nodes."))

    live_names = {n["name"] for n in live_nodes}
    work_names = [n["name"] for n in live_nodes if node_type_by_name[n["name"]] != "trigger"]
    if not work_names:
        raise ValueError("This workflow contains only trigger nodes — nothing to run")

    # --- dependencies --------------------------------------------------------
    depends_on: dict[str, list[str]] = {n: [] for n in work_names}
    input_branch: dict[str, str] = {}
    successors: dict[str, set[str]] = {n: set() for n in work_names}

    # Branch labels are decided once, per condition node, before any edge is
    # read: the label an outgoing edge carries must be one the condition step
    # actually offers, or the executor skips that dependent on every run (it
    # compares the chosen branch against `input_branch` verbatim). So the label
    # list is padded out to the highest output index the graph really uses.
    observed_outputs: dict[str, set[int]] = {}
    for (src_name, dst_name, out_idx) in edges:
        if node_type_by_name.get(src_name) == "condition":
            observed_outputs.setdefault(src_name, set()).add(out_idx)

    condition_branches: dict[str, list[str]] = {}
    for cond_name, ntype in node_type_by_name.items():
        if ntype != "condition":
            continue
        cond_st = short_type(by_name[cond_name].get("type", ""))
        if cond_st == "switch":
            labels = switch_branch_labels(by_name[cond_name].get("parameters") or {})
        elif cond_st == "filter":
            labels = ["pass", "drop"]
        else:
            labels = ["true", "false"]
        needed = max(observed_outputs.get(cond_name) or {0}) + 1
        while len(labels) < needed:
            labels.append(f"output_{len(labels)}")
        condition_branches[cond_name] = labels

    def _branch_label(src_name: str, out_idx: int) -> Optional[str]:
        labels = condition_branches.get(src_name)
        if not labels:
            return None
        return labels[out_idx] if out_idx < len(labels) else labels[-1]

    # target name -> {condition name: [labels it was reached by]}
    branch_sources: dict[str, dict[str, list[str]]] = {}

    for (src_name, dst_name, out_idx) in edges:
        if src_name not in live_names or dst_name not in live_names:
            continue
        if node_type_by_name.get(dst_name) == "trigger":
            continue
        if node_type_by_name.get(src_name) == "trigger":
            if start_id not in depends_on[dst_name]:
                depends_on[dst_name].append(start_id)
            continue
        src_id = name_to_id[src_name]
        if src_id not in depends_on[dst_name]:
            depends_on[dst_name].append(src_id)
        successors[src_name].add(dst_name)
        label = _branch_label(src_name, out_idx)
        if label:
            labels_from_src = branch_sources.setdefault(dst_name, {}).setdefault(src_name, [])
            if label not in labels_from_src:
                labels_from_src.append(label)

    for dst_name, by_source in branch_sources.items():
        # Wired to several outputs of the *same* condition — n8n runs it whichever
        # way that condition goes, so it must carry no branch restriction at all.
        # Pinning it to one label would make the executor skip it on the others.
        unconditional = [src for src, labels in by_source.items() if len(labels) > 1]
        if unconditional:
            warnings.append(ImportWarning(
                "info", "branch_unconditional",
                f"Reached from more than one output of '{unconditional[0]}', so it runs whichever branch is "
                "chosen — no branch condition was set on it.",
                node=dst_name,
            ))
            continue
        chosen_labels = [(src, labels[0]) for src, labels in by_source.items()]
        input_branch[dst_name] = chosen_labels[0][1]
        if len(chosen_labels) > 1:
            warnings.append(ImportWarning(
                "warning", "multiple_branch_inputs",
                f"Fed by branches of {len(chosen_labels)} different conditions; a step here can carry only one, "
                f"so '{chosen_labels[0][1]}' (from '{chosen_labels[0][0]}') was kept.",
                node=dst_name,
            ))

    # --- break loops ---------------------------------------------------------
    # n8n loops (a splitInBatches body wired back to its head) are legal there
    # and rejected here: workflows_router validates the graph is acyclic. Drop
    # the back-edges rather than failing the whole import.
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {n: WHITE for n in work_names}
    removed_back_edges: list[tuple[str, str]] = []

    def _visit(node_name: str):
        colour[node_name] = GREY
        for succ in sorted(successors[node_name]):
            if colour.get(succ) == GREY:
                removed_back_edges.append((node_name, succ))
                continue
            if colour.get(succ) == WHITE:
                _visit(succ)
        colour[node_name] = BLACK

    for n in work_names:
        if colour[n] == WHITE:
            _visit(n)

    for (src_name, dst_name) in removed_back_edges:
        successors[src_name].discard(dst_name)
        src_id = name_to_id[src_name]
        if src_id in depends_on[dst_name]:
            depends_on[dst_name].remove(src_id)
        warnings.append(ImportWarning(
            "warning", "loop_broken",
            f"The loop back to '{dst_name}' was removed — this app runs a DAG, not a cycle. "
            "Fold the per-item work into a Map step's task instead.",
            node=src_name,
        ))

    # roots (nothing upstream) hang off the Start node
    for n in work_names:
        if not depends_on[n]:
            depends_on[n] = [start_id]

    # --- topological order ---------------------------------------------------
    id_to_name = {nid: name for name, nid in name_to_id.items() if node_type_by_name.get(name) != "trigger"}
    rank: dict[str, int] = {}
    remaining = set(work_names)
    current_rank = 0
    while remaining:
        ready = [
            n for n in remaining
            if all(dep == start_id or id_to_name.get(dep) in rank for dep in depends_on[n])
        ]
        if not ready:  # defensive: cycles are already broken, so this should not happen
            ready = sorted(remaining)
        for n in sorted(ready):
            rank[n] = current_rank
        remaining -= set(ready)
        current_rank += 1

    ordered_names = sorted(work_names, key=lambda n: (rank[n], n))

    # --- positions -----------------------------------------------------------
    # n8n lays out left-to-right; this canvas wires top handle -> bottom handle,
    # so the axes are swapped to keep the author's grouping readable here.
    raw_positions = {}
    for n in live_nodes:
        pos = n.get("position")
        if isinstance(pos, list) and len(pos) >= 2 and all(isinstance(v, (int, float)) for v in pos[:2]):
            raw_positions[n["name"]] = (float(pos[1]), float(pos[0]))   # (x', y') = (y, x)
    if raw_positions:
        min_x = min(p[0] for p in raw_positions.values())
        min_y = min(p[1] for p in raw_positions.values())
    else:
        min_x = min_y = 0.0

    def _position_for(node_name: str, fallback_row: int) -> dict:
        if node_name in raw_positions:
            x, y = raw_positions[node_name]
            return {"x": round(x - min_x + 60, 1), "y": round(y - min_y + 160, 1)}
        return {"x": 160, "y": 160 + fallback_row * 260}

    # --- build the steps -----------------------------------------------------
    steps: list[dict] = []
    needs_agent: list[str] = []

    # What `$json` means for a step's successors. An n8n IF/Switch passes its
    # items through untouched, but a condition step here outputs the *branch
    # label* — so `$json` downstream of one refers to whatever fed the
    # condition, not to the condition itself. Start counts as a data source:
    # its output is the workflow input, the analogue of the trigger payload.
    resolve_for: dict[str, Optional[str]] = {start_id: start_id}

    start_step = {
        "id": start_id,
        "node_type": "start",
        "agent_id": None,
        "task": "",
        "order": 1,
        "depends_on": [],
        "input_branch": None,
        "position": {"x": 160, "y": 40},
        "config": {},
    }
    if len(triggers) == 1:
        trig = triggers[0]
        start_step["config"] = {"n8n": {"type": trig.get("type"), "name": trig.get("name"),
                                        "parameters": trig.get("parameters") or {}}}
    steps.append(start_step)

    for i, node_name in enumerate(ordered_names):
        node = by_name[node_name]
        node_id = name_to_id[node_name]
        node_type = node_type_by_name[node_name]
        st = short_type(node.get("type", ""))
        params = node.get("parameters") or {}
        deps = depends_on[node_name]
        # ordered_names is topological, so a single dependency's own resolution
        # is already known here.
        sole_pred = resolve_for.get(deps[0]) if len(deps) == 1 else None

        config: dict[str, Any] = {
            "n8n": {"type": node.get("type"), "name": node_name, "parameters": params}
        }
        if attachments.get(node_name):
            config["n8n"]["attachments"] = [
                {"name": s, "type": (by_name.get(s) or {}).get("type")} for s in attachments[node_name]
            ]
        if node.get("credentials"):
            config["n8n"]["credentials"] = sorted(node["credentials"].keys()) if isinstance(node["credentials"], dict) else None
            warnings.append(ImportWarning(
                "warning", "credentials_required",
                "The original node used n8n credentials, which are not carried over. Give the assigned agent a "
                "tool or MCP server with its own credentials.",
                node=node_name,
            ))

        agent_id: Optional[str] = None
        task = ""

        if node_type == "condition":
            branches = condition_branches[node_name]   # the same labels the edges carry
            described = describe_conditions(params)
            task = (
                f"Decide which branch the input belongs to. The original n8n {st} node routed on: "
                f"{described}" if described else
                f"Decide which branch the input belongs to, following what the n8n '{node_name}' node did."
            )
            config["branches"] = branches
            config["condition_prompt"] = task
            if st == "filter":
                warnings.append(ImportWarning(
                    "info", "filter_as_condition",
                    "A Filter node became a two-branch Condition ('pass' / 'drop'); only the 'pass' branch continues.",
                    node=node_name,
                ))
        elif node_type == "map":
            agent_id = default_agent_id
            if not default_agent_id:
                needs_agent.append(node_id)   # a Map step without an agent fails at run time
            batch_task = "Process this item and return the result:\n\n{{ item }}"
            if sole_pred:
                config["input_source"] = f"{sole_pred}.output"
            else:
                warnings.append(ImportWarning(
                    "warning", "map_input_source_unset",
                    "A Map step needs one upstream step producing a JSON list; set its input source by hand.",
                    node=node_name,
                ))
                config["input_source"] = ""
            config["agent_id"] = default_agent_id or ""
            config["task"] = batch_task
            config["concurrency_limit"] = 5
            config["reduce"] = "list"
            task = batch_task
            warnings.append(ImportWarning(
                "info", "loop_to_map",
                "A batching/loop node became a Map step: it runs its agent once per item of an upstream JSON list, "
                "instead of cycling the graph.",
                node=node_name,
            ))
        elif node_type == "approval":
            resume = params.get("resume")
            task = f"The n8n '{node_name}' node paused here. Approve to continue."
            config["prompt"] = task
            config["timeout_seconds"] = 600
            config["on_timeout"] = "fail"
            warnings.append(ImportWarning(
                "warning", "wait_as_approval",
                f"A Wait node (resume: {resume or 'timer'}) became a human Approval step with a 10-minute timeout — "
                "there is no timed-sleep node here.",
                node=node_name,
            ))
        else:  # agent
            task = build_task(node)
            agent_id = default_agent_id
            if not default_agent_id:
                needs_agent.append(node_id)
            if st in LANGCHAIN_AGENT_TYPES:
                pass  # a genuine LLM step — nothing lost beyond the model choice
            else:
                warnings.append(ImportWarning(
                    "info", "integration_as_agent",
                    f"The '{st}' integration node became an agent step; the assigned agent needs a tool that can "
                    "actually perform it. Its original parameters are kept under config.n8n.",
                    node=node_name,
                ))

        translated, untranslated = translate_expressions(task, name_to_id, sole_pred)
        if untranslated:
            warnings.append(ImportWarning(
                "warning", "expression_not_translated",
                "These n8n expressions have no equivalent here and were left as literal text for the agent to read: "
                + "; ".join(sorted(set(untranslated))[:5]),
                node=node_name,
            ))
        task = translated
        if node_type == "condition":
            config["condition_prompt"] = task
        elif node_type == "map":
            config["task"] = task

        resolve_for[node_id] = sole_pred if node_type == "condition" else node_id

        steps.append({
            "id": node_id,
            "node_type": node_type,
            "agent_id": agent_id,
            "task": task,
            "order": i + 2,   # 1 is the start node
            "depends_on": deps,
            "input_branch": input_branch.get(node_name),
            "position": _position_for(node_name, i),
            "config": config,
        })

    # --- end node ------------------------------------------------------------
    terminal_ids = [name_to_id[n] for n in ordered_names if not successors[n]]
    lowest = max((s["position"]["y"] for s in steps), default=40)
    steps.append({
        "id": end_id,
        "node_type": "end",
        "agent_id": None,
        "task": "",
        "order": len(steps) + 1,
        "depends_on": terminal_ids,
        "input_branch": None,
        "position": {"x": 160, "y": round(lowest + 260, 1)},   # just below the deepest step
        "config": {},
    })

    if not any(s["node_type"] in ("agent", "map") for s in steps):
        warnings.append(ImportWarning(
            "warning", "no_agent_steps",
            "Nothing in this workflow became an agent step, so there is nothing for the workflow to run.",
        ))

    description_parts = [p for p in [raw.get("description")] if p]
    if sticky_texts:
        description_parts.append("Notes from n8n:\n" + "\n\n".join(sticky_texts))
    description = "\n\n".join(description_parts) if description_parts else None

    return N8nImportResult(
        name=name_override or raw.get("name") or "Imported n8n workflow",
        description=description,
        steps=steps,
        warnings=warnings,
        schedules=schedules,
        needs_agent=needs_agent,
    )
