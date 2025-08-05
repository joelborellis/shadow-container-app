import asyncio
import os
import shutil
import subprocess
import time
from typing import Any

from agents import Agent, Runner, gen_trace_id, trace
from agents.mcp import MCPServer, MCPServerStreamableHttp
from agents.model_settings import ModelSettings

from dotenv import load_dotenv

load_dotenv()


async def run(mcp_server: MCPServer):
    agent = Agent(
        name="Assistant",
        instructions="Use the output from the tools to answer the questions.",
        mcp_servers=[mcp_server],
        model="gpt-4.1-mini",
        model_settings=ModelSettings(tool_choice="required"),
    )

    # Use the `add` tool to add two numbers
    message = "Show news for college football, MLB and Nascar?"
    print(f"Running: {message}")
    result = Runner.run_streamed(starting_agent=agent, input=message)
    async for event in result.stream_events():
            if event.type == "run_item_stream_event":
                print(f"Got event of type {event.item.__class__.__name__}")
                if event.item.__class__.__name__ == "ToolCallItem":
                    tool_name = event.item.raw_item.name
                    tool_args = event.item.raw_item.arguments
                    print(f"Tool call Item: {tool_name} with args: {tool_args}")
    print(f"Done streaming; final result:\n {result.final_output}")


async def main():
    async with MCPServerStreamableHttp(
        name="Streamable HTTP Python Server",
        params={
            "url": "https://sports-mcp.ambitioussand-ba55d326.eastus2.azurecontainerapps.io/mcp",
        },
    ) as server:
        trace_id = gen_trace_id()
        with trace(workflow_name="Streamable HTTP Example", trace_id=trace_id):
            print(f"View trace: https://platform.openai.com/traces/trace?trace_id={trace_id}\n")
            await run(server)


if __name__ == "__main__":
    print("Testing Streamable HTTP MCP Server")
    print("=" * 55)
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error running program: {e}")