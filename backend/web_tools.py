"""Expanded web/API tools — opt-in category "web_extended". scrape_structured
and read_feed go beyond fetch_url's flat text-stripping; calculate and
convert_units are pure computation, no network; get_exchange_rate uses
Frankfurter (https://api.frankfurter.dev), a keyless, free, ECB-sourced
rate API, so it needs no Secrets Vault wiring.

calculate deliberately does NOT use Python eval() — it walks a restricted
AST, allowlisting only numeric literals, arithmetic operators, and a small
math function table. Any other node (names, attributes, calls to anything
not on the allowlist, comprehensions, lambdas, subscripts) is rejected."""

import ast
import json
import math

import httpx

WEB_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "scrape_structured",
            "description": "Fetch a URL and return its structure (title, headings, paragraphs, links) rather than flat stripped text. Use when you need to understand a page's layout, not just read it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 10000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_feed",
            "description": "Fetch and parse an RSS or Atom feed, returning recent items with title, link, published date, and summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_items": {"type": "integer", "default": 10},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a mathematical expression safely (arithmetic, sqrt, sin, cos, tan, log, log10, abs, round, pow). Use for any calculation you need to be exact rather than estimated.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "convert_units",
            "description": "Convert a value between units of length, mass, temperature, volume, or area.",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "number"},
                    "from_unit": {"type": "string"},
                    "to_unit": {"type": "string"},
                },
                "required": ["value", "from_unit", "to_unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_exchange_rate",
            "description": "Get a current currency exchange rate and convert an amount, using ECB reference rates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_currency": {"type": "string", "description": "3-letter currency code, e.g. USD"},
                    "to_currency": {"type": "string", "description": "3-letter currency code, e.g. EUR"},
                    "amount": {"type": "number", "default": 1},
                },
                "required": ["from_currency", "to_currency"],
            },
        },
    },
]

WEB_TOOL_NAMES = {s["function"]["name"] for s in WEB_TOOL_SCHEMAS}


def is_web_tool(tool_name: str) -> bool:
    return tool_name in WEB_TOOL_NAMES


# ---------------------------------------------------------------------------
# scrape_structured
# ---------------------------------------------------------------------------

async def _scrape_structured(url: str, max_chars: int) -> str:
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (compatible; ObsidianAI/1.0)"}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch URL: {e}"})

    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    headings = [{"level": h.name, "text": h.get_text(strip=True)} for h in soup.find_all(["h1", "h2", "h3", "h4"]) if h.get_text(strip=True)]
    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
    links = [{"text": a.get_text(strip=True), "href": a.get("href")} for a in soup.find_all("a", href=True) if a.get_text(strip=True)][:50]

    body_text = "\n\n".join(paragraphs)
    truncated = len(body_text) > max_chars
    return json.dumps({
        "title": title,
        "headings": headings[:30],
        "paragraphs": paragraphs if not truncated else [body_text[:max_chars]],
        "links": links,
        "truncated": truncated,
    })


# ---------------------------------------------------------------------------
# read_feed
# ---------------------------------------------------------------------------

async def _read_feed(url: str, max_items: int) -> str:
    import feedparser

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch feed: {e}"})

    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        return json.dumps({"error": "Could not parse feed"})

    items = []
    for entry in parsed.entries[:max_items]:
        items.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", entry.get("updated", "")),
            "summary": entry.get("summary", "")[:500],
        })
    return json.dumps({"feed_title": parsed.feed.get("title", ""), "items": items})


# ---------------------------------------------------------------------------
# calculate — safe AST-walked expression evaluator, no eval()
# ---------------------------------------------------------------------------

_ALLOWED_FUNCS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log, "log10": math.log10, "abs": abs, "round": round, "pow": pow,
}
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Only numeric literals are allowed")
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Add): return left + right
        if isinstance(node.op, ast.Sub): return left - right
        if isinstance(node.op, ast.Mult): return left * right
        if isinstance(node.op, ast.Div): return left / right
        if isinstance(node.op, ast.FloorDiv): return left // right
        if isinstance(node.op, ast.Mod): return left % right
        if isinstance(node.op, ast.Pow): return left ** right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARYOPS):
        operand = _safe_eval(node.operand)
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise ValueError("Only allowlisted functions may be called")
        if node.keywords:
            raise ValueError("Keyword arguments are not allowed")
        args = [_safe_eval(a) for a in node.args]
        return _ALLOWED_FUNCS[node.func.id](*args)
    raise ValueError(f"Disallowed expression element: {type(node).__name__}")


def _calculate(expression: str) -> str:
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree)
    except Exception as e:
        return json.dumps({"error": f"Invalid or unsafe expression: {e}"})
    return json.dumps({"result": result})


# ---------------------------------------------------------------------------
# convert_units — static factor table, temperature handled specially
# ---------------------------------------------------------------------------

_LENGTH_TO_M = {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0, "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344}
_MASS_TO_KG = {"mg": 1e-6, "g": 0.001, "kg": 1.0, "oz": 0.0283495, "lb": 0.453592, "t": 1000.0}
_VOLUME_TO_L = {"ml": 0.001, "l": 1.0, "gal": 3.78541, "qt": 0.946353, "pt": 0.473176, "cup": 0.236588, "floz": 0.0295735}
_AREA_TO_M2 = {"mm2": 1e-6, "cm2": 1e-4, "m2": 1.0, "km2": 1e6, "ft2": 0.092903, "acre": 4046.86, "ha": 10000.0}

_TABLES = {"length": _LENGTH_TO_M, "mass": _MASS_TO_KG, "volume": _VOLUME_TO_L, "area": _AREA_TO_M2}


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float | None:
    f, t = from_unit.lower(), to_unit.lower()
    if f not in ("c", "f", "k") or t not in ("c", "f", "k"):
        return None
    celsius = value if f == "c" else (value - 32) * 5 / 9 if f == "f" else value - 273.15
    if t == "c": return celsius
    if t == "f": return celsius * 9 / 5 + 32
    return celsius + 273.15


def _convert_units(value: float, from_unit: str, to_unit: str) -> str:
    temp_result = _convert_temperature(value, from_unit, to_unit)
    if temp_result is not None:
        return json.dumps({"result": temp_result, "category": "temperature"})

    f, t = from_unit.lower(), to_unit.lower()
    for category, table in _TABLES.items():
        if f in table and t in table:
            base = value * table[f]
            return json.dumps({"result": base / table[t], "category": category})
    return json.dumps({"error": f"Unsupported or mismatched units: {from_unit} -> {to_unit}"})


# ---------------------------------------------------------------------------
# get_exchange_rate
# ---------------------------------------------------------------------------

async def _get_exchange_rate(from_currency: str, to_currency: str, amount: float) -> str:
    from_currency, to_currency = from_currency.upper(), to_currency.upper()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.frankfurter.dev/v1/latest",
                params={"base": from_currency, "symbols": to_currency},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch exchange rate: {e}"})

    rate = (data.get("rates") or {}).get(to_currency)
    if rate is None:
        return json.dumps({"error": f"No rate found for {from_currency} -> {to_currency}"})
    return json.dumps({
        "from": from_currency, "to": to_currency, "rate": rate,
        "amount": amount, "converted": amount * rate, "date": data.get("date"),
    })


async def execute_web_tool(tool_name: str, arguments_str: str) -> str:
    try:
        args = json.loads(arguments_str) if arguments_str else {}
    except json.JSONDecodeError:
        args = {}

    if tool_name == "scrape_structured":
        url = args.get("url", "").strip()
        if not url:
            return json.dumps({"error": "url is required"})
        return await _scrape_structured(url, int(args.get("max_chars", 10000)))

    if tool_name == "read_feed":
        url = args.get("url", "").strip()
        if not url:
            return json.dumps({"error": "url is required"})
        return await _read_feed(url, int(args.get("max_items", 10)))

    if tool_name == "calculate":
        expression = args.get("expression", "")
        if not expression:
            return json.dumps({"error": "expression is required"})
        return _calculate(expression)

    if tool_name == "convert_units":
        try:
            value = float(args.get("value"))
        except (TypeError, ValueError):
            return json.dumps({"error": "value must be a number"})
        return _convert_units(value, args.get("from_unit", ""), args.get("to_unit", ""))

    if tool_name == "get_exchange_rate":
        from_c, to_c = args.get("from_currency", ""), args.get("to_currency", "")
        if not from_c or not to_c:
            return json.dumps({"error": "from_currency and to_currency are required"})
        return await _get_exchange_rate(from_c, to_c, float(args.get("amount", 1)))

    return json.dumps({"error": f"Unknown web tool: {tool_name}"})
