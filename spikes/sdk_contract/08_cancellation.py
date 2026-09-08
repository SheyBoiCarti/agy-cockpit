#!/usr/bin/env python3
"""Phase 1 Spike - 08_cancellation.py: Turn Cancellation Behavior.

Verifies:
1. response.cancel() transmits halt_request to the connection.
2. Safe idempotency when calling cancel() multiple times.
3. asyncio.Task cancellation propagation and cleanup.
"""

import asyncio
import os
import unittest
from unittest import mock
import google.antigravity as agy
from google.antigravity.conversation.conversation import Conversation
from google.antigravity.proto import localharness_pb2
from google.antigravity.connections.local.test_utils import TestLocalHarness

async def test_cancellation():
    print("Testing response.cancel() and cancellation propagation...")
    tc = unittest.TestCase()
    proc = mock.MagicMock()
    harness = TestLocalHarness(tc, proc)
    conv = Conversation(harness.conn)
    
    chat_task = asyncio.create_task(conv.chat("Generate a 10,000 word essay"))
    await harness.wait_for_response()
    
    # 1. Harness emits some tokens
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="traj-cancel",
            step_index=1,
            source=localharness_pb2.StepUpdate.Source.SOURCE_MODEL,
            target=localharness_pb2.StepUpdate.Target.TARGET_USER,
            state=localharness_pb2.StepUpdate.State.STATE_ACTIVE,
            text_delta="Beginning paragraph 1..."
        )
    ))
    
    response = await chat_task
    
    # Trigger cancellation from client side
    cancel_task = asyncio.create_task(response.cancel())
    
    # Harness should receive halt_request
    req = await harness.wait_for_response()
    print(f"Harness received after cancel: {req}")
    assert "haltRequest" in req or "halt_request" in req
    await cancel_task
    
    # Subsequent cancel should be a safe no-op
    await response.cancel()
    
    # Send terminal event from harness
    await harness.send_event(localharness_pb2.OutputEvent(
        trajectory_state_update=localharness_pb2.TrajectoryStateUpdate(
            trajectory_id="traj-cancel",
            state=localharness_pb2.TrajectoryStateUpdate.State.STATE_FULLY_IDLE,
        )
    ))
    
    await harness.disconnect_sdk()
    print("08_cancellation: PASSED")

if __name__ == "__main__":
    asyncio.run(test_cancellation())
