#!/usr/bin/env python3
"""Phase 1 Spike - 01_hello.py: Agent Lifecycle.

Verifies Agent(LocalAgentConfig(...)) startup, session creation, and clean teardown.
"""

import asyncio
import os
import sys
import google.antigravity as agy

async def main():
    print("Testing Agent Lifecycle with google-antigravity...")
    # Use dummy api_key for localharness startup validation if none provided
    api_key = os.environ.get("GEMINI_API_KEY", "dummy-spike-key")
    config = agy.LocalAgentConfig(
        api_key=api_key,
        system_instructions="You are a helpful assistant.",
    )
    
    async with agy.Agent(config) as agent:
        print(f"Agent started successfully: is_started={agent.is_started}")
        assert agent.is_started is True, "Expected agent.is_started to be True"
        print(f"Initial conversation_id: {agent.conversation_id}")
    
    print("Agent cleanly exited context manager.")
    print("01_hello: PASSED")

if __name__ == "__main__":
    asyncio.run(main())
