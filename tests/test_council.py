"""Unit and integration tests for AI Council multi-agent system."""

import os
import pytest
from agy_cockpit.council.personas import (
    get_council_personas,
    ARCHITECT_PERSONA,
    SECURITY_PERSONA,
    PRAGMATIST_PERSONA,
)
from agy_cockpit.council.member import CouncilMember
from agy_cockpit.council.council import AICouncil


@pytest.fixture(autouse=True)
def enable_test_mode(monkeypatch):
    monkeypatch.setenv("COUNCIL_TEST_MODE", "1")


def test_council_personas_generation():
    # Test default 3 personas
    p3 = get_council_personas(3)
    assert len(p3) == 3
    assert p3[0].id == "architect"
    assert p3[1].id == "security"
    assert p3[2].id == "pragmatist"

    # Test 5 personas
    p5 = get_council_personas(5)
    assert len(p5) == 5

    # Test dynamic generation beyond preset count
    p8 = get_council_personas(8)
    assert len(p8) == 8
    assert p8[7].id == "agent_8"
    assert "Specialist Agent #8" in p8[7].title


@pytest.mark.asyncio
async def test_council_member_chat():
    member = CouncilMember(persona=ARCHITECT_PERSONA)
    tokens = []

    def on_token(tok: str):
        tokens.append(tok)

    reply = await member.chat("Design an async pipeline", on_token=on_token)
    assert "Architect" in reply
    assert len(tokens) > 0
    assert "".join(tokens).strip() == reply.strip()
    assert len(member.history) == 2  # user + assistant


@pytest.mark.asyncio
async def test_council_broadcast():
    council = AICouncil(num_agents=3)
    assert len(council.members) == 3

    responses = await council.broadcast("Should we use SQLite?")
    assert len(responses) == 3
    member_names = [r.member_name for r in responses]
    assert "Architect" in member_names
    assert "Security" in member_names
    assert "Pragmatist" in member_names


@pytest.mark.asyncio
async def test_council_chat_member():
    council = AICouncil(num_agents=3)
    resp = await council.chat_member("security", "What are the top 3 CVEs to watch?")
    assert resp.member_name == "Security"
    assert "Security" in resp.content

    # Lookup by index
    resp_idx = await council.chat_member(0, "Check architecture")
    assert resp_idx.member_name == "Architect"

    # Lookup non-existent member
    with pytest.raises(ValueError):
        await council.chat_member("nonexistent", "Hello")


@pytest.mark.asyncio
async def test_council_deliberation():
    council = AICouncil(num_agents=3)
    stages_visited = []

    def on_stage_start(name: str, idx: int):
        stages_visited.append(idx)

    result = await council.deliberate(
        topic="Adopt microservices vs modular monolith",
        on_stage_start=on_stage_start,
    )

    assert stages_visited == [1, 2, 3]
    assert len(result.stage_1_perspectives) == 3
    assert len(result.stage_2_critiques) == 3
    assert "Synthesizer" in result.final_synthesis


@pytest.mark.asyncio
async def test_council_voting():
    council = AICouncil(num_agents=3)
    res = await council.vote("Adopt strict types across codebase")

    assert res["motion"] == "Adopt strict types across codebase"
    assert "tally" in res
    assert len(res["votes"]) == 3
    assert res["outcome"] in ("PASSED", "FAILED", "TIED")
