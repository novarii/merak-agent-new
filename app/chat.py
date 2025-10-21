"""ChatKit server integration for the backend."""

from __future__ import annotations

import inspect
from typing import Annotated, Any, AsyncIterator

from agents import Agent, Runner
from chatkit.agents import AgentContext, ThreadItemConverter, stream_agent_response
from chatkit.server import ChatKitServer
from chatkit.types import (
    Attachment,
    ClientToolCallItem,
    ThreadItem,
    ThreadMetadata,
    ThreadStreamEvent,
    UserMessageItem,
)
from openai.types.responses import ResponseInputContentParam
from pydantic import ConfigDict, Field

from .constants import MERAK_AGENT_INSTRUCTIONS, MODEL
from .memory_store import MemoryStore
from .merak_agent_tool import search_agents_tool


def _is_tool_completion_item(item: Any) -> bool:
    return isinstance(item, ClientToolCallItem)


class MerakAgentContext(AgentContext):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    store: Annotated[MemoryStore, Field(exclude=True)]
    request_context: dict[str, Any]


def _user_message_text(item: UserMessageItem) -> str:
    parts: list[str] = []
    for part in item.content:
        text = getattr(part, "text", None)
        if text:
            parts.append(text)
    return " ".join(parts).strip()


class MerakAgentServer(ChatKitServer):
    """ChatKit server wired up with the Merak search tool."""

    def __init__(self) -> None:
        self.store: MemoryStore = MemoryStore()
        super().__init__(self.store)
        self.assistant = Agent[MerakAgentContext](
            model=MODEL,
            name="Merak Agent",
            instructions=MERAK_AGENT_INSTRUCTIONS,
            tools=[search_agents_tool],
        )
        self._thread_item_converter = self._init_thread_item_converter()

    async def respond(
        self,
        thread: ThreadMetadata,
        input: UserMessageItem | None,
        context: Any,
    ) -> AsyncIterator[ThreadStreamEvent]:
        request_context = context if isinstance(context, dict) else {}
        agent_context = MerakAgentContext(
            thread=thread,
            store=self.store,
            request_context=request_context,
        )

        target_item: ThreadItem | None = input
        if target_item is None:
            target_item = await self._latest_thread_item(thread, request_context)

        if target_item is None or _is_tool_completion_item(target_item):
            return

        agent_input = await self._to_agent_input(thread, target_item)
        if agent_input is None:
            return

        result = Runner.run_streamed(
            self.assistant,
            agent_input,
            context=agent_context,
        )
        async for event in stream_agent_response(agent_context, result):
            yield event
        return

    async def to_message_content(self, _input: Attachment) -> ResponseInputContentParam:
        raise RuntimeError("File attachments are not supported in this demo.")

    def _init_thread_item_converter(self) -> Any | None:
        converter_cls = ThreadItemConverter
        if converter_cls is None or not callable(converter_cls):
            return None

        attempts: tuple[dict[str, Any], ...] = (
            {"to_message_content": self.to_message_content},
            {"message_content_converter": self.to_message_content},
            {},
        )

        for kwargs in attempts:
            try:
                return converter_cls(**kwargs)
            except TypeError:
                continue
        return None

    async def _latest_thread_item(
        self, thread: ThreadMetadata, context: dict[str, Any]
    ) -> ThreadItem | None:
        try:
            items = await self.store.load_thread_items(thread.id, None, 1, "desc", context)
        except Exception:  # pragma: no cover - defensive
            return None

        return items.data[0] if getattr(items, "data", None) else None

    async def _to_agent_input(
        self,
        thread: ThreadMetadata,
        item: ThreadItem,
    ) -> Any | None:
        if _is_tool_completion_item(item):
            return None

        converter = getattr(self, "_thread_item_converter", None)
        if converter is not None:
            for attr in (
                "to_input_item",
                "convert",
                "convert_item",
                "convert_thread_item",
            ):
                method = getattr(converter, attr, None)
                if method is None:
                    continue
                call_args: list[Any] = [item]
                call_kwargs: dict[str, Any] = {}
                try:
                    signature = inspect.signature(method)
                except (TypeError, ValueError):
                    signature = None

                if signature is not None:
                    params = [
                        parameter
                        for parameter in signature.parameters.values()
                        if parameter.kind
                        not in (
                            inspect.Parameter.VAR_POSITIONAL,
                            inspect.Parameter.VAR_KEYWORD,
                        )
                    ]
                    if len(params) >= 2:
                        next_param = params[1]
                        if next_param.kind in (
                            inspect.Parameter.POSITIONAL_ONLY,
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        ):
                            call_args.append(thread)
                        else:
                            call_kwargs[next_param.name] = thread

                result = method(*call_args, **call_kwargs)
                if inspect.isawaitable(result):
                    return await result
                return result

        if isinstance(item, UserMessageItem):
            return _user_message_text(item)

        return None

def create_chatkit_server() -> MerakAgentServer | None:
    """Return a configured ChatKit server instance if dependencies are available."""
    return MerakAgentServer()
