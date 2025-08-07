# Copyright (c) Microsoft. All rights reserved.

import asyncio
import os

from semantic_kernel.agents import Agent, SequentialOrchestration, OpenAIResponsesAgent, OpenAIAssistantAgent
from semantic_kernel.agents.runtime import InProcessRuntime
from semantic_kernel.contents import FunctionCallContent, FunctionResultContent
from semantic_kernel.contents.streaming_chat_message_content import StreamingChatMessageContent

# Import the modified plugin class
from .plugins.shadow_salesdocs_plugin import ShadowSalesDocsPlugin
from .plugins.shadow_account_plugin import ShadowAccountPlugin
from .plugins.shadow_client_plugin import ShadowClientPlugin

from .tools.searchshadow import SearchShadow
from .tools.searchcustomer import SearchCustomer
from .tools.searchclient import SearchUser

from dotenv import load_dotenv

load_dotenv()

ASSISTANT_ID = os.environ.get("ASSISTANT_ID")

INSTRUCTIONS="""### Purpose  
You are the **Sales Training Agent**. Your mission is to deliver **relevant, practical, and decisive guidance** for users working on active sales pursuits. Leverage the **`shadowRetrievalPlugin`** to pull the right material at the right moment.

---

### Context You Receive from Each User Query  

| Field | Meaning | How to Use |
|-------|---------|-----------|
| **Query**           | The user’s actual question | Use it to decide what advice is needed. |
| **AccountName**     | Target customer / prospect | Pass to `get_customer_docs` when you need account-specific info. |
| **ClientName / ClientId** | The user’s own company identifiers | Pass to `get_user_docs` for internal resources. |
| **Demand Stage**    | Current sales‑cycle stage (e.g., *Interest*, *Evaluation*) | Tailor depth and tactics to this stage. |

<details>
<summary>Example</summary>

```text
Query: What are some synergies between my company and the prospect account?
Context:
  AccountName: Allina Health
  ClientName: Growth Orbit
  ClientId: 112655FE-87CB-429B-A7B5-33342DAA9CA8
  Demand Stage: Interest
```
</details>

---

### shadowRetrievalPlugin

| Function | When to Call | Typical Questions |
|----------|--------------|-------------------|
| `get_sales_docs` | Any request about methodology, playbooks, or generic sales tactics | “Which probing questions work well in the discovery stage?” |
| `get_customer_docs` | Need deep knowledge of **AccountName** | “How do I strengthen relationships with decision makers at Panda Health?” |
| `get_user_docs` | Need insights about the user’s own company (**ClientName / ClientId**) | “Identify three solution synergies between us and the target account.” |

---

### Response Guidelines

1. **Be Decisive**  
   Provide clear, confident recommendations—salespeople rely on you to move deals forward.  
2. **Keep It Simple**  
   Communicate in crisp, jargon‑free language. Assume the user values speed over elaboration.  
3. **Stay on Topic**  
   Only answer **sales‑related** questions. If asked something else, politely decline.  
4. **Guide Through Dialogue**  
   Encourage reflection with open‑ended prompts (Deep Dive) that help users surface their own insights.  
5. **Find the Core Issue**  
   Look beyond the immediate ask. Use context and history to zero in on the root challenge.  
6. **Maintain Natural Flow**  
   Sound like a seasoned coach, not a robot. Feel free to share anecdotes, metaphors, or short bullet lists when helpful.  

---

### Example Workflow

1. **User Asks:**  
   “Help me assess our winnability at Allina Health.”

2. **You Decide:**  
   * Strategy topic → call `get_sales_docs`  
   * Account‑specific → call `get_customer_docs` with *Allina Health*

3. **Craft Response:**  
   *Blend playbook insights with customer intel; finish with an action checklist and one or two reflective questions.*

---

Use this framework to deliver **concise, high‑impact** guidance that accelerates every sales pursuit."""

# Instantiate search clients as singletons (if they are thread-safe or handle concurrency internally)
search_shadow_client = SearchShadow()
search_customer_client = SearchCustomer()
search_user_client = SearchUser()

"""
The following sample demonstrates how to create a concurrent orchestration for
executing multiple agents on the same task in parallel.

This sample demonstrates the basic steps of creating and starting a runtime, creating
a concurrent orchestration with multiple agents, invoking the orchestration, and finally
waiting for the results.
"""

async def get_agents() -> list[OpenAIAssistantAgent]:
    """Return a list of agents that will participate in the concurrent orchestration.

    Feel free to add or remove agents.
    """
    # Instantiate ShadowSalesDocsPlugin and pass the search clients
    shadow_salesdocs_plugin = ShadowSalesDocsPlugin(
            search_shadow_client
        )
    
    # Instantiate ShadowSalesDocsPlugin and pass the search clients
    shadow_account_plugin = ShadowAccountPlugin(
            search_customer_client
        )
    
    # Instantiate ShadowSalesDocsPlugin and pass the search clients
    shadow_client_plugin = ShadowClientPlugin(
            search_user_client
        )

    # Create the client using Azure OpenAI resources and configuration
    #client = OpenAIAssistantAgent.create_client(ai_model_id="gpt-4.1-mini")

    # Define the assistant definition
    #definition = await client.beta.assistants.retrieve(
    #       ASSISTANT_ID
    #    )

    # Create the OpenAIAssistantAgent instance using the client and the assistant definition and the defined plugin
    #shadow_agent = OpenAIAssistantAgent(
    #        client=client,
    #        definition=definition,
    #        plugins=[shadow_plugin],
    #    )

    # 1. Create the client using Azure OpenAI resources and configuration
    client = OpenAIResponsesAgent.create_client(ai_model_id="gpt-4.1-mini")
    
    shadow_salesdocs_agent = OpenAIResponsesAgent(
        name="ShadowSalesDocsAgent",
        instructions="You are a retriever Agent.  You handle retrieval requests for sales documents.",
        ai_model_id="gpt-4.1-mini",
        client=client,
        plugins=[shadow_salesdocs_plugin]
    )

    shadow_account_agent = OpenAIResponsesAgent(
        name="ShadowAccountAgent",
        instructions="You are a retriever Agent.  You handle retrieval requests for account documents.",
        ai_model_id="gpt-4.1-mini",
        client=client,
        plugins=[shadow_account_plugin]
    )

    shadow_client_agent = OpenAIResponsesAgent(
        name="ShadowClientAgent",
        instructions="You are a retriever Agent.  You handle retrieval requests for client documents.",
        ai_model_id="gpt-4.1-mini",
        client=client,
        plugins=[shadow_client_plugin]
    )

    return [shadow_salesdocs_agent, shadow_account_agent, shadow_client_agent]

# This callback function will be called for each intermediate message,
# which will allow one to handle FunctionCallContent and FunctionResultContent.
# If the callback is not provided, the agent will return the final response
# with no intermediate tool call steps.
async def handle_streaming_intermediate_steps(message: StreamingChatMessageContent, is_final: bool) -> None:
    # Handle function calls and results immediately
    for item in message.items or []:
        if isinstance(item, FunctionResultContent):
            # Print only the first 100 characters of the function result
            result_text = str(item.result)[:100]
            if len(str(item.result)) > 100:
                result_text += "..."
            print(f"Function Result:> {result_text} for function: {item.name}")
        elif isinstance(item, FunctionCallContent):
            print(f"Function Call:> {item.name} with arguments: {item.arguments}")
    
    # Print streaming content (without newlines to allow continuous text)
    if message.content:
        print(message.content, end="", flush=True)
    
    # Add a newline when the response is final
    if is_final:
        print()  # Just add a newline, no extra message

async def main():
    """Main function to run the agents."""
    # 1. Create a concurrent orchestration with multiple agents
    agents = await get_agents()
    concurrent_orchestration = SequentialOrchestration(members=agents, streaming_agent_response_callback=handle_streaming_intermediate_steps)
    #concurrent_orchestration = ConcurrentOrchestration(members=agents)


    # 2. Create a runtime and start it
    runtime = InProcessRuntime()
    runtime.start() 

    # 3. Invoke the orchestration with a task and the runtime
    orchestration_result = await concurrent_orchestration.invoke(
        task="Summarize what the account does and similarities to my company.  Context: AccountName: Allina Health ClientName: Growth Orbit",
        runtime=runtime,
    )

    # 4. Wait for the results
    # Note: the order of the results is not guaranteed to be the same
    # as the order of the agents in the orchestration.
    value = await orchestration_result.get(timeout=20)

    
    # Since we're using streaming callbacks, the response is already printed above
    # Uncomment the lines below if you want to see the final consolidated results
    #for item in value:
    #    print(f"# {item.name}: {item.model_dump_json(indent=2)}")

    # 5. Stop the runtime after the invocation is complete
    await runtime.stop_when_idle()



if __name__ == "__main__":
    asyncio.run(main())