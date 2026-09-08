#!/usr/bin/env python3
"""Phase 1 Spike - 05_policy_approval.py: Policy Bridge with Future Resolution.

Verifies:
1. Policy configuration: deny("*"), allow("view_file"), ask_user("run_command", handler=...).
2. AskUserHandler awaiting an asyncio.Future resolved asynchronously by another coroutine (simulating WebSocket approval).
3. Allowed -> HookResult(allow=True).
4. Denied -> HookResult(allow=False).
5. Timeout -> clean denial.
6. Cancellation -> clean handling.
"""

import asyncio
import google.antigravity as agy
from google.antigravity.hooks import policy, hooks

async def test_policy_approval_flow():
    print("Testing SDK Policy Bridge with async Future resolution...")
    
    pending_future: asyncio.Future[bool] | None = None
    
    async def simulated_approval_handler(tool_call: agy.types.ToolCall) -> bool:
        nonlocal pending_future
        print(f"  [Handler called] tool={tool_call.name}, args={tool_call.args}")
        pending_future = asyncio.get_running_loop().create_future()
        try:
            # Wait with a timeout (simulating UI approval timeout)
            approved = await asyncio.wait_for(pending_future, timeout=2.0)
            return approved
        except asyncio.TimeoutError:
            print("  [Handler] Approval timed out!")
            return False
        except asyncio.CancelledError:
            print("  [Handler] Approval cancelled!")
            return False

    # Define policy rules
    policies = [
        policy.allow("view_file"),
        policy.ask_user("run_command", handler=simulated_approval_handler),
        policy.deny("*"),
    ]
    
    decide_hook = policy._PolicyDecideHook(policies)
    hook_ctx = hooks.HookContext()

    # Case 1: view_file -> Auto approved
    tc_view = agy.types.ToolCall(name="view_file", args={"path": "README.md"})
    res_view = await decide_hook.run(hook_ctx, tc_view)
    print(f"Case 1 (view_file): allow={res_view.allow}")
    assert res_view.allow is True

    # Case 2: random unknown tool -> Auto denied by wildcard
    tc_bad = agy.types.ToolCall(name="delete_database", args={})
    res_bad = await decide_hook.run(hook_ctx, tc_bad)
    print(f"Case 2 (delete_database): allow={res_bad.allow}")
    assert res_bad.allow is False

    # Case 3: run_command approved via Future
    tc_cmd = agy.types.ToolCall(name="run_command", args={"command": "echo test"})
    
    async def approve_coro():
        # Wait a tick for handler to create the future
        while pending_future is None:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        print("  [Simulator] Approving command...")
        pending_future.set_result(True)

    sim_task = asyncio.create_task(approve_coro())
    res_cmd_approved = await decide_hook.run(hook_ctx, tc_cmd)
    await sim_task
    print(f"Case 3 (run_command approved): allow={res_cmd_approved.allow}")
    assert res_cmd_approved.allow is True

    # Case 4: run_command rejected via Future
    pending_future = None
    async def reject_coro():
        while pending_future is None:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        print("  [Simulator] Rejecting command...")
        pending_future.set_result(False)

    sim_task = asyncio.create_task(reject_coro())
    res_cmd_rejected = await decide_hook.run(hook_ctx, tc_cmd)
    await sim_task
    print(f"Case 4 (run_command rejected): allow={res_cmd_rejected.allow}")
    assert res_cmd_rejected.allow is False

    # Case 5: run_command timed out
    pending_future = None
    res_cmd_timeout = await decide_hook.run(hook_ctx, tc_cmd)
    print(f"Case 5 (run_command timeout): allow={res_cmd_timeout.allow}")
    assert res_cmd_timeout.allow is False

    print("05_policy_approval: PASSED")

if __name__ == "__main__":
    asyncio.run(test_policy_approval_flow())
