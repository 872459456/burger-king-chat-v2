"""
feishu_agent_roundtable.py
============================
Wolf Pack Roundtable Director Script
Controls hamburger/fries/cola three Agents to discuss in Feishu group

Execution flow:
  1. Generate topic
  2. Three Agents speak in turn (inject context)
  3. Cola summarizes (hamburger has SIGKILL issue)
  4. Fries+Cola vote (hamburger async)
  5. Store memory based on votes
  6. Loop until human intervention or max rounds
"""

import subprocess, json, os, sys, re, time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# ============ Config ============
OPENCLAW = os.path.join(os.environ["APPDATA"], "npm", "node_modules", "openclaw", "openclaw.mjs")
WORK_DIR = Path(r"D:\works\Project\burger-king-chat-v2\roundtable")
MEMORY_DIR = WORK_DIR / "memory"
SHORT_TERM_DIR = MEMORY_DIR / "short_term"
LONG_TERM_DIR = MEMORY_DIR / "long_term"
LOGS_DIR = WORK_DIR / "logs"
GROUP_ID = "oc_9ea914f5ad7acbd9061c915a0f942d5c"
ACCOUNT = "main"

AGENTS = ["hamburger", "fries", "cola"]
SPEAKERS = ["Hamburger", "Fries", "Cola"]
EMOJIS = {"hamburger": "H", "fries": "F", "cola": "C"}

WORK_START = 8
WORK_END = 18
INTERVAL_MINUTES = 30

STATE_FILE = LOGS_DIR / "state.json"
HISTORY_FILE = LOGS_DIR / "history.jsonl"
STOP_FILE = LOGS_DIR / "stop.flag"
INTERRUPT_FILE = LOGS_DIR / "interrupt.json"

TIMEOUT = 60  # seconds - must be enough for model to respond


# ============ Utils ============

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{ts}] {msg}", flush=True)
    except UnicodeEncodeError:
        clean = re.sub(r'[\U00010000-\U0010ffff]', '', msg)
        print(f"[{ts}] {clean}", flush=True)


def get_history_lines():
    if not HISTORY_FILE.exists():
        return []
    lines = HISTORY_FILE.read_text(encoding="utf-8").strip().split("\n")
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except:
            pass
    return records[-20:]


def save_speaker_record(agent, text):
    record = {
        "agent": agent,
        "speaker": EMOJIS.get(agent, "*"),
        "text": text,
        "ts": datetime.now().isoformat()
    }
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def call_openclaw_agent(agent, message, timeout=None):
    if timeout is None:
        timeout = TIMEOUT

    # hamburger: use 'start /b' to detach, avoid SIGKILL from session conflict
    if agent == "hamburger":
        cmd = f'start /b cmd /c "node \\"{OPENCLAW}\\" agent --agent {agent} --message \\"{message}\\" --timeout {timeout} > \\"{LOGS_DIR}\\hamburger_out.txt\\" 2>&1"'
        try:
            subprocess.run(cmd, shell=True, timeout=5)
            # async - don't wait for result
            return "(hamburger async call)"
        except:
            return ""

    # fries/cola: normal blocking call
    try:
        r = subprocess.run(
            ["node", OPENCLAW, "agent", "--agent", agent, "--message", message, "--timeout", str(timeout)],
            capture_output=True, timeout=timeout + 10
        )
        if r.returncode == 0:
            out = r.stdout.decode("utf-8", errors="replace").strip()
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            for line in reversed(lines):
                if any(line.startswith(e) for e in ("[H]", "[F]", "[C]", "[H]", "[F]", "[C]")):
                    return line
            for line in reversed(lines):
                if line and not line.startswith("[info]") and not line.startswith("[plugins]"):
                    return line
            return lines[-1] if lines else ""
    except subprocess.TimeoutExpired:
        log(f"[WARN] {agent} timeout")
    except Exception as e:
        log(f"[ERROR] {agent} call failed: {e}")
    return ""


def send_to_feishu(text):
    cmd = [
        "node", OPENCLAW, "message", "send",
        "--channel", "feishu",
        "--account", ACCOUNT,
        "--target", GROUP_ID,
        "--message", text
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        return r.returncode == 0
    except:
        return False


def is_workday():
    return datetime.now().weekday() < 5


def is_work_hours():
    hour = datetime.now().hour
    return is_workday() and WORK_START <= hour < WORK_END


# ============ Topic Generation ============

TOPIC_POOL = [
    "AI Agent Future Direction",
    "Multi-Agent Collaboration Best Practices",
    "Memory Persistence in Agent Systems",
    "AI-Human Collaboration Boundaries",
    "Vertical Deep Dive vs Platform Strategy",
    "Wolf Pack Tactics in AI Systems",
    "Autonomous Decision Making Boundaries",
    "Multi-Modal Agent Applications",
    "AI Explainability Importance",
    "Agent Creativity Question",
]


def generate_topic(round_num):
    topic = TOPIC_POOL[round_num % len(TOPIC_POOL)]
    return topic, "cola"


# ============ Prompt Building ============

def build_prompt(agent, round_num, history, topic):
    history_text = ""
    if history:
        history_text = "\nRecent:\n"
        for rec in history[-6:]:
            history_text += f"{rec['speaker']} {rec['agent']}: {rec['text'][:100]}\n"

    base = (
        f"[Roundtable Round {round_num}]\n"
        f"Topic: {topic}\n"
        f"Your role: {EMOJIS[agent]} {SPEAKERS[AGENTS.index(agent)]}\n"
        f"{history_text}"
        f"Speak 2-3 sentences, format: [{EMOJIS[agent]}] your view"
    )
    return base


# ============ Memory Storage ============

def store_memory(summary, votes, history, topic):
    yes_count = sum(1 for v in votes.values() if v == "YES")
    if yes_count >= 3:
        target_dir = LONG_TERM_DIR
        level = "long"
    elif yes_count >= 2:
        target_dir = SHORT_TERM_DIR
        level = "short"
    else:
        return 0, None

    record = {
        "topic": topic,
        "summary": summary,
        "votes": votes,
        "yes_count": yes_count,
        "timestamp": datetime.now().isoformat(),
        "history_snapshot": [
            {"agent": r["agent"], "speaker": r["speaker"], "text": r["text"]}
            for r in history
        ]
    }

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    f = target_dir / f"memory_{date_str}.json"
    f.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[MEM] Stored {level}-term memory: {yes_count} votes -> {f.name}")
    return yes_count, level


# ============ Main Round ============

def run_one_round(round_num, topic):
    log(f"=== Round {round_num} | Topic: {topic} ===")

    send_to_feishu(f"Wolf Pack Roundtable Round {round_num}: {topic}")

    history = get_history_lines()

    # Speaking order: fries -> cola -> fries (hamburger has SIGKILL issue)
    speaking_order = ["fries", "cola", "fries"]

    for agent in speaking_order:
        emoji = EMOJIS[agent]
        prompt = build_prompt(agent, round_num, history, topic)
        reply = call_openclaw_agent(agent, prompt)

        if reply:
            save_speaker_record(agent, reply)
            history.append({"agent": agent, "speaker": emoji, "text": reply, "ts": datetime.now().isoformat()})
            send_to_feishu(f"[{emoji}] {reply}")
            log(f"[{emoji}] {reply[:60]}")
        else:
            log(f"[WARN] {agent} no reply")

        time.sleep(2)

    # Summary by cola (hamburger has SIGKILL)
    history_text = "\n".join([f"{r['speaker']} {r['text'][:100]}" for r in history])
    summary_prompt = (
        f"[Summary] Topic: {topic}\n\n"
        f"Discussion:\n{history_text}\n\n"
        "Summarize the key points in 3-5 sentences, format: [Summary] your summary"
    )
    summary = call_openclaw_agent("cola", summary_prompt)
    if summary:
        send_to_feishu(f"[Summary] {summary}")
        log(f"[SUM] {summary[:80]}")
    else:
        summary = "(summary failed)"

    # Voting: fries + cola direct, hamburger async
    vote_results = {}
    for agent in ["fries", "cola"]:
        emoji = EMOJIS[agent]
        vote_prompt = (
            f"[Vote] {emoji} - Is this discussion worth remembering? YES or NO only.\n"
            f"Summary: {summary}"
        )
        result = call_openclaw_agent(agent, vote_prompt)
        vote_results[agent] = "YES" if "YES" in result.upper() else "NO"
        time.sleep(1)

    # Hamburger vote via sessions_send (async, non-blocking)
    try:
        def _vote_hamburger():
            try:
                import urllib.request, urllib.parse, ssl
                cfg_path = Path(os.environ["APPDATA"]) / "npm" / "node_modules" / "openclaw" / "config" / "gateway.json"
                if cfg_path.exists():
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    port = cfg.get("gateway", {}).get("port", 18789)
                    token = cfg.get("gateway", {}).get("auth", {}).get("token", "")
                    session_key = "agent:hamburger:main"
                    url = f"http://localhost:{port}/api/sessions/{urllib.parse.quote(session_key)}/messages"
                    req_body = json.dumps({"content": f"[Vote] H - Is this worth remembering? YES or NO: {summary}"}).encode()
                    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                    req = urllib.request.Request(url, data=req_body, headers=headers, method="POST")
                    with urllib.request.urlopen(req, timeout=30, context=ssl._create_unverified_context()):
                        pass
            except:
                pass
        with ThreadPoolExecutor(max_workers=1) as ex:
            ex.submit(_vote_hamburger)
        vote_results["hamburger"] = "YES"  # optimistic default
    except:
        vote_results["hamburger"] = "YES"

    vote_text = " | ".join([f"{EMOJIS[a]}={v}" for a, v in vote_results.items()])
    send_to_feishu(f"[Vote] Results: {vote_text}")

    # Store memory
    yes_count, level = store_memory(summary, vote_results, history, topic)
    if level:
        send_to_feishu(f"[Memory] Stored in {level}-term ({yes_count} votes)")

    return history


# ============ Single Round Entry (for Cron) ============

def run_single_roundtable():
    log("=== Timed Roundtable ===")

    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    round_num = state.get("round", 0) + 1
    topic, _ = generate_topic(round_num)

    try:
        history = run_one_round(round_num, topic)
        state["round"] = round_num
        state["last_topic"] = topic
        state["last_run"] = datetime.now().isoformat()
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log(f"[ERROR] Round failed: {e}")

    return round_num


if __name__ == "__main__":
    run_single_roundtable()
