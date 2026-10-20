"""Cross-round tool-call repetition tracking for the streaming chat loop.

_chat_with_tools/_chat_with_tools_mongo (the non-streaming team-chat helpers)
already dedupe EXACT-duplicate calls WITHIN a single round via
_norm_tool_args, but nothing previously caught a model re-issuing the SAME
TOOL across multiple rounds with no real progress — e.g. calling
sandbox_write five rounds running, varying the file content slightly each
time specifically so an exact-argument-match dedup would never catch it,
instead of ever calling sandbox_read to check its own work. That left a
model free to loop until MAX_TOOL_ROUNDS or a user manually stopped it.

Deliberately keys on TOOL NAME ALONE, not name+arguments — a model stuck in
a loop reliably varies some argument each round (new file content, a
slightly reworded search query) specifically to look like forward progress,
so argument-based dedup is exactly the wrong signal here. The counter is
consecutive: calling a different tool in between resets it, so legitimate
repeated use of the same tool interleaved with other tools (e.g. write,
read, write again to fix something) isn't flagged — only an unbroken run of
the same tool name, repeated with no variety in what's being tried."""

REPEAT_WARNING_THRESHOLD = 3  # this many CONSECUTIVE calls to the same tool triggers a warning


class ToolLoopGuard:
    """One instance per streaming response (constructed fresh in each of the
    4 _stream_response* functions, not shared across requests)."""

    def __init__(self):
        self._last_tool_name: str | None = None
        self._consecutive_count = 0

    def record_and_check(self, tool_name: str, arguments=None) -> int:
        """Record this call and return the current consecutive-repeat count
        for this tool name (resets to 1 whenever a different tool is called).
        `arguments` is accepted but intentionally unused — see module
        docstring for why repetition is tracked by name alone."""
        if tool_name == self._last_tool_name:
            self._consecutive_count += 1
        else:
            self._last_tool_name = tool_name
            self._consecutive_count = 1
        return self._consecutive_count

    @staticmethod
    def warning_text(tool_name: str, repeat_count: int) -> str:
        return (
            f"\n\n[SYSTEM NOTE: you have now called '{tool_name}' "
            f"{repeat_count} times in a row in this response, without "
            f"calling any other tool in between. If you're trying to "
            f"verify something, call a DIFFERENT tool (e.g. a read/list/"
            f"status tool, not another write/repeat of the same action) "
            f"to check the actual result instead of repeating the same "
            f"call. If you already have what you need, stop calling tools "
            f"and answer the user directly now.]"
        )
