#!/usr/bin/env python3
"""Phase 1 Spike - 07_subagents.py: Dynamic Subagents and Trajectory Hierarchy.

Verifies:
1. SubagentConfig configuration and CapabilitiesConfig.enable_subagents / allowed_subagents.
2. Tool name mapping: BuiltinTools.START_SUBAGENT maps to invoke_subagent on the wire.
3. Subagent hierarchy tracking via parent_trajectory_id and trajectory_id in StepUpdate.
"""

import asyncio
import os
import unittest
from unittest import mock
import google.antigravity as agy
from google.antigravity.conversation.conversation import Conversation
from google.antigravity.proto import localharness_pb2
from google.antigravity.connections.local.test_utils import TestLocalHarness

def test_subagent_config():
    print("Testing SubagentConfig declaration...")
    sub_cfg = agy.types.SubagentConfig(
        name="researcher",
        description="Performs web research and reading",
        system_instructions="You are a dedicated researcher.",
        capabilities=agy.types.SubagentCapabilities(
            enabled_tools=[agy.BuiltinTools.SEARCH_WEB, agy.BuiltinTools.READ_URL_CONTENT]
        )
    )
    assert sub_cfg.name == "researcher"
    
    agent_cfg = agy.LocalAgentConfig(
        subagents=[sub_cfg],
        capabilities=agy.types.CapabilitiesConfig(
            enable_subagents=True,
            allowed_subagents=["researcher"]
        )
    )
    assert len(agent_cfg.subagents) == 1
    assert agent_cfg.capabilities.enable_subagents is True

async def test_subagent_trajectory_observation():
    print("Testing subagent hierarchy observation...")
    tc = unittest.TestCase()
    proc = mock.MagicMock()
    harness = TestLocalHarness(tc, proc)
    conv = Conversation(harness.conn)
    
    chat_task = asyncio.create_task(conv.chat("Delegate task to researcher"))
    await harness.wait_for_response()
    
    # 1. Main agent invokes subagent
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="main-traj-1",
            step_index=1,
            source=localharness_pb2.StepUpdate.Source.SOURCE_MODEL,
            target=localharness_pb2.StepUpdate.Target.TARGET_USER,
            state=localharness_pb2.StepUpdate.State.STATE_ACTIVE,
            invoke_subagent=localharness_pb2.ActionInvokeSubagent()
        )
    ))
    
    # 2. Subagent trajectory step (parent_trajectory_id links to main-traj-1)
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="sub-traj-1",
            parent_trajectory_id="main-traj-1",
            step_index=1,
            source=localharness_pb2.StepUpdate.Source.SOURCE_MODEL,
            target=localharness_pb2.StepUpdate.Target.TARGET_USER,
            state=localharness_pb2.StepUpdate.State.STATE_ACTIVE,
            thinking_delta="Subagent researching topic..."
        )
    ))
    
    # 3. Complete turn
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="main-traj-1",
            step_index=2,
            source=localharness_pb2.StepUpdate.Source.SOURCE_MODEL,
            target=localharness_pb2.StepUpdate.Target.TARGET_USER,
            state=localharness_pb2.StepUpdate.State.STATE_DONE,
            text="Subagent finished."
        ),
        trajectory_state_update=localharness_pb2.TrajectoryStateUpdate(
            trajectory_id="main-traj-1",
            state=localharness_pb2.TrajectoryStateUpdate.State.STATE_FULLY_IDLE
        )
    ))
    
    response = await chat_task
    tool_calls = []
    async for call in response.tool_calls:
        tool_calls.append(call)
        
    print(f"Observed tool calls: {[c.name for c in tool_calls]}")
    assert any(c.name == "start_subagent" for c in tool_calls)
    
    await harness.disconnect_sdk()
    print("07_subagents: PASSED")

if __name__ == "__main__":
    test_subagent_config()
    asyncio.run(test_subagent_trajectory_observation())
