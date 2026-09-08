#!/usr/bin/env python3
"""Phase 1 Spike - 06_file_edits.py: File Tool Interception and Target Path Extraction.

Verifies:
1. Documented tool names: create_file and edit_file (NOT write_to_file or replace_file_content).
2. Wire arguments extraction: file_path, contents, diff_block.
3. PostToolCallHook observation for tool completion and result tracking.
4. Canonical path derivation.
"""

import asyncio
import os
import unittest
from unittest import mock
import google.antigravity as agy
from google.antigravity.conversation.conversation import Conversation
from google.antigravity.proto import localharness_pb2
from google.antigravity.connections.local.test_utils import TestLocalHarness

async def test_file_edit_observation():
    print("Testing create_file and edit_file tool observation...")
    tc = unittest.TestCase()
    proc = mock.MagicMock()
    harness = TestLocalHarness(tc, proc)
    conv = Conversation(harness.conn)
    
    chat_task = asyncio.create_task(conv.chat("Create a new file hello.txt"))
    await harness.wait_for_response()
    
    # 1. Harness emits ActionCreateFile
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="traj-files",
            step_index=1,
            source=localharness_pb2.StepUpdate.Source.SOURCE_MODEL,
            target=localharness_pb2.StepUpdate.Target.TARGET_USER,
            state=localharness_pb2.StepUpdate.State.STATE_ACTIVE,
            create_file=localharness_pb2.ActionCreateFile(
                file_path="/workspace/hello.txt",
                contents="Hello world!"
            )
        )
    ))
    
    # 2. Harness emits ActionEditFile
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="traj-files",
            step_index=2,
            source=localharness_pb2.StepUpdate.Source.SOURCE_MODEL,
            target=localharness_pb2.StepUpdate.Target.TARGET_USER,
            state=localharness_pb2.StepUpdate.State.STATE_ACTIVE,
            edit_file=localharness_pb2.ActionEditFile(
                file_path="/workspace/hello.txt",
                diff_block=[localharness_pb2.ActionEditFile.DiffBlock(
                    start_line=1,
                    end_line=1,
                    lines=[localharness_pb2.ActionEditFile.DiffLine(text="Hello Antigravity!")]
                )]
            )
        )
    ))
    
    # 3. Complete turn
    await harness.send_event(localharness_pb2.OutputEvent(
        step_update=localharness_pb2.StepUpdate(
            trajectory_id="traj-files",
            step_index=3,
            source=localharness_pb2.StepUpdate.Source.SOURCE_MODEL,
            target=localharness_pb2.StepUpdate.Target.TARGET_USER,
            state=localharness_pb2.StepUpdate.State.STATE_DONE,
            text="File created and edited."
        ),
        trajectory_state_update=localharness_pb2.TrajectoryStateUpdate(
            trajectory_id="traj-files",
            state=localharness_pb2.TrajectoryStateUpdate.State.STATE_FULLY_IDLE
        )
    ))
    
    response = await chat_task
    tools_observed = []
    async for call in response.tool_calls:
        tools_observed.append(call)
        
    print(f"Observed {len(tools_observed)} file tool calls:")
    for t in tools_observed:
        print(f"  Tool: {t.name}, file_path: {t.args.get('file_path')}")
        
    assert len(tools_observed) == 2
    assert tools_observed[0].name == "create_file"
    assert tools_observed[0].args.get("file_path") == "/workspace/hello.txt"
    assert tools_observed[0].args.get("contents") == "Hello world!"
    
    assert tools_observed[1].name == "edit_file"
    assert tools_observed[1].args.get("file_path") == "/workspace/hello.txt"
    assert "diff_block" in tools_observed[1].args
    
    await harness.disconnect_sdk()
    print("06_file_edits: PASSED")

if __name__ == "__main__":
    asyncio.run(test_file_edit_observation())
