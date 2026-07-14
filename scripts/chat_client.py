"""Interactive terminal agent: Azure OpenAI + seleric-mcp tools over stdio.

Run from Base_Agent:

    uv sync
    uv run python scripts/chat_client.py

Requires AZURE_OPENAI_API_KEY in .env. Endpoint / deployment / api_version
and chat tunables come from config.yaml (env overrides still work).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AzureOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from seleric_mcp.config import load_azure_settings, load_chat_settings  # noqa: E402
from seleric_mcp.gateway.prompts import NO_HALLUCINATION_GUARD  # noqa: E402

MAX_TOOL_ROUNDS = load_chat_settings().max_tool_rounds

# Agent policy lives in an editable file next to this script, not in code.
_POLICY_PATH = Path(__file__).with_name("agent_policy.md")


def _load_agent_policy() -> str:
    if _POLICY_PATH.exists():
        return _POLICY_PATH.read_text(encoding="utf-8")
    print(f"(note: {_POLICY_PATH.name} not found — running without agent policy)")
    return ""


class Scratchpad:
    """Durable per-conversation memory, re-injected into context every round."""

    def __init__(self) -> None:
        self.notes: dict[str, str] = {}

    def write(self, key: str, value: str) -> str:
        key = (key or "").strip()
        if not key:
            return "ignored: empty key"
        if value is None or str(value).strip() == "":
            self.notes.pop(key, None)
            return f"deleted '{key}'"
        self.notes[key] = str(value).strip()
        return f"saved '{key}'"

    def render(self) -> str:
        if not self.notes:
            return "SCRATCHPAD (conversation memory): empty"
        lines = [f"- {k}: {v}" for k, v in self.notes.items()]
        return "SCRATCHPAD (conversation memory):\n" + "\n".join(lines)


SCRATCHPAD_TOOL = {
    "type": "function",
    "function": {
        "name": "scratchpad_write",
        "description": (
            "Save a durable fact/decision for this conversation (term "
            "resolutions, chosen default periods, active filters, useful "
            "query_ids). Overwrites the key. Empty value deletes the key. "
            "Handled locally — never sent to the MCP server."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short stable key, e.g. 'default_period' or 'term:net profit'"},
                "value": {"type": "string", "description": "The fact to remember; empty string deletes"},
            },
            "required": ["key", "value"],
        },
    },
}


def _load_azure() -> tuple[AzureOpenAI, str]:
    azure = load_azure_settings()
    missing = [
        name
        for name, val in [
            ("AZURE_OPENAI_API_KEY", azure.api_key),
            ("azure.endpoint (config.yaml or AZURE_OPENAI_ENDPOINT)", azure.endpoint),
            ("azure.deployment (config.yaml or AZURE_DEPLOYMENT)", azure.deployment),
        ]
        if not val
    ]
    if missing:
        raise SystemExit(f"Missing required Azure settings: {', '.join(missing)}")

    client = AzureOpenAI(
        api_key=azure.api_key,
        azure_endpoint=azure.endpoint,
        api_version=azure.api_version,
    )
    return client, azure.deployment


def _mcp_tools_to_openai(tools: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in tools:
        schema = t.inputSchema or {"type": "object", "properties": {}}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": (t.description or "")[:1024],
                    "parameters": schema,
                },
            }
        )
    return out


def _tool_result_text(result: Any) -> str:
    parts: list[str] = []
    if getattr(result, "isError", False):
        parts.append("ERROR from tool:")
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(str(block))
    if not parts and result.structuredContent is not None:
        parts.append(json.dumps(result.structuredContent, default=str))
    return "\n".join(parts) if parts else "{}"


async def _chat_loop(llm: AzureOpenAI, deployment: str, session: ClientSession) -> None:
    listed = await session.list_tools()
    openai_tools = _mcp_tools_to_openai(listed.tools) + [SCRATCHPAD_TOOL]
    print(f"Connected. {len(openai_tools)} tools from seleric-mcp. Model: {deployment}")
    print("Type a question (or 'exit' / 'quit' / 'scratchpad').\n")

    scratchpad = Scratchpad()
    # messages[1] is the scratchpad slot, refreshed before every LLM call
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": NO_HALLUCINATION_GUARD + "\n" + _load_agent_policy()},
        {"role": "system", "content": scratchpad.render()},
    ]

    while True:
        try:
            user = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return
        if not user:
            continue
        if user.lower() in {"exit", "quit", ":q"}:
            print("Bye.")
            return
        if user.lower() in {"scratchpad", ":s"}:
            print(f"\n{scratchpad.render()}\n")
            continue

        messages.append({"role": "user", "content": user})

        for _ in range(MAX_TOOL_ROUNDS):
            messages[1] = {"role": "system", "content": scratchpad.render()}
            try:
                resp = llm.chat.completions.create(
                    model=deployment,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                )
            except Exception as exc:
                print(f"LLM error: {exc}")
                messages.pop()  # drop failed user turn pairing if needed
                break

            choice = resp.choices[0].message
            tool_calls = choice.tool_calls or []

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": choice.content or "",
            }
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)

            if not tool_calls:
                text = (choice.content or "").strip() or "(empty response)"
                print(f"\nAgent> {text}\n")
                break

            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                print(f"  → tool {name}({json.dumps(args, default=str)[:200]})")
                if name == "scratchpad_write":
                    payload = scratchpad.write(args.get("key", ""), args.get("value", ""))
                else:
                    result = await session.call_tool(name, args)
                    payload = _tool_result_text(result)
                preview = payload if len(payload) < 400 else payload[:400] + "…"
                print(f"  ← {preview}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": payload,
                    }
                )
        else:
            print("Agent> (stopped: too many tool rounds)")


async def main() -> None:
    llm, deployment = _load_azure()

    # Use the current interpreter + module entrypoint (avoids locked .exe on Windows
    # when an HTTP seleric-mcp process is already running).
    command = sys.executable
    args = ["-m", "seleric_mcp", "--transport", "stdio"]

    params = StdioServerParameters(
        command=command,
        args=args,
        cwd=str(ROOT),
        # Pass full env so Cube secrets reach the child if needed;
        # the server also loads Base_Agent/.env itself via dotenv.
        env={**os.environ},
    )

    print("Starting seleric-mcp (stdio)…")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _chat_loop(llm, deployment, session)


if __name__ == "__main__":
    asyncio.run(main())
