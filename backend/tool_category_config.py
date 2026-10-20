"""Opt-in tool category config, mirroring pii_redactor.py's PrivacyModeConfig
pattern. Lives in Agent.config_json under "tool_categories" — no new column,
no migration. Absent/malformed config means every category is off, so an
agent that existed before this shipped gets zero new tools until a user
explicitly enables a category.

Category tool schemas are only ever included in the LLM's tool list when
their category is enabled (see chat_router.py's _build_tools_for_llm) — the
dispatch functions below never re-check "is this category actually
enabled" at execution time, since the schema's absence from the model's
tool list is itself the enforcement point, same as sandbox tools never
re-check sandbox_enabled inside their own executor."""

from dataclasses import dataclass

ALL_CATEGORIES = ("data_files", "web_extended", "productivity")


@dataclass
class ToolCategoryConfig:
    data_files: bool = False
    web_extended: bool = False
    productivity: bool = False

    @classmethod
    def from_agent_config(cls, config: dict | None) -> "ToolCategoryConfig":
        if not isinstance(config, dict):
            return cls()
        raw = config.get("tool_categories")
        if not isinstance(raw, dict):
            return cls()
        return cls(**{k: bool(raw.get(k, False)) for k in ALL_CATEGORIES})

    def enabled_schema_lists(self) -> list[list[dict]]:
        out = []
        if self.data_files:
            from data_tools import DATA_TOOL_SCHEMAS
            out.append(DATA_TOOL_SCHEMAS)
        if self.web_extended:
            from web_tools import WEB_TOOL_SCHEMAS
            out.append(WEB_TOOL_SCHEMAS)
        if self.productivity:
            from productivity_tools import PRODUCTIVITY_TOOL_SCHEMAS
            out.append(PRODUCTIVITY_TOOL_SCHEMAS)
        return out


def is_any_category_tool(tool_name: str) -> bool:
    from data_tools import is_data_tool
    from web_tools import is_web_tool
    from productivity_tools import is_productivity_tool
    return is_data_tool(tool_name) or is_web_tool(tool_name) or is_productivity_tool(tool_name)


async def execute_category_tool(tool_name: str, arguments_str: str, *, agent, db, session_id, is_mongo: bool = False) -> str:
    from data_tools import is_data_tool, execute_data_tool
    from web_tools import is_web_tool, execute_web_tool
    from productivity_tools import is_productivity_tool, execute_productivity_tool

    if is_data_tool(tool_name):
        return await execute_data_tool(tool_name, arguments_str, session_id=session_id, db=db, is_mongo=is_mongo)
    if is_web_tool(tool_name):
        return await execute_web_tool(tool_name, arguments_str)
    if is_productivity_tool(tool_name):
        return await execute_productivity_tool(tool_name, arguments_str, agent=agent, db=db, is_mongo=is_mongo)
    return f'{{"error": "Unknown category tool: {tool_name}"}}'
