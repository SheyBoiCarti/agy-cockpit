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


class AICouncil:
    """Orchestrates an AI Council consisting of X Gemini agents."""

    def __init__(
        self,
        num_agents: int = 3,
        model_slug: str = "gemini-3.8-flash-high",
        workspace_path: Optional[str] = None,
        custom_personas: Optional[List[CouncilPersona]] = None,
    ):
        self.num_agents = max(1, num_agents)
        self.model_slug = model_slug
        self.workspace_path = workspace_path

        # Initialize council members
        personas = custom_personas or get_council_personas(self.num_agents)
        self.members: List[CouncilMember] = [
            CouncilMember(
                persona=p,
                model_slug=self.model_slug,
                workspace_path=self.workspace_path,
            )
            for p in personas[: self.num_agents]
        ]

        # The Council Chair / Synthesizer
        self.chair = CouncilMember(
            persona=SYNTHESIZER_PERSONA,
            model_slug=self.model_slug,
            workspace_path=self.workspace_path,
        )

    def get_member(self, target: Union[str, int]) -> Optional[CouncilMember]:
        """Looks up a council member by index or name/role."""
        if isinstance(target, int):
            if 0 <= target < len(self.members):
                return self.members[target]
            return None

        target_lower = target.strip().lower().lstrip("@")
        for m in self.members:
            if m.id.lower() == target_lower or m.name.lower() == target_lower:
                return m
        if self.chair.id.lower() == target_lower or self.chair.name.lower() == target_lower:
            return self.chair
        return None

    async def broadcast(
        self,
        message: str,
        on_member_token: Optional[Callable[[CouncilMember, str], Any]] = None,
    ) -> List[MemberResponse]:
        """Broadcasts a user message to all X council members concurrently."""
        tasks = []
        for member in self.members:
            async def _run_member(m: CouncilMember):
                def _token_cb(token: str):
                    if on_member_token:
                        res = on_member_token(m, token)
                        if asyncio.iscoroutine(res):
                            return res
                    return None

                reply = await m.chat(message, on_token=_token_cb)
                return MemberResponse(
                    member_id=m.id,
                    member_name=m.name,
                    member_title=m.title,
                    content=reply,
                )

            tasks.append(_run_member(member))

        results = await asyncio.gather(*tasks)
        return list(results)

    async def chat_member(
        self,
        target: Union[str, int],
        message: str,
        on_token: Optional[Callable[[str], Any]] = None,
    ) -> MemberResponse:
        """Sends a direct message to a specific council member."""
        member = self.get_member(target)
        if not member:
            raise ValueError(f"Council member '{target}' not found. Available: {[m.name for m in self.members]}")

        reply = await member.chat(message, on_token=on_token)
        return MemberResponse(
            member_id=member.id,
            member_name=member.name,
            member_title=member.title,
            content=reply,
        )

    async def deliberate(
        self,
        topic: str,
        on_stage_start: Optional[Callable[[str, int], Any]] = None,
        on_member_token: Optional[Callable[[CouncilMember, str], Any]] = None,
        on_synthesis_token: Optional[Callable[[str], Any]] = None,
    ) -> CouncilDeliberationResult:
        """Conducts a rigorous 3-stage council deliberation on a topic or proposal."""
        result = CouncilDeliberationResult(topic=topic)

        # -------------------------------------------------------------
        # STAGE 1: Independent Deliberation (Concurrent Analysis)
        # -------------------------------------------------------------
        if on_stage_start:
            res = on_stage_start("Stage 1: Independent Deliberation & Analysis", 1)
            if asyncio.iscoroutine(res):
                await res

        stage1_prompt = (
            f"[COUNCIL CONVENE — STAGE 1: INDEPENDENT PERSPECTIVE]\n"
            f"Topic for Deliberation:\n{topic}\n\n"
            f"Provide your independent, focused assessment strictly through the lens of your assigned persona "
            f"and core priorities. Be concise, rigorous, and direct."
        )

        stage1_responses = await self.broadcast(stage1_prompt, on_member_token=on_member_token)
        result.stage_1_perspectives = stage1_responses

        # -------------------------------------------------------------
        # STAGE 2: Cross-Examination & Peer Critique (Concurrent Debate)
        # -------------------------------------------------------------
        if on_stage_start:
            res = on_stage_start("Stage 2: Cross-Examination & Peer Critique", 2)
            if asyncio.iscoroutine(res):
                await res

        perspectives_summary = "\n\n".join([
            f"### [{r.member_name} — {r.member_title}]\n{r.content}"
            for r in stage1_responses
        ])

        stage2_tasks = []
        for member in self.members:
            async def _run_critique(m: CouncilMember):
                critique_prompt = (
                    f"[COUNCIL CONVENE — STAGE 2: CROSS-EXAMINATION]\n"
                    f"Here are the perspectives submitted by your fellow council members:\n\n"
                    f"{perspectives_summary}\n\n"
                    f"Review their assessments. From your stance as {m.title}:\n"
                    f"1. Which points do you strongly agree with and endorse?\n"
                    f"2. Where do you disagree or see unaddressed risks/blind spots?\n"
                    f"Keep your response concise (under 200 words) and constructive."
                )

                def _token_cb(token: str):
                    if on_member_token:
                        return on_member_token(m, token)
                    return None

                reply = await m.chat(critique_prompt, on_token=_token_cb)
                return MemberResponse(
                    member_id=m.id,
                    member_name=m.name,
                    member_title=m.title,
                    content=reply,
                )

            stage2_tasks.append(_run_critique(member))

        stage2_responses = await asyncio.gather(*stage2_tasks)
        result.stage_2_critiques = list(stage2_responses)

        # -------------------------------------------------------------
        # STAGE 3: Council Synthesis & Verdict
        # -------------------------------------------------------------
        if on_stage_start:
            res = on_stage_start("Stage 3: Council Synthesis & Actionable Consensus", 3)
            if asyncio.iscoroutine(res):
                await res

        critiques_summary = "\n\n".join([
            f"### [{r.member_name} — {r.member_title}]\n{r.content}"
            for r in stage2_responses
        ])

        synthesis_prompt = (
            f"[COUNCIL CONVENE — STAGE 3: SYNTHESIS & FINAL VERDICT]\n"
            f"Topic: {topic}\n\n"
            f"Initial Perspectives:\n{perspectives_summary}\n\n"
            f"Peer Critiques & Debate:\n{critiques_summary}\n\n"
            f"As the Council Chair and Arbitrator, synthesize the entire deliberation into:\n"
            f"1. **Core Agreements**: Unanimous points and consensus principles.\n"
            f"2. **Primary Trade-offs**: Contested trade-offs and differing architectural priorities.\n"
            f"3. **Council Recommendation & Next Steps**: The definitive, prioritized path forward."
        )

        synthesis_text = await self.chair.chat(synthesis_prompt, on_token=on_synthesis_token)
        result.final_synthesis = synthesis_text

        return result

    async def vote(self, motion: str) -> Dict[str, Any]:
        """Requests an immediate roll-call vote from all council members."""
        vote_prompt = (
            f"[COUNCIL ROLL-CALL VOTE]\n"
            f"Motion on the table: \"{motion}\"\n\n"
            f"Cast your vote as {self.chair.title}. You must begin your response with exactly one word: "
            f"'APPROVE', 'REJECT', or 'ABSTAIN', followed by exactly one sentence explaining why."
        )

        tasks = [m.chat(vote_prompt) for m in self.members]
        raw_votes = await asyncio.gather(*tasks)

        tally = {"APPROVE": 0, "REJECT": 0, "ABSTAIN": 0}
        votes: List[Dict[str, str]] = []

        for m, reply in zip(self.members, raw_votes):
            text = reply.strip()
            first_word = text.split()[0].upper().rstrip(":,.") if text else "ABSTAIN"
            decision = first_word if first_word in tally else "ABSTAIN"
            tally[decision] += 1
            votes.append({
                "member": m.name,
                "title": m.title,
                "vote": decision,
                "rationale": text,
            })

        outcome = "PASSED" if tally["APPROVE"] > tally["REJECT"] else "FAILED"
        if tally["APPROVE"] == tally["REJECT"]:
            outcome = "TIED"

        return {
            "motion": motion,
            "outcome": outcome,
            "tally": tally,
            "votes": votes,
        }
