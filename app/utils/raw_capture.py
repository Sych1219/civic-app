"""Utilities for capturing LLM call inputs as RawMessageBlock dicts (frontend contract)."""

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

_MAX_RAW_CONTENT = 32 * 1024  # 32 KB


def truncate_content(text: str) -> tuple[str, bool]:
    if len(text) > _MAX_RAW_CONTENT:
        return text[:_MAX_RAW_CONTENT], True
    return text, False


def serialize_messages(msgs: list, history_count: int = 0) -> list[dict]:
    """Convert a list of LangChain messages to RawMessageBlock dicts.

    history_count: how many messages immediately after the system prompt
    are from prior conversation history (marked is_history=True).
    Layout assumed: [SystemMessage, *history_msgs, HumanMessage(current), ...]
    """
    blocks: list[dict] = []
    for i, msg in enumerate(msgs):
        is_history = history_count > 0 and 1 <= i <= history_count

        if isinstance(msg, SystemMessage):
            raw = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
            content, truncated = truncate_content(raw)
            b: dict = {"role": "system", "content": content}
            if truncated:
                b["truncated"] = True
            blocks.append(b)

        elif isinstance(msg, HumanMessage):
            raw = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
            content, truncated = truncate_content(raw)
            b = {"role": "user", "content": content}
            if is_history:
                b["is_history"] = True
            if truncated:
                b["truncated"] = True
            blocks.append(b)

        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                    content, truncated = truncate_content(args_str)
                    b = {
                        "role": "assistant",
                        "content": content,
                        "tool_name": tc["name"],
                        "tool_call_id": tc.get("id", ""),
                    }
                    if truncated:
                        b["truncated"] = True
                    blocks.append(b)
            else:
                raw = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                content, truncated = truncate_content(raw)
                b = {"role": "assistant", "content": content}
                if truncated:
                    b["truncated"] = True
                blocks.append(b)

        elif isinstance(msg, ToolMessage):
            raw = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
            content, truncated = truncate_content(raw)
            b = {
                "role": "tool",
                "content": content,
                "tool_call_id": msg.tool_call_id,
            }
            if getattr(msg, "name", None):
                b["tool_name"] = msg.name
            if truncated:
                b["truncated"] = True
            blocks.append(b)

    return blocks
