#!/usr/bin/env python3
"""A real agent loop for simulated students: the week-1 lab, executed live.

Bare ReAct-style loop (no framework): the model reasons in text, requests
tools via ACTION lines, observations are fed back, loop until FINAL or the
iteration cap. Produces genuinely agentic traces (multi-turn, tool calls,
failures) through the gateway, for viewer and autopsy testing.

Usage:
    python agent_student.py [--model argonne-coder] [--gateway URL]
Reads sim_keys.csv; runs each task in TASKS as a different sim student.
"""

import argparse
import csv
import json
import math
import os
import re
import time

import requests

SYSTEM = """You are an agent that solves tasks step by step using tools.
Available tools:
  calc(expression)   - evaluate a Python arithmetic expression (math module allowed)
  lookup(key)        - look up a constant in the course data table
Respond with EXACTLY ONE of:
  THOUGHT: <your reasoning>
  ACTION: <tool>(<argument>)
  FINAL: <your answer>
Use one ACTION at a time and wait for the OBSERVATION. Begin."""

TABLE = {
    "avogadro": 6.02214076e23,
    "boltzmann": 1.380649e-23,
    "planck_sites_2026": 41,
    "sophia_gpus": 256,
}


def run_tool(call: str) -> str:
    m = re.match(r"(\w+)\((.*)\)\s*$", call.strip())
    if not m:
        return "ERROR: could not parse action"
    tool, arg = m.group(1), m.group(2).strip().strip("\"'")
    if tool == "calc":
        try:
            return str(eval(arg, {"__builtins__": {}}, {"math": math}))
        except Exception as e:
            return f"ERROR: {e}"
    if tool == "lookup":
        return str(TABLE.get(arg.lower(), f"ERROR: no entry '{arg}'"))
    return f"ERROR: unknown tool '{tool}'"


def run_agent(task: str, key: str, model: str, gateway: str,
              session_id: str = "adhoc", student: str = "unknown",
              max_iters: int = 8) -> str:
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"TASK: {task}"}]
    for i in range(max_iters):
        r = requests.post(f"{gateway}/v1/chat/completions",
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "messages": messages,
                                "max_tokens": 300, "temperature": 0.2,
                                "user": student,
                                # lands in span attrs as metadata.requester_metadata:
                                # search/filter traces by session in Phoenix
                                "metadata": {"session_id": session_id,
                                             "student": student,
                                             "step": i + 1}},
                          timeout=120)
        r.raise_for_status()
        reply = r.json()["choices"][0]["message"]["content"].strip()
        messages.append({"role": "assistant", "content": reply})
        final = re.search(r"FINAL:\s*(.+)", reply, re.S)
        if final:
            return f"[{i+1} iters] {final.group(1).strip()[:120]}"
        action = re.search(r"ACTION:\s*(.+)", reply)
        obs = run_tool(action.group(1)) if action else "ERROR: no ACTION or FINAL found; use the required format"
        messages.append({"role": "user", "content": f"OBSERVATION: {obs}"})
        time.sleep(0.5)
    return f"[cap {max_iters} iters] did not converge (good autopsy material)"


TASKS = [
    ("sim-diligent@sim.invalid",
     "Compute Avogadro's number divided by the number of GPUs on Sophia, "
     "then give the base-10 logarithm of the result to 3 decimal places. "
     "Use lookup() for both constants."),
    ("sim-minimal@sim.invalid",
     "What is (37*89) + sqrt(1024)? Then divide by the boltzmann constant "
     "from the lookup table and report in scientific notation."),
    ("sim-burner@sim.invalid",
     "Find the entry 'dark_matter_density' in the lookup table and multiply "
     "it by 2. (Note: this entry does not exist; a well-behaved agent should "
     "discover that and say so.)"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="argonne-coder")
    ap.add_argument("--gateway", default=os.environ.get("GATEWAY_URL", "http://localhost:4000"))
    ap.add_argument("--keys", default=os.path.join(os.path.dirname(__file__), "sim_keys.csv"))
    args = ap.parse_args()

    keys = {row["email"]: row["key"] for row in csv.DictReader(open(args.keys))}
    stamp = time.strftime("%m%d-%H%M")
    for email, task in TASKS:
        student = email.split("@")[0]
        session = f"week1live-{student.removeprefix('sim-')}-{stamp}"
        print(f"\n=== {email}  [session: {session}]\n    task: {task[:90]}...")
        out = run_agent(task, keys[email], args.model, args.gateway,
                        session_id=session, student=student)
        print(f"    result: {out}")


if __name__ == "__main__":
    main()
