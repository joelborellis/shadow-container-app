import fastapi
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
import json
import os
import logging
import asyncio
import time
from collections import defaultdict

from .tools.searchshadow import SearchShadow
from .tools.searchcustomer import SearchCustomer
from .tools.searchclient import SearchUser

from semantic_kernel.agents import OpenAIAssistantAgent, AssistantAgentThread
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
logger = logging.getLogger("__init__.py")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


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

ASSISTANT_ID = os.environ.get("ASSISTANT_ID")

# Global dictionary to track token usage per thread
thread_token_usage = {}

# Track when threads were last accessed for cleanup
thread_last_access = defaultdict(float)
MAX_THREAD_AGE_HOURS = 24  # Clean up threads older than 24 hours


def cleanup_old_threads():
    """Clean up token tracking for threads not accessed recently."""
    current_time = time.time()
    cutoff_time = current_time - (MAX_THREAD_AGE_HOURS * 3600)
    
    threads_to_remove = [
        thread_id for thread_id, last_access in thread_last_access.items()
        if last_access < cutoff_time
    ]
    
    for thread_id in threads_to_remove:
        if thread_id in thread_token_usage:
            del thread_token_usage[thread_id]
        del thread_last_access[thread_id]
        logger.info(f"Cleaned up old thread: {thread_id}")


def get_thread_token_usage(thread_id: str) -> dict:
    """Get current token usage for a thread with access tracking."""
    if thread_id:
        thread_last_access[thread_id] = time.time()
        return thread_token_usage.get(thread_id, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def get_all_thread_stats() -> dict:
    """Get statistics about all tracked threads (useful for monitoring)."""
    return {
        "total_threads": len(thread_token_usage),
        "total_tokens_across_all_threads": sum(usage["total_tokens"] for usage in thread_token_usage.values()),
        "threads": {thread_id: usage for thread_id, usage in thread_token_usage.items()}
    }


def extract_and_accumulate_tokens(response, thread_id: str) -> dict:
    """
    Extract token usage from the response and accumulate it for the thread.
    
    Args:
        response: The agent response object
        thread_id: The thread ID to track tokens for
        
    Returns:
        dict: Current accumulated token usage for the thread
    """
    if not thread_id:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    
    # Initialize thread token tracking if not exists
    if thread_id not in thread_token_usage:
        thread_token_usage[thread_id] = {
            "input_tokens": 0,
            "output_tokens": 0, 
            "total_tokens": 0
        }
    
    # Extract token usage from response metadata
    current_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    
    try:
        # First, try model_dump_json() to get the complete response structure
        if hasattr(response, 'model_dump_json'):
            try:
                response_json = response.model_dump_json()
                response_data = json.loads(response_json)
                
                # Check for usage field directly (most common case)
                if 'usage' in response_data and isinstance(response_data['usage'], dict):
                    usage = response_data['usage']
                    current_usage = {
                        "input_tokens": usage.get('prompt_tokens', 0),
                        "output_tokens": usage.get('completion_tokens', 0),
                        "total_tokens": usage.get('total_tokens', 0)
                    }
                    if current_usage["total_tokens"] > 0:
                        logger.info(f"Found token usage in model_dump_json: {current_usage}")
                        
            except Exception as e:
                logger.debug(f"Error in model_dump_json processing: {e}")
        
        # Fallback to direct attribute access if model_dump_json didn't work or find usage
        if current_usage["total_tokens"] == 0 and hasattr(response, 'usage') and response.usage:
            current_usage["input_tokens"] = getattr(response.usage, 'prompt_tokens', 0)
            current_usage["output_tokens"] = getattr(response.usage, 'completion_tokens', 0) 
            current_usage["total_tokens"] = getattr(response.usage, 'total_tokens', 0)
            
            if current_usage["total_tokens"] > 0:
                logger.info(f"Found token usage in response.usage: {current_usage}")
        
        # Check for usage in metadata if other methods didn't work
        elif current_usage["total_tokens"] == 0 and hasattr(response, 'metadata') and response.metadata:
            usage = response.metadata.get('usage', {})
            if usage:
                current_usage["input_tokens"] = usage.get('prompt_tokens', 0)
                current_usage["output_tokens"] = usage.get('completion_tokens', 0)
                current_usage["total_tokens"] = usage.get('total_tokens', 0)
                
                if current_usage["total_tokens"] > 0:
                    logger.info(f"Found token usage in response metadata: {current_usage}")
                        
    except Exception as e:
        logger.error(f"Error extracting token usage: {e}")
    
    # Accumulate the usage for this thread
    if current_usage["total_tokens"] > 0:
        thread_token_usage[thread_id]["input_tokens"] += current_usage["input_tokens"]
        thread_token_usage[thread_id]["output_tokens"] += current_usage["output_tokens"]
        thread_token_usage[thread_id]["total_tokens"] += current_usage["total_tokens"]
        
        logger.info(f"Updated thread {thread_id} token usage: {thread_token_usage[thread_id]}")
    
    return thread_token_usage[thread_id].copy()


def reset_thread_tokens(thread_id: str):
    """Reset token tracking for a thread."""
    if thread_id in thread_token_usage:
        del thread_token_usage[thread_id]
        logger.info(f"Reset token tracking for thread: {thread_id}")


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
    if request.ClientId:
        context_parts.append(f"ClientId: {request.ClientId}")
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


async def get_agent() -> Optional[OpenAIAssistantAgent]:
    """
    Setup the Assistant with error handling.
    """
    try:
        # (2) Create plugin
        # Instantiate ShadowInsightsPlugin and pass the search clients
        shadow_plugin = ShadowInsightsPlugin(
            search_shadow_client, search_customer_client, search_user_client
        )
    except Exception as e:
        logger.error("Failed to instantiate ShadowInsightsPlugin: %s", e)
        return None

    try:
        # Create the client using Azure OpenAI resources and configuration
        client = OpenAIAssistantAgent.create_client(ai_model_id="gpt-4.1-mini")

        # Define the assistant definition
        definition = await client.beta.assistants.retrieve(
            ASSISTANT_ID
        )

        # Create the OpenAIAssistantAgent instance using the client and the assistant definition and the defined plugin
        agent = OpenAIAssistantAgent(
            client=client,
            definition=definition,
            plugins=[shadow_plugin],
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
    Simplified approach using direct asyncio.Queue without extra wrapper classes.
    """
    def safe_serialize(data):
        if isinstance(data, (str, int, float, bool, list, dict, type(None))):
            return data
        return str(data)

    def format_sse_event(event_type: str, event_data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"

    # Simple event queue for immediate streaming - no wrapper needed!
    event_queue = asyncio.Queue()
    
    # Callback to handle intermediate messages (function calls, results, etc.)
    async def handle_intermediate_message(message: ChatMessageContent) -> None:
        """Handle intermediate messages including function calls and results."""
        for item in message.items or []:
            if isinstance(item, FunctionCallContent):
                event_data = format_sse_event("function_call", {
                    "type": "function_call",
                    "function_name": item.name,
                    "arguments": safe_serialize(item.arguments)
                })
                await event_queue.put(event_data)
                logger.info(f"Yielded function_call event for: {item.name}")
            elif isinstance(item, FunctionResultContent):
                event_data = format_sse_event("function_result", {
                    "type": "function_result",
                    "function_name": item.name,
                    "result": safe_serialize(item.result)
                })
                await event_queue.put(event_data)
                logger.info(f"Yielded function_result event for: {item.name}")
            else:
                # Handle other intermediate content if needed
                event_data = format_sse_event("intermediate", {
                    "type": "intermediate",
                    "content": str(item)
                })
                await event_queue.put(event_data)

    async def stream_processor():
        """Process the agent stream in the background."""
        try:
            agent = await get_agent()
            if not agent:
                await event_queue.put(format_sse_event("error", {"type": "error", "error": "Failed to initialize agent"}))
                return

            # Convert ShadowRequest to list[ChatMessageContent]
            messages = create_chat_messages_from_request(request)
            
            threadId = request.threadId
            current_thread = AssistantAgentThread(client=agent.client, thread_id=threadId) if threadId else None
            
            # If no threadId provided, we'll get a new one from the response and reset token tracking
            is_new_thread = not bool(threadId)
            
            additional_instructions = (
                f"<additional_instructions>{request.additional_instructions}</additional_instructions>"
                if request.additional_instructions else None
            )

            first_chunk = True
            actual_thread_id = threadId
              # Process the stream and yield events as soon as they are available
            async for response in agent.invoke_stream(
                messages=messages,
                thread=current_thread,
                additional_instructions=additional_instructions,
                on_intermediate_message=handle_intermediate_message,  # Add the callback here
            ):
                # Extract thread ID from response if we didn't have one
                if hasattr(response, 'thread') and response.thread:
                    actual_thread_id = getattr(response.thread, 'id', threadId)
                
                # If this is a new thread (no threadId was provided), reset token tracking
                if is_new_thread and actual_thread_id:
                    reset_thread_tokens(actual_thread_id)
                    is_new_thread = False  # Only reset once per request
                  # Yield thread info on first chunk (without token usage - tokens will be sent after completion)
                if first_chunk:
                    thread_info = {
                        "type": "thread_info",
                        "agent_name": getattr(response, 'name', 'Unknown'),
                        "thread_id": actual_thread_id or 'Unknown'
                    }
                    await event_queue.put(format_sse_event("thread_info", thread_info))
                    first_chunk = False# Handle regular response content
                content = ""
                if hasattr(response, 'content') and response.content is not None:
                    content = str(response.content)
                if content.strip():
                    content_data = {
                        "type": "content",
                        "content": content
                    }
                    await event_queue.put(format_sse_event("content", content_data))            # After stream completion, get token usage from the completed run
            try:
                if agent and actual_thread_id:
                    # List the runs for this thread to get the latest run with token usage
                    runs = await agent.client.beta.threads.runs.list(
                        thread_id=actual_thread_id,
                        limit=1
                    )
                    
                    if runs.data and len(runs.data) > 0:
                        latest_run = runs.data[0]
                        logger.info(f"Latest run status: {latest_run.status}")
                        
                        # Extract and accumulate token usage from the completed run
                        if hasattr(latest_run, 'usage') and latest_run.usage:
                            prompt_tokens = getattr(latest_run.usage, 'prompt_tokens', 0) or 0
                            completion_tokens = getattr(latest_run.usage, 'completion_tokens', 0) or 0
                            total_tokens = getattr(latest_run.usage, 'total_tokens', 0) or 0
                            
                            if total_tokens > 0:
                                # Initialize thread token tracking if not exists
                                if actual_thread_id not in thread_token_usage:
                                    thread_token_usage[actual_thread_id] = {
                                        "input_tokens": 0,
                                        "output_tokens": 0,
                                        "total_tokens": 0
                                    }
                                
                                # Accumulate the tokens for this request
                                thread_token_usage[actual_thread_id]["input_tokens"] += prompt_tokens
                                thread_token_usage[actual_thread_id]["output_tokens"] += completion_tokens
                                thread_token_usage[actual_thread_id]["total_tokens"] += total_tokens
                                
                                logger.info(f"Updated thread {actual_thread_id} token usage: {thread_token_usage[actual_thread_id]}")
                            else:
                                logger.info(f"No token usage found in latest run for thread {actual_thread_id}")
                        else:
                            logger.info(f"No usage data found in latest run for thread {actual_thread_id}")
                    else:
                        logger.info(f"No runs found for thread {actual_thread_id}")
                        
            except Exception as e:
                logger.error(f"Error retrieving run status from thread: {e}")

            # Send token usage event just before stream completion
            final_token_usage = thread_token_usage.get(actual_thread_id, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
            if final_token_usage["total_tokens"] > 0:
                await event_queue.put(format_sse_event("token_usage", {
                    "type": "token_usage",
                    "thread_id": actual_thread_id,
                    "token_usage": final_token_usage
                }))
            
            # Send stream completion event
            await event_queue.put(format_sse_event("stream_complete", {
                "type": "stream_complete"
            }))

        except HTTPException as exc:
            await event_queue.put(format_sse_event("error", {"type": "error", "error": exc.detail}))
        except Exception as e:
            logger.exception("Unexpected error during streaming SSE.")
            await event_queue.put(format_sse_event("error", {"type": "error", "error": str(e)}))
        finally:
            # Signal end of stream
            await event_queue.put(None)

    # Start background processing
    task = asyncio.create_task(stream_processor())
    
    try:
        # Yield events as they become available with minimal latency
        while True:
            event = await event_queue.get()
            if event is None:  # End signal
                break
            yield event
    finally:
        # Clean up the background task
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


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


# Optional: Add endpoint for monitoring token usage
@app.get("/shadow-sk/stats")
async def get_token_stats():
    """
    Get current token usage statistics for all threads.
    """
    # Clean up old threads before returning stats
    cleanup_old_threads()
    
    return {
        "timestamp": time.time(),
        "statistics": get_all_thread_stats()
    }


@app.get("/shadow-sk/health")
async def health_check():
    """
    Health check endpoint with token tracking diagnostics.
    """
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "token_tracking": {
            "active_threads": len(thread_token_usage),
            "total_tokens_tracked": sum(usage["total_tokens"] for usage in thread_token_usage.values()),            "optimizations_active": True,            "features": [
                "Token usage extracted from completed runs (not streaming chunks)",
                "Direct run.usage attribute access for accurate token counts", 
                "Automatic thread cleanup",
                "Cumulative token tracking per thread",
                "Real-time streaming with post-completion token accumulation",
                "Token usage sent as separate event after stream completion"
            ]
        },
        "assistant_id": ASSISTANT_ID is not None
    }
