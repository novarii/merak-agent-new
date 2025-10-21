import asyncio
from agents import Agent, run_demo_loop
from app.merak_agent import merak_agent

async def main() -> None:
    agent = merak_agent
    await run_demo_loop(agent)

if __name__ == "__main__":
    asyncio.run(main())