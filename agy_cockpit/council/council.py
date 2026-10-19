"""AI Council orchestration managing X Gemini agents."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from agy_cockpit.council.member import CouncilMember
from agy_cockpit.council.personas import (
    CouncilPersona,
    SYNTHESIZER_PERSONA,
    get_council_personas,
    BOLD,
    RESET,
)

logger = logging.getLogger(__name__)


@dataclass
class MemberResponse:
    member_id: str
    member_name: str
    member_title: str
    content: str


@dataclass
class CouncilDeliberationResult:
    topic: str
    stage_1_perspectives: List[MemberResponse] = field(default_factory=list)
    stage_2_critiques: List[MemberResponse] = field(default_factory=list)
    final_synthesis: str = ""


async def gather_members(coroutines):
    tasks = [asyncio.create_task(c) for c in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class AICouncil:
    def __init__(self, num_agents=3, model_slug="gemini-3.8-flash-high", workspace_path=None,
                 custom_personas=None, runner=None, member_timeout_seconds=120, on_progress=None):
        self.num_agents = max(1, num_agents)
        self.model_slug = model_slug
        self.workspace_path = workspace_path
        self.on_progress = on_progress
        personas = custom_personas or get_council_personas(self.num_agents)
        self.members = [CouncilMember(p, model_slug=model_slug, workspace_path=workspace_path,
            runner=runner, member_timeout_seconds=member_timeout_seconds) for p in personas[:self.num_agents]]
        self.chair = CouncilMember(SYNTHESIZER_PERSONA, model_slug=model_slug, workspace_path=workspace_path,
            runner=runner, member_timeout_seconds=member_timeout_seconds)

    def get_member(self, target):
        if isinstance(target, int): return self.members[target] if 0 <= target < len(self.members) else None
        target = target.lower().lstrip('@')
        return next((m for m in [*self.members, self.chair] if target in (m.id.lower(), m.name.lower())), None)

    async def _progress(self, stage, member, state, text_delta=None):
        from agy_cockpit.council.member import invoke
        await invoke(self.on_progress, stage, member.id, state, text_delta)

    async def _ask(self, member, prompt, stage, cancellation_token=None, on_token=None):
        from agy_cockpit.council.member import invoke
        if cancellation_token and cancellation_token.is_set(): raise asyncio.CancelledError()
        await self._progress(stage, member, 'running')
        async def token(text):
            await self._progress(stage, member, 'running', text)
            await invoke(on_token, text)
        try:
            text = await member.chat(prompt, on_token=token, cancellation_token=cancellation_token)
            await self._progress(stage, member, 'completed')
            return MemberResponse(member.id, member.name, member.title, text)
        except asyncio.CancelledError:
            await self._progress(stage, member, 'cancelled'); raise
        except Exception:
            await self._progress(stage, member, 'failed'); raise

    async def broadcast(self, message, on_member_token=None, cancellation_token=None):
        def callback(member):
            return (lambda text: on_member_token(member, text)) if on_member_token else None
        return await gather_members([self._ask(m, message, 'analysis', cancellation_token, callback(m)) for m in self.members])

    async def chat_member(self, target, message, on_token=None, cancellation_token=None):
        member = self.get_member(target)
        if not member: raise ValueError(f"Council member '{target}' not found")
        if not message.strip(): raise ValueError('A Council question is required')
        return await self._ask(member, message, 'ask', cancellation_token, on_token)

    async def deliberate(self, topic, on_stage_start=None, on_member_token=None, on_synthesis_token=None, cancellation_token=None):
        from agy_cockpit.council.member import invoke
        if not topic.strip(): raise ValueError('A deliberation topic is required')
        result = CouncilDeliberationResult(topic)
        await invoke(on_stage_start, 'Stage 1: Independent analysis', 1)
        result.stage_1_perspectives = await self.broadcast(f"[COUNCIL STAGE 1: INDEPENDENT PERSPECTIVE]\nTopic: {topic}\nProvide a concise assessment from your own persona.", on_member_token, cancellation_token)
        perspectives = '\n\n'.join(f'{r.member_name}: {r.content}' for r in result.stage_1_perspectives)
        await invoke(on_stage_start, 'Stage 2: Peer critique', 2)
        def callback(member):
            return (lambda text: on_member_token(member, text)) if on_member_token else None
        result.stage_2_critiques = await gather_members([self._ask(m,
            f"[COUNCIL STAGE 2: CROSS-EXAMINATION]\nTopic: {topic}\nPeer perspectives:\n{perspectives}\nState agreements, disagreements and unaddressed risks in under 200 words.",
            'critique', cancellation_token, callback(m)) for m in self.members])
        critiques = '\n\n'.join(f'{r.member_name}: {r.content}' for r in result.stage_2_critiques)
        await invoke(on_stage_start, 'Stage 3: Synthesis', 3)
        synthesis = await self._ask(self.chair,
            f"[COUNCIL STAGE 3: SYNTHESIS]\nTopic: {topic}\nPerspectives:\n{perspectives}\nCritiques:\n{critiques}\nGive core agreements, contested trade-offs and prioritized next steps. Do not invent unanimity.",
            'synthesis', cancellation_token, on_synthesis_token)
        result.final_synthesis = synthesis.content
        return result

    async def vote(self, motion, cancellation_token=None):
        import re
        from agy_cockpit.council.member import CouncilExecutionError
        if not motion.strip(): raise ValueError('A voting motion is required')
        responses = await gather_members([self._ask(m,
            f"[COUNCIL ROLL-CALL VOTE]\nMotion: {motion}\nCast your vote as {m.title}. Begin with APPROVE, REJECT, or ABSTAIN followed by one sentence explaining why.",
            'vote', cancellation_token) for m in self.members])
        tally = {'APPROVE': 0, 'REJECT': 0, 'ABSTAIN': 0}
        votes = []
        for member, response in zip(self.members, responses):
            match = re.match(r'^(?:\*\*|__|`)?(APPROVE|REJECT|ABSTAIN)(?:\*\*|__|`)?(?=[\s:,.!]|$)', response.content.strip(), re.I)
            if not match:
                await self._progress('vote', member, 'failed')
                raise CouncilExecutionError(member.id, 'malformed vote result')
            decision = match[1].upper(); tally[decision] += 1
            votes.append({'member': member.name, 'title': member.title, 'vote': decision, 'rationale': response.content})
        outcome = 'PASSED' if tally['APPROVE'] > tally['REJECT'] else 'FAILED' if tally['REJECT'] > tally['APPROVE'] else 'TIED'
        return {'motion': motion, 'outcome': outcome, 'tally': tally, 'votes': votes}
