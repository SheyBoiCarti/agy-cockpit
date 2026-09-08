"""Command-line interface for the AI Council."""

import argparse
import asyncio
import sys
from typing import List

from agy_cockpit.council.council import AICouncil
from agy_cockpit.council.member import CouncilMember
from agy_cockpit.council.personas import (
    BOLD,
    CYAN,
    GREEN,
    MAGENTA,
    RED,
    RESET,
    WHITE,
    YELLOW,
)


def print_banner(num_agents: int, model: str, members: List[CouncilMember]):
    print(f"\n{BOLD}{CYAN}╔════════════════════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║                    ANTIGRAVITY AI COUNCIL CONTROL                     ║{RESET}")
    print(f"{BOLD}{CYAN}╚════════════════════════════════════════════════════════════════════════╝{RESET}")
    print(f"{WHITE}Active Model: {BOLD}{model}{RESET} | {WHITE}Active Agents: {BOLD}{num_agents}{RESET}\n")
    print(f"{BOLD}Council Roster:{RESET}")
    for idx, m in enumerate(members, start=1):
        print(f"  {idx}. {m.persona.format_header()} ({m.model_slug})")
    print(f"  ⚖️. {CYAN}⚖️ [Synthesizer — Council Chair & Arbitrator]{RESET} ({model})")
    print(f"\n{WHITE}Type {BOLD}/help{RESET} for commands or type a prompt to chat with the entire council.{RESET}\n")


async def run_deliberation(council: AICouncil, topic: str):
    print(f"\n{BOLD}{MAGENTA}============================================================{RESET}")
    print(f"{BOLD}{WHITE}🏛️  CONVENING COUNCIL DELIBERATION{RESET}")
    print(f"{BOLD}Topic:{RESET} {topic}")
    print(f"{BOLD}{MAGENTA}============================================================{RESET}\n")

    def on_stage_start(stage_name: str, stage_idx: int):
        print(f"\n{BOLD}{CYAN}>>> [STAGE {stage_idx}] {stage_name}{RESET}")
        print(f"{CYAN}{'─' * 60}{RESET}\n")

    def on_member_token(member: CouncilMember, token: str):
        # In multi-member streaming, prefix tokens with member tag
        sys.stdout.write(f"{member.persona.color_ansi}{token}{RESET}")
        sys.stdout.flush()

    def on_synthesis_token(token: str):
        sys.stdout.write(f"{WHITE}{token}{RESET}")
        sys.stdout.flush()

    res = await council.deliberate(
        topic=topic,
        on_stage_start=on_stage_start,
        on_member_token=None,  # We'll print stage outputs cleanly
        on_synthesis_token=None,
    )

    print(f"\n{BOLD}{CYAN}=== STAGE 1: INDEPENDENT MEMBER PERSPECTIVES ==={RESET}\n")
    for resp in res.stage_1_perspectives:
        m = council.get_member(resp.member_name)
        color = m.persona.color_ansi if m else WHITE
        print(f"{BOLD}{color}┌── {resp.member_name} ({resp.member_title}) ──┐{RESET}")
        print(resp.content.strip())
        print(f"{BOLD}{color}└{'─' * 45}┘{RESET}\n")

    print(f"\n{BOLD}{YELLOW}=== STAGE 2: CROSS-EXAMINATION & DEBATE ==={RESET}\n")
    for resp in res.stage_2_critiques:
        m = council.get_member(resp.member_name)
        color = m.persona.color_ansi if m else WHITE
        print(f"{BOLD}{color}┌── {resp.member_name} (Critique & Cross-Examination) ──┐{RESET}")
        print(resp.content.strip())
        print(f"{BOLD}{color}└{'─' * 45}┘{RESET}\n")

    print(f"\n{BOLD}{GREEN}=== STAGE 3: COUNCIL SYNTHESIS & FINAL VERDICT ==={RESET}\n")
    print(res.final_synthesis.strip())
    print(f"\n{BOLD}{GREEN}============================================================{RESET}\n")


async def run_voting(council: AICouncil, motion: str):
    print(f"\n{BOLD}{YELLOW}>>> CALLING ROLL-CALL VOTE ON MOTION:{RESET} \"{motion}\"\n")
    vote_res = await council.vote(motion)

    for v in vote_res["votes"]:
        m = council.get_member(v["member"])
        color = m.persona.color_ansi if m else WHITE
        badge = (
            f"\033[42m\033[30m APPROVED \033[0m"
            if v["vote"] == "APPROVE"
            else f"\033[41m\033[37m REJECTED \033[0m"
            if v["vote"] == "REJECT"
            else f"\033[43m\033[30m ABSTAIN \033[0m"
        )
        print(f"{color}{BOLD}[{v['member']}]{RESET} {badge} — {v['rationale']}")

    tally = vote_res["tally"]
    outcome = vote_res["outcome"]
    outcome_color = GREEN if outcome == "PASSED" else RED if outcome == "FAILED" else YELLOW
    print(f"\n{BOLD}Final Tally:{RESET} {GREEN}{tally['APPROVE']} Approve{RESET} | {RED}{tally['REJECT']} Reject{RESET} | {YELLOW}{tally['ABSTAIN']} Abstain{RESET}")
    print(f"{BOLD}Result:{RESET} {outcome_color}{BOLD}{outcome}{RESET}\n")


async def interactive_loop(council: AICouncil):
    print_banner(council.num_agents, council.model_slug, council.members)

    while True:
        try:
            user_input = input(f"{BOLD}{CYAN}Council > {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting AI Council.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
            print("Adjourning AI Council session.")
            break

        elif user_input.lower() in ("/help", "help"):
            print(f"\n{BOLD}Available Council Commands:{RESET}")
            print(f"  {CYAN}/deliberate <topic>{RESET}  Convene 3-stage deliberation (Analysis, Debate, Verdict)")
            print(f"  {CYAN}/vote <motion>{RESET}       Call immediate roll-call vote across all members")
            print(f"  {CYAN}/members{RESET}             Show council roster and assigned roles")
            print(f"  {CYAN}/all <message>{RESET}       Broadcast message to all members in parallel")
            print(f"  {CYAN}@<Member> <msg>{RESET}      Direct 1-on-1 question (e.g. @Architect or @Security)")
            print(f"  {CYAN}/exit{RESET}                Exit council\n")

        elif user_input.lower() == "/members":
            print(f"\n{BOLD}Council Members ({council.num_agents} Agents):{RESET}")
            for idx, m in enumerate(council.members, start=1):
                print(f"  {idx}. {m.persona.format_header()}")
                print(f"     Role: {m.persona.system_prompt[:90]}...\n")

        elif user_input.lower().startswith("/vote "):
            motion = user_input[6:].strip()
            await run_voting(council, motion)

        elif user_input.lower().startswith("/deliberate "):
            topic = user_input[12:].strip()
            await run_deliberation(council, topic)

        elif user_input.startswith("@"):
            parts = user_input.split(" ", 1)
            target = parts[0][1:]
            msg = parts[1] if len(parts) > 1 else ""
            if not msg:
                print(f"Please provide a message for @{target}.")
                continue
            m = council.get_member(target)
            if not m:
                print(f"Unknown council member '@{target}'. Known: {[x.name for x in council.members]}")
                continue
            print(f"\n{m.persona.format_header()} is responding...")
            reply = await council.chat_member(target, msg)
            print(f"\n{m.persona.color_ansi}{reply}{RESET}\n")

        else:
            # Broadcast to all members
            msg = user_input
            if msg.startswith("/all "):
                msg = msg[5:].strip()

            print(f"\n{BOLD}Broadcasting to all {council.num_agents} council members in parallel...{RESET}\n")
            responses = await council.broadcast(msg)
            for resp in responses:
                m = council.get_member(resp.member_name)
                color = m.persona.color_ansi if m else WHITE
                print(f"{BOLD}{color}┌── {resp.member_name} ({resp.member_title}) ──┐{RESET}")
                print(resp.content.strip())
                print(f"{BOLD}{color}└{'─' * 45}┘{RESET}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Antigravity AI Council — Spawn and converse with X Gemini agents."
    )
    parser.add_argument(
        "-n", "--agents",
        type=int,
        default=3,
        help="Number of Gemini council agents to spawn (default: 3)",
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        default="gemini-3.8-flash-high",
        help="Gemini model slug to use (default: gemini-3.8-flash-high)",
    )
    parser.add_argument(
        "-t", "--topic",
        type=str,
        default=None,
        help="Deliberate on a specific topic and exit",
    )
    parser.add_argument(
        "-v", "--vote",
        type=str,
        default=None,
        help="Conduct a roll-call vote on a motion and exit",
    )
    parser.add_argument(
        "-w", "--workspace",
        type=str,
        default=None,
        help="Workspace directory context",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Launch interactive AI council chat loop",
    )

    args = parser.parse_args()

    council = AICouncil(
        num_agents=args.agents,
        model_slug=args.model,
        workspace_path=args.workspace,
    )

    if args.topic:
        asyncio.run(run_deliberation(council, args.topic))
    elif args.vote:
        asyncio.run(run_voting(council, args.vote))
    else:
        asyncio.run(interactive_loop(council))


if __name__ == "__main__":
    main()
