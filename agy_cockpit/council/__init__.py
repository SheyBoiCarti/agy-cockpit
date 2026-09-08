"""AI Council package for spawning and managing X Gemini agents."""

from agy_cockpit.council.personas import (
    CouncilPersona,
    get_council_personas,
    ARCHITECT_PERSONA,
    SECURITY_PERSONA,
    PRAGMATIST_PERSONA,
    CRITIC_PERSONA,
    PERFORMANCE_PERSONA,
    SYNTHESIZER_PERSONA,
)
from agy_cockpit.council.member import CouncilMember
from agy_cockpit.council.council import (
    AICouncil,
    CouncilDeliberationResult,
    MemberResponse,
)

__all__ = [
    "AICouncil",
    "CouncilMember",
    "CouncilPersona",
    "CouncilDeliberationResult",
    "MemberResponse",
    "get_council_personas",
    "ARCHITECT_PERSONA",
    "SECURITY_PERSONA",
    "PRAGMATIST_PERSONA",
    "CRITIC_PERSONA",
    "PERFORMANCE_PERSONA",
    "SYNTHESIZER_PERSONA",
]
