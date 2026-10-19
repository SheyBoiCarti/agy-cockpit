"""Council member execution with explicit failure and cancellation semantics."""
import asyncio
import inspect
import json
import os
import shutil
import uuid
from typing import Optional
from agy_cockpit.council.personas import CouncilPersona
from agy_cockpit.backend.services.process_utils import terminate_process_tree, spawn_owned_process


class CouncilExecutionError(RuntimeError):
    def __init__(self, member_id: str, reason: str):
        self.member_id = member_id
        super().__init__(f"Council member {member_id}: {reason}")


async def invoke(callback, *args):
    if callback:
        result = callback(*args)
        if inspect.isawaitable(result):
            return await result


class CouncilMember:
    def __init__(self, persona: CouncilPersona, model_slug="gemini-3.8-flash-high",
                 conversation_id: Optional[str] = None, workspace_path=None, agy_path=None,
                 member_timeout_seconds=120, runner=None):
        self.persona = persona
        self.model_slug = model_slug
        self.conversation_id = conversation_id or str(uuid.uuid4())
        self.workspace_path = workspace_path or os.getcwd()
        self.agy_path = agy_path or shutil.which("agy") or "agy"
        self.member_timeout_seconds = member_timeout_seconds
        self.runner = runner
        self.history = []
        self._initialized = False

    @property
    def id(self): return self.persona.id
    @property
    def name(self): return self.persona.short_name
    @property
    def title(self): return self.persona.title

    async def chat(self, prompt, on_token=None, on_thought=None, cancellation_token=None):
        cancel = cancellation_token or asyncio.Event()
        if cancel.is_set(): raise asyncio.CancelledError()
        full_prompt = prompt
        if not self._initialized:
            full_prompt = f"[SYSTEM DIRECTIVE / ROLE SPECIFICATION]\n{self.persona.system_prompt}\nYou are {self.title} ({self.name}).\n\n{prompt}"
        self.history.append({"role": "user", "content": prompt})
        async def execute():
            if self.runner:
                return await self.runner(self, full_prompt, on_token, on_thought, cancel)
            if os.environ.get("COUNCIL_TEST_MODE") == "1":
                vote = prompt.startswith("[COUNCIL ROLL-CALL VOTE]")
                text = "APPROVE Quality and isolation matter." if vote else f"[{self.name} Perspective]: Prioritize quality, robustness, and clarity."
                for token in text.split(' '):
                    if cancel.is_set(): raise asyncio.CancelledError()
                    await invoke(on_token, token + ' ')
                    await asyncio.sleep(.01)
                return text
            return await self._cli_chat(full_prompt, on_token, on_thought)
        task = asyncio.create_task(execute())
        cancelled = asyncio.create_task(cancel.wait())
        try:
            async with asyncio.timeout(self.member_timeout_seconds):
                done, _ = await asyncio.wait({task, cancelled}, return_when=asyncio.FIRST_COMPLETED)
                if cancelled in done or cancel.is_set(): raise asyncio.CancelledError()
                text = await task
                if not text or not text.strip(): raise CouncilExecutionError(self.id, "empty result")
                self._initialized = True
                self.history.append({"role": "assistant", "content": text})
                return text
        except TimeoutError as exc:
            raise CouncilExecutionError(self.id, "timed out") from exc
        finally:
            task.cancel(); cancelled.cancel()
            await asyncio.gather(task, cancelled, return_exceptions=True)

    async def _cli_chat(self, prompt, on_token, on_thought):
        if not shutil.which(self.agy_path):
            raise CouncilExecutionError(self.id, "Antigravity CLI is missing")
        cmd = [self.agy_path, "--conversation", self.conversation_id, "--print", prompt,
               "--output-format", "stream-json", "--add-dir", self.workspace_path, "--model", self.model_slug]
        proc = await spawn_owned_process(*cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=self.workspace_path, **({"start_new_session": True} if os.name != 'nt' else {}))
        async def drain_stderr():
            tail = b''
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk: return tail
                tail = (tail + chunk)[-32768:]
        stderr_task = asyncio.create_task(drain_stderr())
        tokens = []
        try:
            async for line in proc.stdout:
                try: data = json.loads(line.decode('utf-8', errors='replace'))
                except (ValueError, UnicodeError): continue
                event = data.get('event') or data.get('type')
                if event == 'step_update':
                    step = data.get('step_update') or {}
                    delta = data.get('delta') or step.get('delta') or {}
                    await invoke(on_thought, delta.get('thinking') or step.get('thinking') or '')
                    text = step.get('text_delta') or delta.get('text') or step.get('text') or ''
                    if text: tokens.append(text); await invoke(on_token, text)
                elif event == 'result' and not tokens:
                    result = data.get('result') or {}
                    text = result.get('response') or result.get('text') or ''
                    if text: tokens.append(text); await invoke(on_token, text)
            code = await proc.wait()
            stderr = await stderr_task
            if code:
                raise CouncilExecutionError(self.id, f"worker exited {code}: {stderr.decode(errors='replace')[-500:]}")
            return ''.join(tokens).strip()
        finally:
            await terminate_process_tree(proc)
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
