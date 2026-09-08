"""Council Member implementation representing an active Gemini agent."""

import asyncio
import json
import logging
import os
import shutil
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from agy_cockpit.council.personas import CouncilPersona, RESET, BOLD

logger = logging.getLogger(__name__)


class CouncilMember:
    """An autonomous Gemini agent serving as a member of the AI Council."""

    def __init__(
        self,
        persona: CouncilPersona,
        model_slug: str = "gemini-3.8-flash-high",
        conversation_id: Optional[str] = None,
        workspace_path: Optional[str] = None,
        agy_path: Optional[str] = None,
    ):
        self.persona = persona
        self.model_slug = model_slug
        self.conversation_id = conversation_id or str(uuid.uuid4())
        self.workspace_path = workspace_path or os.getcwd()
        self.agy_path = agy_path or shutil.which("agy") or "agy"
        self.history: List[Dict[str, str]] = []
        self._initialized = False

    @property
    def id(self) -> str:
        return self.persona.id

    @property
    def name(self) -> str:
        return self.persona.short_name

    @property
    def title(self) -> str:
        return self.persona.title

    async def chat(
        self,
        prompt: str,
        on_token: Optional[Callable[[str], Any]] = None,
        on_thought: Optional[Callable[[str], Any]] = None,
        cancellation_token: Optional[asyncio.Event] = None,
    ) -> str:
        """Sends a prompt to this council member and streams the response."""
        # Include persona context if this is the first turn
        system_context = ""
        if not self._initialized:
            system_context = (
                f"[SYSTEM DIRECTIVE / ROLE SPECIFICATION]\n"
                f"{self.persona.system_prompt}\n"
                f"You are speaking as {self.persona.title} ({self.persona.short_name}). "
                f"Stay strictly in character and apply your specialized evaluation criteria.\n\n"
            )
            self._initialized = True

        full_prompt = f"{system_context}{prompt}"
        self.history.append({"role": "user", "content": prompt})

        # Check if running in mock/testing mode
        if os.environ.get("COUNCIL_TEST_MODE") == "1" or not shutil.which(self.agy_path):
            mock_response = (
                f"[{self.persona.short_name} Perspective]: Analyzing '{prompt[:40]}...' "
                f"From my stance as {self.persona.title}, we must prioritize quality, robustness, and clarity."
            )
            if on_thought:
                res = on_thought(f"Analyzing prompt from {self.persona.title} perspective...")
                if asyncio.iscoroutine(res):
                    await res
            for word in mock_response.split(" "):
                token = word + " "
                if on_token:
                    res = on_token(token)
                    if asyncio.iscoroutine(res):
                        await res
                await asyncio.sleep(0.01)
            self.history.append({"role": "assistant", "content": mock_response})
            return mock_response

        # Execute via agy CLI using active user session
        cmd = [
            self.agy_path,
            "--conversation", self.conversation_id,
            "--print", full_prompt,
            "--output-format", "stream-json",
            "--add-dir", self.workspace_path,
        ]
        if self.model_slug:
            cmd.extend(["--model", self.model_slug])

        accumulated_tokens: List[str] = []
        accumulated_thoughts: List[str] = []

        try:
            if on_thought:
                res = on_thought(f"Deliberating as {self.persona.title}...\n")
                if asyncio.iscoroutine(res):
                    await res

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace_path,
            )

            async def watch_cancel():
                if cancellation_token:
                    await cancellation_token.wait()
                    if proc and proc.returncode is None:
                        try:
                            proc.terminate()
                        except Exception:
                            pass

            cancel_task = asyncio.create_task(watch_cancel())

            try:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue
                    try:
                        data = json.loads(line_str)
                    except Exception:
                        continue

                    event_name = data.get("event") or data.get("type")
                    if event_name == "step_update":
                        step = data.get("step_update", {})
                        delta_obj = data.get("delta") or step.get("delta") or {}
                        
                        # Thinking stream
                        thinking = delta_obj.get("thinking") or step.get("thinking")
                        if thinking:
                            accumulated_thoughts.append(thinking)
                            if on_thought:
                                res = on_thought(thinking)
                                if asyncio.iscoroutine(res):
                                    await res

                        # Token stream
                        chunk = step.get("text_delta") or delta_obj.get("text") or step.get("text")
                        if chunk:
                            if len(chunk) > 20 and " " in chunk:
                                # Stream words progressively for smooth readability
                                words = chunk.split(" ")
                                for i, w in enumerate(words):
                                    piece = w + (" " if i < len(words) - 1 else "")
                                    accumulated_tokens.append(piece)
                                    if on_token:
                                        res = on_token(piece)
                                        if asyncio.iscoroutine(res):
                                            await res
                                    await asyncio.sleep(0.012)
                            else:
                                accumulated_tokens.append(chunk)
                                if on_token:
                                    res = on_token(chunk)
                                    if asyncio.iscoroutine(res):
                                        await res

                    elif event_name == "result":
                        res_obj = data.get("result", {})
                        final = res_obj.get("response") or res_obj.get("text") or ""
                        if not accumulated_tokens and final:
                            accumulated_tokens.append(final)
                            if on_token:
                                res = on_token(final)
                                if asyncio.iscoroutine(res):
                                    await res

                await proc.wait()
            finally:
                cancel_task.cancel()

        except Exception as e:
            logger.exception("CouncilMember %s execution failed: %s", self.persona.short_name, e)
            error_msg = f"[Error from {self.persona.short_name}: {e}]"
            accumulated_tokens.append(error_msg)
            if on_token:
                res = on_token(error_msg)
                if asyncio.iscoroutine(res):
                    await res

        full_reply = "".join(accumulated_tokens).strip()
        self.history.append({"role": "assistant", "content": full_reply})
        return full_reply
