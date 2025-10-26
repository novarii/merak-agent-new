import json
import time

from typing import Any
from pydantic import BaseModel, Field
from openai import OpenAI
from agents import RunContextWrapper, FunctionTool, Agent, ToolOutputText
from chatkit.agents import AgentContext, ClientToolCall, ClientToolCall
from chatkit.types import ProgressUpdateEvent, ClientToolCallItem

from app.constants import MERAK_AGENT_INSTRUCTIONS
from app.core.settings import settings
client = OpenAI(api_key=settings.openai_api_key)

class FunctionArgs(BaseModel):
    query: str = Field(description="A short semantic search query that captures the user's need.")
    industries: list[str] | None = Field(description="A list of primary industries relevant to the search.")
    agent_types: list[str] | None = Field(description="A list of agent types to consider for the search.")
    max_rate: float | None = Field(description="The maximum hourly rate in USD for the search.")
    min_success_rate: float | None = Field(description="The minimum success rate as a percentage for the search.")
    availability: str | None = Field(description="The desired availability of the agents (e.g., full-time, part-time).")
    max_results: int = Field(default=5, description="The maximum number of results to return.")

def build_attribute_filter(
    industries: list[str] | None = None,
    agent_types: list[str] | None = None,
    max_rate: float | None = None,
    min_success_rate: float | None = None,
    availability: str | None = None,
) -> dict | None:
    """Build an attribute filter for vector store search."""
    
    filters = []
    
    # Industry filtering disabled temporarily during testing.
    
    # Filter by agent types (if agent's type is in the list)
    if agent_types and len(agent_types) > 0:
        filters.append({
            "type": "in",
            "key": "agent_type",
            "value": agent_types
        })
    
    # Filter by max rate (agent's rate <= max_rate)
    if max_rate is not None:
        filters.append({
            "type": "lte",
            "key": "base_rate",
            "value": max_rate
        })
    
    # Filter by min success rate (agent's success_rate >= min_success_rate)
    if min_success_rate is not None:
        filters.append({
            "type": "gte",
            "key": "success_rate",
            "value": min_success_rate
        })
    
    # Filter by availability
    if availability:
        filters.append({
            "type": "eq",
            "key": "availability",
            "value": availability
        })
    
    # If no filters, return None
    if not filters:
        return None
    
    # If only one filter, return it directly
    if len(filters) == 1:
        return filters[0]
    
    # If multiple filters, combine with AND
    return {
        "type": "and",
        "filters": filters
    }

async def stream_search_animation(ctx: RunContextWrapper[Any], active: bool) -> None:
    now = time.perf_counter()

    if active:
        ctx.context._search_animation_started_at = now
        print(f"[SEARCH] animation ON @ {now:.3f}s", flush=True)
        marker = "start"
    else:
        started = getattr(ctx.context, "_search_animation_started_at", None)
        elapsed = (now - started) if started is not None else None
        print(f"[SEARCH] animation OFF after {elapsed:.3f}s", flush=True)
        ctx.context._search_animation_started_at = None
        marker = "stop"

    await ctx.context.stream(
        ProgressUpdateEvent(text=f"search_animation:{marker}")
    )


def extract_agent_ids(search_results: Any) -> list[str]:
    agent_ids = []
    
    for result in search_results.data:
        if hasattr(result, "attributes") and result.attributes:
            agent_id = result.attributes.get("agent_id")
            if agent_id:
                agent_ids.append(agent_id)
    
    return agent_ids


async def search_agents(ctx: RunContextWrapper[Any], args: str) -> ToolOutputText:
    await stream_search_animation(ctx, active=True)

    parsed = FunctionArgs.model_validate_json(args)
    
    attribute_filter = build_attribute_filter(
        industries=parsed.industries,
        agent_types=parsed.agent_types,
        max_rate=parsed.max_rate,
        min_success_rate=parsed.min_success_rate,
        availability=parsed.availability,
    )

    results = client.vector_stores.search(
        vector_store_id=settings.vector_store_id,
        query=parsed.query,
        max_num_results=max(5, parsed.max_results),
        filters=attribute_filter,
        ranking_options={
        "score_threshold": 0.4,
        },
    )

    agent_ids = extract_agent_ids(results)

    await stream_search_animation(ctx, active=False)
    ctx.context.client_tool_call = ClientToolCall(
        name="display_agent_profiles",
        arguments={"agent_ids": agent_ids}
    )
    
    tool_payload = {
        "total_results": len(results.data),
        "agents": [
            {
                "file_id": result.file_id,
                "filename": result.filename,
                "score": result.score,
                "attributes": result.attributes if hasattr(result, 'attributes') else {},
                "content": [c.text for c in result.content if c.type == "text"]
            }
            for result in results.data
        ]
    }

    return ToolOutputText(text=json.dumps(tool_payload))


search_agents_tool = FunctionTool(
    name="search_agents",
    description="Search for agents that match the user's requirements based on various facets like industry, agent type, rate, success rate, and availability.",
    params_json_schema=FunctionArgs.model_json_schema(),
    on_invoke_tool=search_agents,
)

merak_agent = Agent[AgentContext](
    model="gpt-4.1-mini",
    name="Merak Agent",
    instructions=MERAK_AGENT_INSTRUCTIONS,
    tools=[search_agents_tool],
)
