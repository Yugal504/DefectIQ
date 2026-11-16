"""The Agentic AI chatbot orchestrator.

Two execution modes:
  * LLM mode (Azure OpenAI): the model plans and calls grounded tools via
    function-calling, then writes the final natural-language answer.
  * Offline mode: a deterministic router selects one grounded tool and the
    tool's own summary is returned.

Either way, all defect facts come from the consolidated dataset - the LLM is
never asked to recall defect data from its own knowledge (BRD 5.3.3).
"""
from __future__ import annotations

import json
from typing import Any

from ..config import get_settings
from ..models import ChatResponse
from ..store import DefectStore
from . import nl_fallback
from .tools import TOOL_SCHEMAS, DefectTools

SYSTEM_PROMPT = (
    "You are DefectIQ, NTT DATA's defect assistant. Answer questions about "
    "consolidated defects (the Smartsheet defect list enriched with GitHub data). "
    "Rules:\n"
    "- You MUST call a tool for EVERY question about defects before answering; never answer "
    "a defect question from memory. For 'by X' / 'breakdown' / 'distribution' questions use "
    "defect_distribution with the right group_by.\n"
    "- Base every fact ONLY on the tool results; never invent ids, counts, statuses or owners.\n"
    "- Use the EXACT 'count' / numbers returned by the tool verbatim. Never re-estimate or "
    "round; if the tool says 346, say 346.\n"
    "- Be SHORT and crisp: 1 sentence, plain language a human can read at a glance.\n"
    "- Give the key number/answer directly. Do NOT paste tables, long lists, raw rows, "
    "JSON, ids dumps, or disclaimers - the app renders any visuals separately.\n"
    "- If there is no data, say so in one sentence."
)

MAX_TOOL_ROUNDS = 4


class DefectAgent:
    def __init__(self, store: DefectStore) -> None:
        self.store = store
        self.tools = DefectTools(store)
        self.settings = get_settings()
        self._client = None
        if self.settings.azure_openai_enabled:
            self._init_client()

    def _init_client(self) -> None:
        try:
            from openai import AzureOpenAI

            self._client = AzureOpenAI(
                azure_endpoint=self.settings.azure_openai_endpoint,
                api_key=self.settings.azure_openai_api_key,
                api_version=self.settings.azure_openai_api_version,
            )
        except Exception:  # pragma: no cover - missing pkg or bad config
            self._client = None

    @property
    def llm_enabled(self) -> bool:
        return self._client is not None

    def _call_tool(self, name: str, args: dict[str, Any]) -> dict:
        fn = getattr(self.tools, name, None)
        if fn is None:
            return {"summary": f"Unknown tool '{name}'.", "count": 0, "rows": [], "extra": {}}
        try:
            return fn(**(args or {}))
        except TypeError:
            # Drop unexpected kwargs and retry.
            return fn()

    # ----------------------------------------------------------------- answer
    def answer(self, message: str, history: list[dict] | None = None) -> ChatResponse:
        refreshed = self.store.last_refreshed or self.store.reconciled_at
        if self.llm_enabled:
            try:
                return self._answer_llm(message, history or [], refreshed)
            except Exception:
                # Any LLM/runtime failure gracefully degrades to offline mode.
                pass
        return self._answer_offline(message, refreshed)

    # ------------------------------------------------------------- offline mode
    def _answer_offline(self, message: str, refreshed: str | None) -> ChatResponse:
        tool_name, kwargs = nl_fallback.route(message)
        result = self._call_tool(tool_name, kwargs)
        reply = result.get("summary", "")
        if not result.get("rows") and result.get("count", 0) == 0 and tool_name == "search_defects":
            reply = (
                f"{reply} I can answer questions about defect counts, statuses, "
                "developers, reconciliation gaps, and individual defects."
            )
        return ChatResponse(
            reply=reply,
            data={"tool": tool_name, "args": kwargs, "rows": result.get("rows", []),
                  "count": result.get("count", 0), "extra": result.get("extra", {})},
            used_llm=False,
            refreshed_at=refreshed,
        )

    # ----------------------------------------------------------------- llm mode
    def _answer_llm(self, message: str, history: list[dict], refreshed: str | None) -> ChatResponse:
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history[-6:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})

        last_tool_rows: list = []
        last_tool_meta: dict = {}
        last_tool_extra: dict = {}
        last_tool_count: int = 0
        for _ in range(MAX_TOOL_ROUNDS):
            resp = self._client.chat.completions.create(
                model=self.settings.azure_openai_deployment,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0,
            )
            choice = resp.choices[0].message
            if not choice.tool_calls:
                # If the model answered without ever grounding on a tool, fall back
                # to the deterministic engine so the reply always has real data+visual.
                if not last_tool_meta:
                    return self._answer_offline(message, refreshed)
                return ChatResponse(
                    reply=choice.content or "",
                    data={
                        "tool": last_tool_meta.get("tool"),
                        "args": last_tool_meta.get("args", {}),
                        "rows": last_tool_rows,
                        "count": last_tool_count,
                        "extra": last_tool_extra,
                    },
                    used_llm=True,
                    refreshed_at=refreshed,
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": choice.content,
                    "tool_calls": [tc.model_dump() for tc in choice.tool_calls],
                }
            )
            for tc in choice.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._call_tool(name, args)
                last_tool_rows = result.get("rows", []) or last_tool_rows
                last_tool_count = result.get("count", 0)
                last_tool_extra = result.get("extra", {}) or last_tool_extra
                last_tool_meta = {"tool": name, "args": args, "count": last_tool_count}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(
                            {
                                "summary": result.get("summary"),
                                "count": result.get("count"),
                                "rows": result.get("rows", [])[:40],
                                "extra": result.get("extra", {}),
                            },
                            default=str,
                        ),
                    }
                )
        # Exhausted rounds: summarize from the last tool result.
        return ChatResponse(
            reply="Here is the most relevant information I found.",
            data={
                "tool": last_tool_meta.get("tool"),
                "args": last_tool_meta.get("args", {}),
                "rows": last_tool_rows,
                "count": last_tool_count,
                "extra": last_tool_extra,
            },
            used_llm=True,
            refreshed_at=refreshed,
        )
