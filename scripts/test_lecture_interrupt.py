"""Test lecture interrupt flow without microphone.

Starts the agent with lecture, waits for a few blocks,
then injects a student message into ctx_chat to simulate interruption.
Checks that the agent: stops, answers, resumes lecture.
"""
import json
import multiprocessing as mp
import os
import sys
import time
import threading

mp.set_start_method("spawn", force=True)

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_project_root, "src"))
os.chdir(_project_root)  # agent expects CWD = project root

from dotenv import load_dotenv
load_dotenv(".env")

from data_schema.structure_templates import create_ctx_swarm
from data_flow.ctx_handler import CtxHandler
from data_schema.chat_structures import EventBase
from utils.time_helper import eztime


def inject_student_message(ctx_handler, msg: str):
    """Simulate a student speaking."""
    event = EventBase(
        processing_timestamp=time.time_ns(),
        date=eztime(),
        env="voice",
        user="TestStudent",
        type="chat",
        msg=msg,
        filter_results={"acceptable": True},
    )
    ctx_handler.add_message(event)
    print(f"\n>>> INJECTED: '{msg}'\n", flush=True)


def main():
    print("=== LECTURE INTERRUPT TEST ===", flush=True)

    # Create shared state
    manager = mp.Manager()
    ctx_swarm = create_ctx_swarm(manager)
    ctx_swarm["env"]["actived"] = True
    ctx_handler = CtxHandler(ctx_swarm)

    # Write lecture signal (relative to src/ which is CWD)
    plan_path = "data/lecture_plans/ai_professor_lecture.json"
    if not os.path.exists(plan_path):
        print(f"ERROR: Plan not found at {abs_plan}")
        return

    with open("data/lecture_start_signal.txt", "w") as f:
        f.write(plan_path)

    # Clear logs
    open("data/agent_log.txt", "w").close()

    # Start agent
    from agent.core_agent import CoreAgent
    agent = CoreAgent(ctx_swarm, ctx_handler)

    print("Agent created. Starting in background thread...", flush=True)

    # Run agent in background
    agent_thread = threading.Thread(target=agent.run, daemon=True)
    agent_thread.start()

    # Wait for lecture to start and deliver 2 blocks
    print("Waiting 15s for lecture to deliver first blocks...", flush=True)
    time.sleep(15)

    # Read agent log to see progress
    with open("data/agent_log.txt", "r", encoding="utf-8") as f:
        log = f.read()
    block_count = log.count("[LECTURE] Stream done:")
    print(f"Blocks delivered so far: {block_count}", flush=True)

    # Inject interrupt
    print("\n=== INJECTING INTERRUPT ===", flush=True)
    inject_student_message(ctx_handler, "Профессор, а что такое AI агент?")

    # Wait for response
    print("Waiting 15s for agent to answer and resume...", flush=True)
    time.sleep(15)

    # Check log
    with open("data/agent_log.txt", "r", encoding="utf-8") as f:
        log = f.read()

    # Verify flow
    print("\n=== VERIFICATION ===", flush=True)

    has_interrupt = "[LECTURE] Student interrupted during block" in log
    has_question = "Answering question:" in log
    has_answered = "[LECTURE] Answered:" in log
    has_resume = "Resuming after question" in log

    # Check if lecture continued after the answer (any block after the answer)
    lines = log.strip().split("\n")
    answer_idx = -1
    for i, line in enumerate(lines):
        if "[LECTURE] Answered:" in line:
            answer_idx = i

    resumed_lecture = False
    if answer_idx >= 0:
        for line in lines[answer_idx:]:
            if "[LECTURE] step()" in line or "[LECTURE] Block" in line:
                resumed_lecture = True
                break

    print(f"  Interrupt detected:  {'PASS' if has_interrupt else 'FAIL'}")
    print(f"  Question received:   {'PASS' if has_question else 'FAIL'}")
    print(f"  Answer generated:    {'PASS' if has_answered else 'FAIL'}")
    print(f"  Resume announced:    {'PASS' if has_resume else 'FAIL'}")
    print(f"  Lecture continued:   {'PASS' if resumed_lecture else 'FAIL'}")

    all_pass = all([has_interrupt, has_question, has_answered, has_resume, resumed_lecture])
    print(f"\n  OVERALL: {'ALL PASS' if all_pass else 'SOME FAILED'}", flush=True)

    # Print relevant log section
    print("\n=== RELEVANT LOG ===", flush=True)
    for line in lines:
        if any(k in line for k in ["interrupt", "Student", "Answering", "Answered", "Продолж", "step()", "Block"]):
            print(f"  {line}")

    # Stop
    agent.stop()
    ctx_swarm["env"]["actived"] = False
    print("\n=== TEST COMPLETE ===", flush=True)


if __name__ == "__main__":
    main()
