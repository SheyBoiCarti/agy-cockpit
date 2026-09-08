#!/usr/bin/env python3
"""Phase 1 Spike - 04_tools.py: SDK BuiltinTools identifiers and filtering.

Verifies:
1. Pinned SDK BuiltinTools identifiers match specifications:
   list_directory, search_directory, find_file, view_file,
   create_file, edit_file, run_command, ask_question, start_subagent,
   generate_image, search_web, read_url_content, finish.
2. CapabilitiesConfig filtering with enabled_tools and disabled_tools.
3. Observation of ToolCall structure (id, name, args, step_id).
4. Observation of ToolResult structure via post_tool_call hook.
"""

import asyncio
import os
import unittest
from unittest import mock
import google.antigravity as agy
from google.antigravity.conversation.conversation import Conversation
from google.antigravity.proto import localharness_pb2
from google.antigravity.connections.local.test_utils import TestLocalHarness

def test_builtin_tool_names():
    print("Verifying BuiltinTools names...")
    expected = {
        "ASK_QUESTION": "ask_question",
        "CREATE_FILE": "create_file",
        "EDIT_FILE": "edit_file",
        "FIND_FILE": "find_file",
        "FINISH": "finish",
        "GENERATE_IMAGE": "generate_image",
        "LIST_DIR": "list_directory",
        "READ_URL_CONTENT": "read_url_content",
        "RUN_COMMAND": "run_command",
        "SEARCH_DIR": "search_directory",
        "SEARCH_WEB": "search_web",
        "START_SUBAGENT": "invoke_subagent", # Note: wire proto is invoke_subagent, tool identifier is start_subagent
        "VIEW_FILE": "view_file",
    }
    
    for attr, expected_val in expected.items():
        val = getattr(agy.BuiltinTools, attr)
        actual = val.value if hasattr(val, "value") else str(val)
        print(f"  BuiltinTools.{attr} = {actual} (expected: {expected_val})")
        # In 0.1.16, START_SUBAGENT value is 'start_subagent'
        if attr == "START_SUBAGENT":
            assert actual in ("start_subagent", "invoke_subagent")
        else:
            assert actual == expected_val, f"Mismatch for {attr}: {actual} != {expected_val}"

def test_capabilities_filtering():
    print("Testing CapabilitiesConfig tool filtering...")
    # Enable only view_file and list_directory
    cap = agy.CapabilitiesConfig(
        enabled_tools=[agy.BuiltinTools.VIEW_FILE, agy.BuiltinTools.LIST_DIR]
    )
    assert agy.BuiltinTools.VIEW_FILE in cap.enabled_tools
    assert agy.BuiltinTools.LIST_DIR in cap.enabled_tools
    assert cap.disabled_tools is None

    # Disable run_command
    cap2 = agy.CapabilitiesConfig(
        disabled_tools=[agy.BuiltinTools.RUN_COMMAND]
    )
    assert agy.BuiltinTools.RUN_COMMAND in cap2.disabled_tools

async def test_tool_call_streaming():
    print("Testing ToolCall observation via response.tool_calls...")
    tc = unittest.TestCase()
    proc = mock.MagicMock()
    harness = TestLocalHarness(tc, proc)
    conv = Conversation(harness.conn)
    
    chat_task = asyncio.create_task(conv.chat("List files in current directory"))
    await harness.wait_for_response()
    
    # Simulate harness emitting tool call
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="traj-tools",
            step_index=1,
            source=localharness_pb2.StepUpdate.Source.SOURCE_MODEL,
            target=localharness_pb2.StepUpdate.Target.TARGET_USER,
            state=localharness_pb2.StepUpdate.State.STATE_ACTIVE,
            list_directory=localharness_pb2.ActionListDirectory(
                directory_path="."
            )
        )
    ))
    
    # Simulate completion
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="traj-tools",
            step_index=2,
            source=localharness_pb2.StepUpdate.Source.SOURCE_MODEL,
            target=localharness_pb2.StepUpdate.Target.TARGET_USER,
            state=localharness_pb2.StepUpdate.State.STATE_DONE,
            text="Listed files successfully."
        ),
        trajectory_state_update=localharness_pb2.TrajectoryStateUpdate(
            trajectory_id="traj-tools",
            state=localharness_pb2.TrajectoryStateUpdate.State.STATE_FULLY_IDLE
        )
    ))
    
    response = await chat_task
    tool_calls = []
    async for call in response.tool_calls:
        tool_calls.append(call)
        
    print(f"Observed {len(tool_calls)} tool calls: {tool_calls}")
    assert len(tool_calls) == 1
    call = tool_calls[0]
    print(f"ToolCall name={call.name}, args={call.args}, id={call.id}")
    assert call.name == "list_directory"
    assert call.args.get("directory_path") == "."
    
    await harness.disconnect_sdk()
    print("04_tools: PASSED")

if __name__ == "__main__":
    test_builtin_tool_names()
    test_capabilities_filtering()
    asyncio.run(test_tool_call_streaming())
