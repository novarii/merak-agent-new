import json
from typing import Any
from pydantic import BaseModel, Field
from openai import OpenAI
from agents import RunContextWrapper, FunctionTool, Agent, ToolOutputText
from chatkit.agents import AgentContext

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
    
    # Filter by industries (if agent's industry is in the list)
    if industries and len(industries) > 0:
        filters.append({
            "type": "in",
            "key": "industry",
            "value": industries
        })
    
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


async def search_agents(ctx: RunContextWrapper[Any], args: str) -> ToolOutputText:
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
        max_num_results=parsed.max_results,
        filters=attribute_filter,
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
