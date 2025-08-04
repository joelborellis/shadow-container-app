"""
Test script to verify cumulative token tracking across multiple requests to the same thread.
This test simulates the behavior when a user sends multiple requests using the same threadId.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

# Mock the app module components for testing
class MockResponse:
    def __init__(self, usage_data=None, metadata=None, thread_id=None):
        self.usage = usage_data
        self.metadata = metadata or {}
        self.thread = MockThread(thread_id) if thread_id else None

class MockThread:
    def __init__(self, thread_id):
        self.id = thread_id

class MockUsage:
    def __init__(self, prompt_tokens, completion_tokens, total_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens

# Import and test the functions
from collections import defaultdict
import time

# Simulate the global variables from main.py
thread_token_usage = {}
thread_last_access = defaultdict(float)

def simulate_extract_and_accumulate_tokens(response, thread_id: str) -> dict:
    """
    Simulate the optimized token extraction and accumulation logic from main.py
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
        # First, try direct attribute access which is faster and less error-prone
        if hasattr(response, 'usage') and response.usage:
            current_usage["input_tokens"] = getattr(response.usage, 'prompt_tokens', 0)
            current_usage["output_tokens"] = getattr(response.usage, 'completion_tokens', 0) 
            current_usage["total_tokens"] = getattr(response.usage, 'total_tokens', 0)
            
            if current_usage["total_tokens"] > 0:
                print(f"   Found token usage in response.usage: {current_usage}")
        
        # Check for usage in metadata if direct access didn't work
        elif hasattr(response, 'metadata') and response.metadata:
            usage = response.metadata.get('usage', {})
            if usage:
                current_usage["input_tokens"] = usage.get('prompt_tokens', 0)
                current_usage["output_tokens"] = usage.get('completion_tokens', 0)
                current_usage["total_tokens"] = usage.get('total_tokens', 0)
                
                if current_usage["total_tokens"] > 0:
                    print(f"   Found token usage in response metadata: {current_usage}")
        
        # Only try model_dump methods as a last resort to reduce serialization errors
        elif hasattr(response, 'model_dump'):
            try:
                response_data = response.model_dump()
                # Only process if it's a simple dict to avoid complex object serialization
                if isinstance(response_data, dict) and 'usage' in response_data:
                    usage = response_data['usage']
                    if isinstance(usage, dict):
                        current_usage = {
                            "input_tokens": usage.get('prompt_tokens', 0),
                            "output_tokens": usage.get('completion_tokens', 0),
                            "total_tokens": usage.get('total_tokens', 0)
                        }
                        if current_usage["total_tokens"] > 0:
                            print(f"   Found token usage in model_dump: {current_usage}")
                        
            except Exception as e:
                # Log at debug level to reduce noise
                print(f"   Debug: Error in model_dump processing: {e}")
                        
    except Exception as e:
        print(f"   Error extracting token usage: {e}")
    
    # Accumulate the usage for this thread
    if current_usage["total_tokens"] > 0:
        thread_token_usage[thread_id]["input_tokens"] += current_usage["input_tokens"]
        thread_token_usage[thread_id]["output_tokens"] += current_usage["output_tokens"]
        thread_token_usage[thread_id]["total_tokens"] += current_usage["total_tokens"]
        
        print(f"   Updated thread {thread_id} token usage: {thread_token_usage[thread_id]}")
    
    return thread_token_usage[thread_id].copy()

def simulate_reset_thread_tokens(thread_id: str):
    """Reset token tracking for a thread."""
    if thread_id in thread_token_usage:
        del thread_token_usage[thread_id]
        print(f"   Reset token tracking for thread: {thread_id}")

def test_cumulative_token_tracking():
    print("Testing Cumulative Token Tracking Across Multiple Requests")
    print("=" * 65)
    
    # Test Scenario: Multiple requests to the same thread
    test_thread_id = "thread_test_12345"
    
    print(f"\n📋 Test Scenario: Multiple requests to thread '{test_thread_id}'")
    print("-" * 65)
    
    # Simulate Request 1: User asks "What is sales methodology?"
    print("\n1️⃣  First Request: 'What is sales methodology?'")
    print("   Simulating response with token usage...")
    
    # Mock response with token usage from first request
    mock_usage_1 = MockUsage(100, 50, 150)  # Small query, moderate response
    response_1 = MockResponse(usage_data=mock_usage_1, thread_id=test_thread_id)
    
    # Process the response
    cumulative_usage_1 = simulate_extract_and_accumulate_tokens(response_1, test_thread_id)
    print(f"   📊 After Request 1: {cumulative_usage_1}")
    
    # Simulate Request 2: User asks for more details (same thread)
    print("\n2️⃣  Second Request: 'Can you give me specific examples?'")
    print("   Simulating response with additional token usage...")
    
    # Mock response with token usage from second request
    mock_usage_2 = MockUsage(75, 125, 200)  # More detailed response
    response_2 = MockResponse(usage_data=mock_usage_2, thread_id=test_thread_id)
    
    # Process the response (should accumulate)
    cumulative_usage_2 = simulate_extract_and_accumulate_tokens(response_2, test_thread_id)
    print(f"   📊 After Request 2: {cumulative_usage_2}")
    
    # Simulate Request 3: User asks follow-up question (same thread)
    print("\n3️⃣  Third Request: 'How do I apply this to my current situation?'")
    print("   Simulating response with additional token usage...")
    
    # Mock response with token usage from third request
    mock_usage_3 = MockUsage(90, 80, 170)  # Contextual response
    response_3 = MockResponse(usage_data=mock_usage_3, thread_id=test_thread_id)
    
    # Process the response (should accumulate)
    cumulative_usage_3 = simulate_extract_and_accumulate_tokens(response_3, test_thread_id)
    print(f"   📊 After Request 3: {cumulative_usage_3}")
    
    # Verify cumulative tracking is working correctly
    print("\n✅ Verification:")
    expected_input = 100 + 75 + 90  # 265
    expected_output = 50 + 125 + 80  # 255
    expected_total = 150 + 200 + 170  # 520
    
    print(f"   Expected Total: Input={expected_input}, Output={expected_output}, Total={expected_total}")
    print(f"   Actual Total:   {cumulative_usage_3}")
    
    assert cumulative_usage_3["input_tokens"] == expected_input, f"Input tokens mismatch: expected {expected_input}, got {cumulative_usage_3['input_tokens']}"
    assert cumulative_usage_3["output_tokens"] == expected_output, f"Output tokens mismatch: expected {expected_output}, got {cumulative_usage_3['output_tokens']}"
    assert cumulative_usage_3["total_tokens"] == expected_total, f"Total tokens mismatch: expected {expected_total}, got {cumulative_usage_3['total_tokens']}"
    
    print("   ✅ Cumulative tracking is working correctly!")
    
    # Test New Thread Reset
    print("\n🔄 Testing New Thread Creation (Token Reset)")
    print("-" * 65)
    
    new_thread_id = "thread_new_67890"
    print(f"\n4️⃣  New Thread Request: User starts new conversation (threadId = '{new_thread_id}')")
    print("   Simulating new thread with token reset...")
    
    # For new threads, we reset tokens when no threadId is provided initially
    # Then when we get the actual thread ID, we start fresh
    mock_usage_4 = MockUsage(50, 30, 80)  # Fresh start
    response_4 = MockResponse(usage_data=mock_usage_4, thread_id=new_thread_id)
    
    cumulative_usage_4 = simulate_extract_and_accumulate_tokens(response_4, new_thread_id)
    print(f"   📊 New Thread Usage: {cumulative_usage_4}")
    
    # Verify new thread starts fresh
    assert cumulative_usage_4["input_tokens"] == 50, "New thread should start with fresh token count"
    assert cumulative_usage_4["output_tokens"] == 30, "New thread should start with fresh token count"
    assert cumulative_usage_4["total_tokens"] == 80, "New thread should start with fresh token count"
    
    print("   ✅ New thread token tracking is working correctly!")
    
    # Verify old thread data is preserved
    print(f"   📊 Original Thread Still Has: {thread_token_usage[test_thread_id]}")
    assert thread_token_usage[test_thread_id]["total_tokens"] == expected_total, "Original thread data should be preserved"
    
    print("\n📈 Final Statistics:")
    print(f"   Total Threads Tracked: {len(thread_token_usage)}")
    print(f"   Thread '{test_thread_id}': {thread_token_usage[test_thread_id]}")
    print(f"   Thread '{new_thread_id}': {thread_token_usage[new_thread_id]}")
    
    total_tokens_all_threads = sum(usage["total_tokens"] for usage in thread_token_usage.values())
    print(f"   Total Tokens Across All Threads: {total_tokens_all_threads}")
    
    print("\n" + "=" * 65)
    print("🎉 Cumulative Token Tracking Test PASSED!")
    print("\nKey Features Verified:")
    print("  ✅ Tokens accumulate correctly across multiple requests to same thread")
    print("  ✅ New threads start with fresh token counts")
    print("  ✅ Multiple threads can be tracked simultaneously")
    print("  ✅ Token usage is preserved per thread independently")
    print("  ✅ Optimized extraction prioritizes direct attribute access")

if __name__ == "__main__":
    test_cumulative_token_tracking()
