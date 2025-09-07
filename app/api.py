import fastapi
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
import json
import logging
import asyncio

from .tools.searchshadow import SearchShadow
from .tools.searchcustomer import SearchCustomer
from .tools.searchclient import SearchUser

from semantic_kernel.agents import OpenAIResponsesAgent, ResponsesAgentThread
from semantic_kernel.contents.chat_message_content import (
    ChatMessageContent,
    FunctionCallContent,
    FunctionResultContent,
)
from semantic_kernel.contents import AuthorRole

# Import the modified plugin class
from .plugins.shadow_insights_plugin import ShadowInsightsPlugin

from typing import Optional, AsyncGenerator

app = fastapi.FastAPI()

# Allow requests from all domains (not always recommended for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure module-level logger
logger = logging.getLogger("api.py")
logger.setLevel(logging.INFO)

INSTRUCTIONS="""### Purpose  
You are the **Sales Training Agent**. Your mission is to deliver **relevant, practical, and decisive guidance** for users working on active sales pursuits. Leverage the **`shadowRetrievalPlugin`** to pull the right content to help answer the users query.

---

### Context You Receive from Each User Query  

| Field | Meaning | How to Use |
|-------|---------|-----------|
| **Query**           | The user’s actual question | Use it to decide what advice is needed. |
| **AccountName**     | Target customer / prospect account | Pass to `get_customer_docs` when you need target or prospect account-specific info. |
| **ClientName** | The user’s own company name | Pass to `get_user_docs` when you need user-company specific info. |
| **Demand Stage**    | Current sales‑cycle stage (e.g., *Interest*, *Evaluation*) | Tailor depth and tactics to this stage. |

<details>
<summary>Example Context received from User Query</summary>

```text
Query: What are some synergies between my company and the prospect account?
Context:
  AccountName: Allina Health
  ClientName: Growth Orbit
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

### Example Workflow 1

1. **User Asks:**  
   “Help me assess our winnability at Allina Health.”

2. **You Decide:**  
   * Strategy topic → call `get_sales_docs`  
   * Account‑specific → call `get_customer_docs` with AccountName - *Allina Health*

3. **Craft Response:**  
   *Blend sales playbook insights with customer account intel; finish with an action checklist and one or two reflective questions.*
   
### Example Workflow 2

1. **User Asks:**  
   “Help me assess the synergies between my company and the prospect account.”

2. **You Decide:**   
   * User-company-specific → call `get_user_docs` with ClientName
   * Account‑specific → call `get_customer_docs` with AccountName

3. **Craft Response:**  
   *Blend User-company-specific and Account-specific insights; finish with an action checklist and one or two reflective questions.*

---

Use this framework to deliver **concise, high‑impact** guidance that accelerates every sales pursuit."""


# Define request body model
class ShadowRequest(BaseModel):
    query: str
    threadId: str
    demand_stage: Optional[str] = None
    AccountName: Optional[str] = None
    AccountId: Optional[str] = None
    ClientName: Optional[str] = None
    ClientId: Optional[str] = None
    PursuitId: Optional[str] = None
    additional_instructions: Optional[str] = None


# Instantiate search clients as singletons (if they are thread-safe or handle concurrency internally)
search_shadow_client = SearchShadow()
search_customer_client = SearchCustomer()
search_user_client = SearchUser()

def create_chat_messages_from_request(request: ShadowRequest) -> list[ChatMessageContent]:
    """
    Convert ShadowRequest to a list of ChatMessageContent objects.
    
    Args:
        request: The ShadowRequest containing query and metadata
        
    Returns:
        list[ChatMessageContent]: List of messages for the agent
    """
    messages = []
    
    # Create the main user query message
    query = request.query
    
    # Add context parameters to the query if they exist
    context_parts = []
    if request.AccountName:
        context_parts.append(f"AccountName: {request.AccountName}")
    if request.ClientName:
        context_parts.append(f"ClientName: {request.ClientName}")
    if request.demand_stage:
        context_parts.append(f"Demand Stage: {request.demand_stage}")
    #if request.PursuitId:
        #context_parts.append(f"Pursuit ID: {request.PursuitId}")
    
    # Combine query with context
    if context_parts:
        enhanced_query = f"{query}\n\nContext:\n" + "\n".join(f"- {part}" for part in context_parts)
    else:
        enhanced_query = query
    
    # Create the user message
    user_message = ChatMessageContent(
        role=AuthorRole.USER,
        content=enhanced_query
    )
    messages.append(user_message)
    
    return messages

async def get_agent() -> Optional[OpenAIResponsesAgent]:

    try:
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
            store_enabled=True,
        )

        if agent is None:
            logger.error(
                    "Failed to retrieve the assistant agent. Please check the assistant ID."
                )
            return None
    except Exception as e:
        logger.error("An error occurred while retrieving the assistant agent: %s", e)
        return None

    return agent


async def event_stream(request: ShadowRequest) -> AsyncGenerator[str, None]:
    """
    Asynchronously stream responses back to the caller using Server-Sent Events (SSE).
    Optimized approach with direct yielding for content and queue only for intermediate events.
    """
    def safe_serialize(data):
        if isinstance(data, (str, int, float, bool, list, dict, type(None))):
            return data
        return str(data)

    def format_sse_event(event_type: str, event_data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"

    # Queue only for intermediate events (function calls/results) - not for content
    intermediate_queue = asyncio.Queue()
    
    # Callback to handle intermediate messages (function calls, results, etc.)
    async def handle_streaming_intermediate_steps(message: ChatMessageContent) -> None:
        """Handle intermediate messages including function calls and results."""
        for item in message.items or []:
            if isinstance(item, FunctionCallContent):
                event_data = format_sse_event("function_call", {
                    "type": "function_call",
                    "function_name": item.name,
                    "arguments": safe_serialize(item.arguments)
                })
                await intermediate_queue.put(event_data)
                logger.info(f"Yielded function_call event for: {item.name}")
            elif isinstance(item, FunctionResultContent):
                event_data = format_sse_event("function_result", {
                    "type": "function_result",
                    "function_name": item.name,
                    "result": safe_serialize(item.result)
                })
                await intermediate_queue.put(event_data)
                logger.info(f"Yielded function_result event for: {item.name}")
            else:
                # Handle other intermediate content if needed
                event_data = format_sse_event("intermediate", {
                    "type": "intermediate",
                    "content": str(item)
                })
                await intermediate_queue.put(event_data)

    async def yield_pending_intermediates():
        """Yield any pending intermediate events without blocking."""
        while True:
            try:
                event = intermediate_queue.get_nowait()
                yield event
            except asyncio.QueueEmpty:
                break

    try:
        agent = await get_agent()
        if not agent:
            yield format_sse_event("error", {"type": "error", "error": "Failed to initialize agent"})
            return        # Convert ShadowRequest to list[ChatMessageContent]
        messages = create_chat_messages_from_request(request)
        
        # For OpenAIResponsesAgent, we let it handle threading internally
        # The thread ID will be available in the response.thread property
        threadId = request.threadId
        current_thread = ResponsesAgentThread(client=agent.client, previous_response_id=threadId) if threadId else None

        first_chunk = True
        thread_info_sent = False
        async for response in agent.invoke_stream(
            messages=messages,
            thread=current_thread,
            on_intermediate_message=handle_streaming_intermediate_steps,
        ):
            # Yield any pending intermediate events first (non-blocking)
            async for intermediate_event in yield_pending_intermediates():
                yield intermediate_event            # Send thread info once we have the thread ID from the response
            if not thread_info_sent and hasattr(response, 'thread') and response.thread:
                # For OpenAIResponsesAgent, response.thread should be a string thread ID
                thread_info_data = {
                    "type": "thread_info",
                    "thread_id": str(response.thread.id)
                }
                yield format_sse_event("thread_info", thread_info_data)
                thread_info_sent = True
        
            # Handle regular response content - yield directly for lowest latency
            content = ""
            if hasattr(response, 'content') and response.content is not None:
                content = str(response.content)
            if content.strip():
                content_data = {
                    "type": "content",
                    "content": content
                }
                yield format_sse_event("content", content_data)
        
        # Yield any remaining intermediate events
        async for intermediate_event in yield_pending_intermediates():
            yield intermediate_event
        
        # Send stream completion event
        yield format_sse_event("stream_complete", {
            "type": "stream_complete"
        })

    except HTTPException as exc:
        yield format_sse_event("error", {"type": "error", "error": exc.detail})
    except Exception as e:
        logger.exception("Unexpected error during streaming SSE.")
        yield format_sse_event("error", {"type": "error", "error": str(e)})


@app.post("/shadow-sk")
async def shadow_sk(request: ShadowRequest):
    """
    Endpoint that receives a query, passes it to the agent, and streams back responses.
    """
    return StreamingResponse(
        event_stream(request),
        media_type="text/event-stream",
        status_code=200,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
