#!/usr/bin/env python3
"""Phase 1 Spike - 02_streaming.py: Streaming reasoning and token responses.

Verifies:
1. Response cursor properties: `response.thoughts`, `response.chunks`, and direct iteration (`response`).
2. Concurrent consumption of reasoning and token streams without blocking.
3. Stream chunk types: Thought (step_index, text, signature) and Text (step_index, text).
"""

import asyncio
import os
import unittest
from unittest import mock
import google.antigravity as agy
from google.antigravity.proto import localharness_pb2
from google.antigravity.connections.local.test_utils import TestLocalHarness

from google.antigravity.conversation.conversation import Conversation

async def test_streaming_with_simulated_harness():
    print("Testing streaming with simulated harness...")
    tc = unittest.TestCase()
    proc = mock.MagicMock()
    harness = TestLocalHarness(tc, proc)
    
    # Create conversation wrapping this connection
    conv = Conversation(harness.conn)
    
    # Trigger a chat call in background task
    chat_task = asyncio.create_task(conv.chat("Explain quantum mechanics"))
    
    # Wait for the chat request to be sent to harness
    chat_req = await harness.wait_for_response()
    assert "userInput" in chat_req or "user_message" in chat_req, f"Expected userInput, got: {chat_req}"
    
    # Simulate streaming events from the Go harness:
    # 1. Thought delta
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="traj-1",
            step_index=1,
            source=localharness_pb2.StepUpdate.Source.SOURCE_MODEL,
            target=localharness_pb2.StepUpdate.Target.TARGET_USER,
            state=localharness_pb2.StepUpdate.State.STATE_ACTIVE,
            thinking_delta="Reasoning about the problem...",
        )
    ))
    
    # 2. Text delta
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="traj-1",
            step_index=2,
            source=localharness_pb2.StepUpdate.Source.SOURCE_MODEL,
            target=localharness_pb2.StepUpdate.Target.TARGET_USER,
            state=localharness_pb2.StepUpdate.State.STATE_ACTIVE,
            text_delta="Quantum mechanics is the study of matter and light.",
        )
    ))
    
    # 3. Mark done
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="traj-1",
            step_index=2,
            state=localharness_pb2.StepUpdate.STATE_DONE,
        ),
        trajectory_state_update=localharness_pb2.TrajectoryStateUpdate(
            trajectory_id="traj-1",
            state=localharness_pb2.TrajectoryStateUpdate.State.STATE_FULLY_IDLE,
        )
    ))
    
    response = await chat_task
    assert isinstance(response, agy.types.ChatResponse), f"Unexpected response type: {type(response)}"
    
    # Consume thoughts and tokens concurrently
    thoughts = []
    tokens = []
    
    async def collect_thoughts():
        async for t in response.thoughts:
            thoughts.append(t)
    
    async def collect_tokens():
        async for tok in response:
            tokens.append(tok)
            
    await asyncio.gather(collect_thoughts(), collect_tokens())
    
    print(f"Collected {len(thoughts)} thoughts: {thoughts}")
    print(f"Collected {len(tokens)} tokens: {tokens}")
    assert len(thoughts) == 1, f"Expected 1 thought, got {len(thoughts)}"
    assert len(tokens) == 1, f"Expected 1 token chunk, got {len(tokens)}"
    assert thoughts[0] == "Reasoning about the problem..."
    assert "Quantum mechanics" in tokens[0]
    
    # Test chunks cursor
    chunks = []
    async for c in response.chunks:
        chunks.append(c)
    print(f"Collected {len(chunks)} raw semantic chunks: {[type(c).__name__ for c in chunks]}")
    assert len(chunks) == 2
    assert isinstance(chunks[0], agy.types.Thought)
    assert isinstance(chunks[1], agy.types.Text)
    
    await harness.disconnect_sdk()
    print("02_streaming: PASSED")

if __name__ == "__main__":
    asyncio.run(test_streaming_with_simulated_harness())
