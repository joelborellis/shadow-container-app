"""
Optimized test script to demonstrate real-time streaming events from the FastAPI endpoint.
This version uses proper SSE streaming techniques for immediate event display.
"""

import asyncio
import aiohttp
import json
import sys

async def test_streaming_events():
    """Test the streaming endpoint with real-time event display."""
    url = "http://localhost:8000/shadow-sk"  # Local test server
    
    # Test payload with empty threadId to create a new thread
    payload = {
        "query": "What are some synergies between my company and the prospect account?",
        "threadId": "",  # Empty to create new thread - server will return the new thread_id
        "demand_stage": "Interest",
        "AccountName": "Allina Health",
        "AccountId": "",  # Example account ID
        "ClientName": "Growth Orbit",
        "ClientId": "112655FE-87CB-429B-A7B5-33342DAA9CA8",  # Example client ID
        "PursuitId": "",
        "additional_instructions": "Format your output in markdown.",
    }
    
    try:
        # Configure session for real-time streaming
        timeout = aiohttp.ClientTimeout(total=None)  # No timeout for streaming
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    print("[START] Starting to receive events...\n")
                    sys.stdout.flush()  # Force immediate display
                    
                    # Track content streaming state
                    content_buffer = ""
                    content_started = False
                    buffer = ""
                    
                    # Stream data in real-time with small chunks
                    async for chunk in response.content.iter_chunked(64):  # Small chunks for real-time
                        try:
                            chunk_str = chunk.decode('utf-8')
                            buffer += chunk_str
                            
                            # Process complete lines from buffer
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                line_str = line.strip()
                                
                                if not line_str:
                                    continue
                                    
                                if line_str.startswith('event:'):
                                    event_type = line_str.split(':', 1)[1].strip()
                                    # Only print event header for non-content events
                                    if event_type != 'content':
                                        if content_started:
                                            print()  # New line to finish content
                                            content_started = False
                                            content_buffer = ""
                                        print(f"\n[EVENT] {event_type}")
                                        print("-" * 30)
                                        sys.stdout.flush()
                                    
                                elif line_str.startswith('data:'):
                                    data_str = line_str.split(':', 1)[1].strip()
                                    try:
                                        data = json.loads(data_str)
                                        
                                        # Update content state
                                        if data.get('type') == 'content':
                                            if not content_started:
                                                print("\n[CONTENT] ", end="", flush=True)
                                                content_started = True
                                            content_buffer += data['content']
                                            print(data['content'], end="", flush=True)
                                        elif data.get('type') in ['function_call', 'function_result', 'intermediate', 'thread_info']:
                                            if content_started:
                                                print()  # New line to finish content
                                                content_started = False
                                                content_buffer = ""
                                            await handle_event(data)
                                        elif data.get('type') == 'stream_complete':
                                            if content_started:
                                                print()  # New line to finish content
                                            print(f"\n[STREAM COMPLETE]")
                                            sys.stdout.flush()
                                            return
                                        elif data.get('type') == 'error':
                                            await handle_event(data)
                                            
                                    except json.JSONDecodeError as e:
                                        print(f"[ERROR] Invalid JSON: {data_str} - {e}")
                                        sys.stdout.flush()
                                        
                        except UnicodeDecodeError:
                            # Skip malformed chunks
                            continue
                        
                else:
                    error_text = await response.text()
                    print(f"[ERROR] {response.status} - {error_text}")
                    
    except Exception as e:
        print(f"[CONNECTION ERROR] {e}")
        print("Make sure the FastAPI server is running on the expected port.")

async def handle_event(data):
    """Handle individual event types for immediate display."""
    event_type = data.get('type')
    
    if event_type == 'function_call':
        print(f"[FUNC CALL] {data['function_name']}")
        print(f"   Arguments: {data['arguments']}")
        sys.stdout.flush()
        
    elif event_type == 'function_result':
        print(f"[FUNC RESULT] {data['function_name']}")
        result_preview = str(data['result'])[:100] + "..." if len(str(data['result'])) > 100 else str(data['result'])
        print(f"   Result: {result_preview}")
        sys.stdout.flush()
        
    elif event_type == 'intermediate':
        print(f"[INTERMEDIATE] {data['content']}")
        sys.stdout.flush()
        
    elif event_type == 'thread_info':
        print(f"[THREAD INFO] Thread ID: {data['thread_id']}")
        sys.stdout.flush()
        
    elif event_type == 'error':
        print(f"[ERROR] {data['error']}")
        sys.stdout.flush()

if __name__ == "__main__":
    print("Testing Shadow FastAPI Streaming Events - Optimized")
    print("=" * 55)
    print("This version shows events in real-time as they happen\n")
    sys.stdout.flush()
    
    asyncio.run(test_streaming_events())
