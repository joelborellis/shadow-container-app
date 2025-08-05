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
            
            
            additional_instructions = (
                f"<additional_instructions>{request.additional_instructions}</additional_instructions>"
                if request.additional_instructions else None
            )

            first_chunk = True
            actual_thread_id = None

            # Process the stream and yield events as soon as they are available
            async for response in agent.invoke_stream(
                messages=messages,
                thread=current_thread,
                additional_instructions=additional_instructions,
                on_intermediate_message=handle_intermediate_message,  # Add the callback here
            ):  
                # Yield thread info on first chunk (without token usage - tokens will be sent after completion)
                if first_chunk:
                    # Get the actual thread ID from various sources
                    if current_thread and current_thread.thread_id:
                        actual_thread_id = current_thread.thread_id
                        logger.info(f"Using thread_id from current_thread: {actual_thread_id}")
                    elif threadId:
                        actual_thread_id = threadId
                        logger.info(f"Using provided threadId: {actual_thread_id}")
                    else:
                        # When no thread is provided, the agent creates one internally
                        # Try multiple approaches to get the thread ID
                        try:
                            logger.info("Searching for thread ID in agent and response objects...")
                            
                            # Method 1: Check agent attributes
                            agent_attrs = [attr for attr in dir(agent) if 'thread' in attr.lower()]
                            logger.info(f"Agent thread-related attributes: {agent_attrs}")
                            
                            # Method 2: Check response attributes more thoroughly
                            response_attrs = [attr for attr in dir(response) if not attr.startswith('__')]
                            logger.info(f"Response attributes: {response_attrs[:10]}...")  # Log first 10
                            
                            # Method 3: Try to access common thread locations
                            potential_locations = [
                                ('agent.thread', lambda: getattr(agent, 'thread', None)),
                                ('agent._thread', lambda: getattr(agent, '_thread', None)),
                                ('agent.current_thread', lambda: getattr(agent, 'current_thread', None)),
                                ('response.thread', lambda: getattr(response, 'thread', None)),
                                ('response._thread', lambda: getattr(response, '_thread', None)),
                            ]
                            
                            for location_name, getter in potential_locations:
                                try:
                                    thread_obj = getter()
                                    if thread_obj:
                                        logger.info(f"Found thread object at {location_name}: {type(thread_obj)}")
                                        if hasattr(thread_obj, 'thread_id'):
                                            actual_thread_id = thread_obj.thread_id
                                            logger.info(f"Successfully extracted thread_id from {location_name}: {actual_thread_id}")
                                            break
                                        elif isinstance(thread_obj, str):
                                            actual_thread_id = thread_obj
                                            logger.info(f"Found string thread_id at {location_name}: {actual_thread_id}")
                                            break
                                except Exception as e:
                                    logger.debug(f"Could not access {location_name}: {e}")
                            
                            if not actual_thread_id:
                                # Last resort: try to find thread ID in response content if it's a dict-like object
                                if hasattr(response, '__dict__'):
                                    response_dict = response.__dict__
                                    for key, value in response_dict.items():
                                        if 'thread' in key.lower() and isinstance(value, str) and value.startswith('thread_'):
                                            actual_thread_id = value
                                            logger.info(f"Found thread_id in response.__dict__['{key}']: {actual_thread_id}")
                                            break
                                        elif hasattr(value, 'thread_id'):
                                            actual_thread_id = value.thread_id
                                            logger.info(f"Found thread_id in response.__dict__['{key}'].thread_id: {actual_thread_id}")
                                            break
                            
                            if not actual_thread_id:
                                actual_thread_id = 'Auto-Generated'
                                logger.info("Could not extract thread_id from any location")
                                
                        except Exception as e:
                            logger.error(f"Error searching for thread info: {e}")
                            actual_thread_id = 'Auto-Generated'
                    
                    thread_info = {
                        "type": "thread_info",
                        "agent_name": getattr(response, 'name', 'ShadowAssistant'),
                        "thread_id": actual_thread_id
                    }
                    await event_queue.put(format_sse_event("thread_info", thread_info))
                    first_chunk = False 
                
                # Handle regular response content
                content = ""
                if hasattr(response, 'content') and response.content is not None:
                    content = str(response.content)
                if content.strip():
                    content_data = {
                        "type": "content",
                        "content": content
                    }
                    await event_queue.put(format_sse_event("content", content_data))
            
            # Send stream completion event after the loop
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
