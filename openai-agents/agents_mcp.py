import argparse
import asyncio

from agents import Agent, HostedMCPTool, Runner

from dotenv import load_dotenv

load_dotenv()

"""This example demonstrates how to use the hosted MCP support in the OpenAI Responses API, with
approvals not required for any tools. You should only use this for trusted MCP servers."""


async def main(verbose: bool, stream: bool):
    agent = Agent(
        name="Assistant",
        instructions="Use the output from the tools to answer the questions.",
        model="gpt-4.1-mini",
        tools=[
            HostedMCPTool(
                tool_config={
                    "type": "mcp",
                    "server_label": "sports-mcp",
                    "server_url": "https://sports-mcp.ambitioussand-ba55d326.eastus2.azurecontainerapps.io/mcp",
                    "require_approval": "never",
                }
            )
        ],
    )

    if stream:
        result = Runner.run_streamed(agent, "Show news for college football, MLB. NHL and Nascar?")
        async for event in result.stream_events():
            if event.type == "run_item_stream_event":
                print(f"Got event of type {event.item.__class__.__name__}")
                if event.item.__class__.__name__ == "ToolCallItem":
                    tool_name = event.item.raw_item.name
                    tool_args = event.item.raw_item.arguments
                    print(f"Tool call Item: {tool_name} with args: {tool_args}")
        print(f"Done streaming; final result:\n {result.final_output}")
    else:
        res = await Runner.run(agent, "Show news for college football, MLB and Nascar?")
        print(res.final_output)

    if verbose:
        for item in res.new_items:
            print(item)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", default=False)
    parser.add_argument("--stream", action="store_true", default=True)
    args = parser.parse_args()

    asyncio.run(main(args.verbose, args.stream))