import asyncio
import os
import json

from semantic_kernel.agents import OpenAIResponsesAgent
from semantic_kernel.contents import AuthorRole, FunctionCallContent, FunctionResultContent
from semantic_kernel.contents.chat_message_content import ChatMessageContent

from .tools.searchshadow import SearchShadow
from .tools.searchcustomer import SearchCustomer
from .tools.searchclient import SearchUser

# Import the modified plugin class
from .plugins.shadow_insights_plugin import ShadowInsightsPlugin

from dotenv import load_dotenv

load_dotenv()

# Instantiate search clients as singletons (if they are thread-safe or handle concurrency internally)
search_shadow_client = SearchShadow()
search_customer_client = SearchCustomer()
search_user_client = SearchUser()

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



# This callback function will be called for each intermediate message,
# which will allow one to handle FunctionCallContent and FunctionResultContent.
# If the callback is not provided, the agent will return the final response
# with no intermediate tool call steps.
async def handle_streaming_intermediate_steps(message: ChatMessageContent) -> None:
    for item in message.items or []:
        if isinstance(item, FunctionResultContent):
            result_preview = str(item.result)[:100]
            if len(str(item.result)) > 100:
                result_preview += "..."
            print(f"Function Result:> {result_preview} for function: {item.name}")
        elif isinstance(item, FunctionCallContent):
            print(f"Function Call:> {item.name} with arguments: {item.arguments}")
        else:
            print(f"{item}")


async def main():
    # 1. Create the client using Azure OpenAI resources and configuration
    client = OpenAIResponsesAgent.create_client(ai_model_id="gpt-4.1-mini")

    # 2. Instantiate ShadowInsightsPlugin and pass the search clients
    shadow_plugin = ShadowInsightsPlugin(
            search_shadow_client, search_customer_client, search_user_client
        )

    # 3. Create a Semantic Kernel agent for the OpenAI Responses API
    agent = OpenAIResponsesAgent(
        ai_model_id="gpt-4.1-mini",
        client=client,
        name="ShadowInsightsAgent",
        instructions=INSTRUCTIONS,
        plugins=[shadow_plugin],
    )

    # 4. Create a thread for the agent
    # If no thread is provided, a new thread will be
    # created and returned with the initial response
    thread = None

    print("Welcome to Shadow Seller Agent.")
    print("-" * 60)

    try:
        while True:
            # Get user input
            user_input = input(f"\n{AuthorRole.USER}: ").strip()
            
            # Check if user wants to exit
            if user_input.lower() in ['exit', 'quit']:
                print("Goodbye!")
                break
                
            # Skip empty inputs
            if not user_input:
                continue

            print(f"# {AuthorRole.USER}: '{user_input}'")

            first_chunk = True
            async for response in agent.invoke_stream(
                messages=user_input,
                thread=thread,
                #on_intermediate_message=handle_streaming_intermediate_steps,
            ):
                thread = response.thread
                if first_chunk:
                    print(f"# {response.name}: ", end="", flush=True)
                    first_chunk = False
                print(response.content, end="", flush=True)
            print()
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    asyncio.run(main())