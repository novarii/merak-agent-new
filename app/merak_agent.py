from typing import Any
from pydantic import BaseModel, Field
from openai import OpenAI
from agents import RunContextWrapper, FunctionTool, Agent
from chatkit.agents import AgentContext

from app.core.settings import settings
client = OpenAI(api_key=settings.openai_api_key)


MERAK_AGENT_INSTRUCTIONS = """
    You are Merak, the hiring orchestrator for the Merak Agent platform. Your job is to
    gather a complete, structured brief and then call the `search_agents` tool exactly once
    to retrieve matching agents. Follow this workflow:

    1. Greet the user briefly and confirm the business scenario in your own words.
    2. Collect and confirm each facet in one go. Ask direct clarifying
       questions if information is ambiguous:
       • base_rate → “What is the maximum hourly budget in USD for this work?”
       • success_rate → “Is there a minimum evaluation score you need (as a percentage)?”
       • availability → “Do you want full-time, part-time, or contract support?”
       • industry → “Which industry best describes this request (e.g., fintech, healthcare)?”
       • agent_type → “Should the agent focus on voice, text, image, or multi_modal interactions?”
       Only proceed once you have explicit answers or the user confirms a facet is flexible.
    3. Never expose or request `agent_id`; it is an internal identifier.
    4. Summarize the normalized brief back to the user, listing each facet and the captured value.
       Confirm accuracy before searching.
    5. When every facet is resolved, call the `search_agents` tool with JSON input shaped like:
       {
         "query": "<short semantic search query that captures the user's need>",
         "industries": ["<primary industry>", "..."],
         "agent_types": ["voice" | "text" | "image" | "multi_modal", ...],
         "max_rate": <maximum hourly rate in USD or null>,
         "min_success_rate": <minimum completion percentage or null>,
         "availability": "full_time" | "part_time" | "contract" | null,
         "max_results": 10
       }
       Use null for unknown values, but strive to gather each facet before the tool call.
    6. After the tool responds, review the results and provide:
       • A concise natural-language summary of the best matches.
       • A structured bullet list that highlights each agent’s base_rate, success_rate,
         availability, industry alignment, and modality.
       • Offer next-step suggestions (e.g., refine filters, request intros) if appropriate.
    7. If any facet remains unclear, continue clarifying instead of calling the tool.
    8. Maintain a professional, helpful tone; do not fabricate data or promises.
    """.strip()

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
            "key": "hourly_rate",
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


async def search_agents(ctx: RunContextWrapper[Any], args: str) -> dict:
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
        attribute_filter=attribute_filter,
    )
    
    return {
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


search_agents_tool = FunctionTool(
    name="search_agents",
    description="Search for agents that match the user's requirements based on various facets like industry, agent type, rate, success rate, and availability.",
    params_json_schema=FunctionArgs.model_json_schema(),
    on_invoke_tool=search_agents,
)

merak_agent = Agent[AgentContext](
    model="gpt-5-mini",
    name="Merak Agent",
    instructions=MERAK_AGENT_INSTRUCTIONS,
    tools=[search_agents],
)
