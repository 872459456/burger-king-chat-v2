"""
洋葱圈圆桌导演 - 重构版 v2.1

核心原理: 洋葱圈(导演) + 汉堡/薯条/可乐(演员)
通过 sessions_spawn 隔离子会话调用Agent，避免SIGKILL冲突

执行流程:
1. 洋葱圈宣布议题
2. 依次 sessions_spawn 调用各Agent发言
3. 洋葱圈总结
4. sessions_spawn 调用各Agent投票
5. 发送结果到飞书
"""

import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============ 配置 ============
WORK_DIR = Path(__file__).parent
MEMORY_DIR = WORK_DIR / "memory"
SHORT_TERM_DIR = MEMORY_DIR / "short_term"
LONG_TERM_DIR = MEMORY_DIR / "long_term"
LOGS_DIR = WORK_DIR / "logs"
GROUP_ID = "oc_9ea914f5ad7acbd9061c915a0f942d5c"
ACCOUNT = "main"

# Agent配置
AGENTS = ["hamburger", "fries", "cola"]
EMOJI = {"hamburger": "🍔", "fries": "🍟", "cola": "🥤", "onion": "🧅"}
SPEAKERS = {"hamburger": "汉堡", "fries": "薯条", "cola": "可乐", "onion": "洋葱圈"}

# OpenClaw路径
OPENCLAW_CMD = "openclaw.cmd"  # Windows环境

# Timeout设置
SPAWN_TIMEOUT = 90  # sessions_spawn子Agent超时(秒)
MSG_TIMEOUT = 15  # 飞书消息发送超时(秒)

# ============ 工具函数 ============

def log(msg):
    """日志输出"""
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{ts}] {msg}", flush=True)
    except UnicodeEncodeError:
        clean = re.sub(r'[\U00010000-\U0010ffff]', '', msg)
        print(f"[{ts}] {clean}", flush=True)


def run_openclaw(args: list, timeout: int = 60) -> tuple[int, str, str]:
    """执行OpenClaw CLI命令"""
    import subprocess

    cmd = [OPENCLAW_CMD] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def send_feishu(text: str) -> bool:
    """发送消息到飞书群"""
    code, stdout, stderr = run_openclaw([
        "message", "send",
        "--channel", "feishu",
        "--account", ACCOUNT,
        "--target", GROUP_ID,
        "--message", text
    ], timeout=MSG_TIMEOUT)

    if code == 0:
        log(f"[飞书发送成功] {text[:50]}...")
        return True
    else:
        log(f"[飞书发送失败] {stderr[:100]}")
        return False


def spawn_agent(agent_id: str, message: str, timeout: int = SPAWN_TIMEOUT) -> str:
    """
    通过sessions_spawn调用Agent（隔离子会话，避免SIGKILL）

    使用 openclaw agent --agent xxx --message "..." --session-id yyy --local
    为每个调用创建新的session-id，避免与主会话冲突
    """
    session_id = f"rt-{agent_id}-{uuid.uuid4().hex[:6]}"

    code, stdout, stderr = run_openclaw([
        "agent",
        "--agent", agent_id,
        "--message", message,
        "--session-id", session_id,
        "--local",
        "--timeout", str(timeout)
    ], timeout=timeout + 10)

    if code == 0 and stdout:
        # 尝试解析JSON获取reply
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                reply = data.get("reply", data.get("text", ""))
                if reply:
                    return clean_reply(reply)
        except json.JSONDecodeError:
            pass

        # 降级：提取最后有效行
        lines = [l.strip() for l in stdout.strip().split('\n') if l.strip()]
        for line in reversed(lines):
            if line and not line.startswith('[info]') and not line.startswith('[plugins]'):
                return clean_reply(line)

    log(f"[{agent_id}] 调用失败: {stderr[:80] if stderr else '无输出'}")
    return ""


def clean_reply(text: str) -> str:
    """清理回复文本"""
    # 移除机器人前缀
    for emoji in EMOJI.values():
        if text.startswith(emoji):
            text = text[len(emoji):].strip()
    # 移除[H]、[F]、[C]等前缀
    text = re.sub(r'^\[[A-Za-z]\]', '', text).strip()
    return text


def call_agent_blocking(agent_id: str, message: str) -> str:
    """
    同步调用Agent（使用独立session-id）
    这是修复SIGKILL问题的关键：每次调用都用新的session-id
    """
    session_id = f"roundtable-{uuid.uuid4().hex[:8]}"

    code, stdout, stderr = run_openclaw([
        "agent",
        "--agent", agent_id,
        "--message", message,
        "--session-id", session_id,
        "--local",
        "--timeout", str(SPAWN_TIMEOUT)
    ], timeout=SPAWN_TIMEOUT + 15)

    if code == 0 and stdout:
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                reply = data.get("reply", data.get("text", ""))
                if reply:
                    return clean_reply(reply)
        except json.JSONDecodeError:
            pass

        lines = [l.strip() for l in stdout.strip().split('\n') if l.strip()]
        for line in reversed(lines):
            if line and not line.startswith('[info]'):
                return clean_reply(line)

    return ""


# ============ 提示词构建 ============

def build_intro_message(topic: str, round_num: int) -> str:
    """构建开场白"""
    return (
        f"🐺 **狼群圆桌会议 第{round_num}轮**\n\n"
        f"议题：{topic}\n\n"
        f"请各位从自己的角色视角发表看法，2-3句话即可。"
    )


def build_speaker_prompt(agent_id: str, round_num: int, topic: str, history: list) -> str:
    """构建发言提示词"""
    speaker = SPEAKERS.get(agent_id, agent_id)

    history_text = ""
    if history:
        history_text = "\n最近发言：\n"
        for rec in history[-6:]:
            history_text += f"{EMOJI.get(rec['agent'], '')} {rec['text'][:80]}\n"

    return (
        f"【圆桌会议 第{round_num}轮】\n"
        f"议题：{topic}\n"
        f"你是{speaker}（{EMOJI.get(agent_id)}），请从你的角色视角发表2-3句看法。\n"
        f"{history_text}"
        f"回复格式：简单陈述你的观点即可，不要使用前缀标记。"
    )


def build_summary_prompt(topic: str, history: list) -> str:
    """构建总结提示词"""
    speaker_text = "\n".join([
        f"{EMOJI.get(rec['agent'], '')} {SPEAKERS.get(rec['agent'], rec['agent'])}: {rec['text'][:150]}"
        for rec in history
    ])

    return (
        f"【总结环节】\n\n"
        f"议题：{topic}\n\n"
        f"讨论内容：\n{speaker_text}\n\n"
        f"请以「🧅 {SPEAKERS['onion']}」身份，用3-5句话总结本次讨论的核心结论。\n"
        f"保持中立，归纳各方观点，给出有价值的洞察。"
    )


def build_vote_prompt(agent_id: str, summary: str) -> str:
    """构建投票提示词"""
    speaker = SPEAKERS.get(agent_id, agent_id)

    return (
        f"【投票环节】\n\n"
        f"请判断以下讨论是否有价值记住？\n\n"
        f"总结：{summary[:200]}\n\n"
        f"你是{speaker}（{EMOJI.get(agent_id)}），\n"
        f"只回复 YES 或 NO，不要解释。"
    )


# ============ 圆桌流程 ============

def run_roundtable_topic(topic: str, num_rounds: int = 2) -> dict:
    """
    运行一轮圆桌会议

    Args:
        topic: 讨论议题
        num_rounds: 发言轮数（默认2轮）

    Returns:
        {"history": [...], "summary": "...", "votes": {...}}
    """
    log(f"=== 圆桌会议开始 | 议题: {topic} ===")

    history = []

    # 第1轮：固定顺序发言（汉堡→薯条→可乐）
    log("--- 第1轮：探索阶段 ---")
    first_round_order = ["hamburger", "fries", "cola"]

    for agent_id in first_round_order:
        prompt = build_speaker_prompt(agent_id, 1, topic, history)
        log(f"[调用 {agent_id}]...")

        reply = call_agent_blocking(agent_id, prompt)

        if reply:
            log(f"[{EMOJI.get(agent_id)}] {reply[:60]}")
            history.append({
                "agent": agent_id,
                "text": reply,
                "ts": datetime.now().isoformat()
            })
        else:
            log(f"[{agent_id}] 无回复")

        time.sleep(2)  # 避免请求过于密集

    # 第2轮起：智能调度（发言最少者优先）
    if num_rounds >= 2:
        log("--- 第2轮：深入阶段 ---")

        # 统计发言次数
        counts = {a: sum(1 for rec in history if rec['agent'] == a) for a in AGENTS}

        # 发言最少者
        next_agent = min(counts, key=counts.get)
        prompt = build_speaker_prompt(next_agent, 2, topic, history)
        log(f"[调用 {next_agent}]...")

        reply = call_agent_blocking(next_agent, prompt)
        if reply:
            log(f"[{EMOJI.get(next_agent)}] {reply[:60]}")
            history.append({
                "agent": next_agent,
                "text": reply,
                "ts": datetime.now().isoformat()
            })

    # 洋葱圈总结
    log("--- 洋葱圈总结 ---")
    summary_prompt = build_summary_prompt(topic, history)
    summary = call_agent_blocking("onion", summary_prompt)

    if not summary:
        summary = "（总结生成失败）"
    else:
        log(f"[🧅] {summary[:80]}")

    # 三Agent投票
    log("--- 投票环节 ---")
    votes = {}
    for agent_id in AGENTS:
        vote_prompt = build_vote_prompt(agent_id, summary)
        vote_reply = call_agent_blocking(agent_id, vote_prompt)

        vote = "YES" if "YES" in vote_reply.upper() else "NO"
        votes[agent_id] = vote
        log(f"[{EMOJI.get(agent_id)} 投票] {vote}")

        time.sleep(1)

    return {
        "topic": topic,
        "history": history,
        "summary": summary,
        "votes": votes,
        "timestamp": datetime.now().isoformat()
    }


def output_to_feishu(result: dict) -> bool:
    """输出结果到飞书"""
    topic = result["topic"]
    history = result["history"]
    summary = result["summary"]
    votes = result["votes"]

    lines = [
        f"🐺 **狼群圆桌会议**",
        f"议题：{topic}",
        "",
        "--- 讨论 ---"
    ]

    for rec in history:
        emoji = EMOJI.get(rec["agent"], "?")
        lines.append(f"{emoji} {SPEAKERS.get(rec['agent'], rec['agent'])}: {rec['text']}")

    lines.extend(["", "--- 总结 ---", f"🧅 {summary}", "", "--- 投票 ---"])

    yes_count = 0
    for agent_id, vote in votes.items():
        emoji = EMOJI.get(agent_id, "?")
        lines.append(f"{emoji} {SPEAKERS.get(agent_id, agent_id)}: {vote}")
        if vote == "YES":
            yes_count += 1

    lines.append(f"\n✅ {yes_count}/3 认为值得记住")

    text = "\n".join(lines)
    return send_feishu(text)


def store_memory(result: dict) -> bool:
    """存储有价值的记忆"""
    yes_count = sum(1 for v in result["votes"].values() if v == "YES")

    if yes_count >= 2:
        target_dir = LONG_TERM_DIR if yes_count >= 3 else SHORT_TERM_DIR
        level = "long" if yes_count >= 3 else "short"

        record = {
            "topic": result["topic"],
            "summary": result["summary"],
            "votes": result["votes"],
            "yes_count": yes_count,
            "timestamp": result["timestamp"],
            "history": [
                {"agent": r["agent"], "text": r["text"]}
                for r in result["history"]
            ]
        }

        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        f = target_dir / f"memory_{date_str}.json"
        f.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"[记忆存储] {level}-term ({yes_count}票) -> {f.name}")
        return True

    return False


# ============ 议题生成 ============

TOPIC_POOL = [
    "AI Agent未来发展方向",
    "多Agent协作最佳实践",
    "Agent记忆持久化策略",
    "狼群战术在AI系统中的应用",
    "垂直深耕 vs 平台战略",
    "AI与人类协作边界",
    "Agent自主决策边界",
    "多模态Agent应用场景",
    "AI可解释性重要性",
    "Agent创造力之问",
]


def generate_topic() -> str:
    """生成议题（简单轮换）"""
    index = int(time.time()) // 3600 % len(TOPIC_POOL)
    return TOPIC_POOL[index]


# ============ 主入口 ============

def main():
    """主入口"""
    log("=" * 50)
    log("洋葱圈圆桌导演 v2.1 启动")
    log("=" * 50)

    # 读取或生成议题
    topic_file = WORK_DIR / "current_topic.txt"
    if topic_file.exists():
        topic = topic_file.read_text(encoding="utf-8").strip()
        if topic:
            log(f"读取议题: {topic}")
        else:
            topic = generate_topic()
    else:
        topic = generate_topic()

    # 运行圆桌
    result = run_roundtable_topic(topic, num_rounds=2)

    # 发送到飞书
    output_to_feishu(result)

    # 存储记忆
    store_memory(result)

    log("=" * 50)
    log("圆桌会议完成")
    log("=" * 50)


if __name__ == "__main__":
    main()
