from agents import Agent, RunConfig, Runner
from agents.model_settings import ModelSettings
from chatkit.agents import AgentContext, stream_agent_response
from chatkit.server import ChatKitServer, StreamingResult
from .memory_store import MemoryStore

from app.constants import MERAK_AGENT_INSTRUCTIONS, MODEL

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
    """ChatKit server wired up with the search tool."""
    def __init__(self) -> None:
        self.store: MemoryStore = MemoryStore()
        super().__init__(self.store)
        tools = [save_fact, switch_theme, get_weather]
        self.assistant = Agent[MerakAgentContext](
            model=MODEL,
            name="ChatKit Guide",
            instructions=MERAK_AGENT_INSTRUCTIONS,
            tools=tools,  # type: ignore[arg-type]
        )
    
    async def respond(
        self,
        thread: ThreadMetadata,
        input: UserMessageItem | None,
        context: Any,
    ) -> AsyncIterator[ThreadStreamEvent]:
        context = AgentContext(
            thread=thread,
            store=self.store,
            request_context=context,
        )
        result = Runner.run_streamed(
            self.assistant_agent,
            await simple_to_agent_input(input) if input else [],
            context=context,
        )
        async for event in stream_agent_response(context, result):
            yield event

