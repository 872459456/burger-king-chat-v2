"""
洋葱圈圆桌导演 v2.2 - 使用sessions_spawn实现

核心原理: 洋葱圈(导演) + sessions_spawn(隔离子会话)调用Agent

关键修复：
- 使用 sessions_spawn runtime="subagent" 创建真正隔离的子会话
- 避免session文件锁冲突（SIGKILL问题根因）
- 通过Gateway API直接通信
"""

import json
import os
import re
import sys
import time
import uuid
import urllib.request
import urllib.parse
import ssl
from datetime import datetime
from pathlib import Path

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

# Gateway配置
GATEWAY_PORT = 18789
GATEWAY_TOKEN = ""  # 从配置文件读取

# Timeout设置
SPAWN_TIMEOUT = 90  # 子Agent超时(秒)
MSG_TIMEOUT = 15  # 飞书消息发送超时(秒)

# ============ 读取Gateway Token ============

def load_gateway_token() -> str:
    """从配置文件读取Gateway token"""
    cfg_path = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "openclaw" / "config" / "gateway.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            return cfg.get("gateway", {}).get("auth", {}).get("token", "")
        except:
            pass
    return ""


# ============ Gateway API ============

def gateway_api(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """调用Gateway API"""
    global GATEWAY_TOKEN
    if not GATEWAY_TOKEN:
        GATEWAY_TOKEN = load_gateway_token()

    url = f"http://localhost:{GATEWAY_PORT}{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GATEWAY_TOKEN}"
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers=headers,
        method=method
    )

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def sessions_spawn(agent_id: str, task: str, timeout: int = 90) -> dict:
    """
    使用sessions_spawn创建隔离子会话调用Agent

    返回: {"ok": true, "sessionKey": "...", "reply": "..."}
    """
    result = gateway_api(
        "/api/sessions/spawn",
        method="POST",
        data={
            "runtime": "subagent",
            "agentId": agent_id,
            "task": task,
            "runTimeoutSeconds": timeout
        }
    )
    return result


def send_feishu(text: str) -> bool:
    """发送消息到飞书群"""
    result = gateway_api(
        "/api/message/send",
        method="POST",
        data={
            "channel": "feishu",
            "account": ACCOUNT,
            "target": GROUP_ID,
            "message": text
        }
    )
    return result.get("ok", False)


# ============ 工具函数 ============

def log(msg: str):
    """日志输出"""
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{ts}] {msg}", flush=True)
    except UnicodeEncodeError:
        clean = re.sub(r'[\U00010000-\U0010ffff]', '', msg)
        print(f"[{ts}] {clean}", flush=True)


def clean_reply(text: str) -> str:
    """清理回复文本"""
    # 移除机器人前缀
    for emoji in EMOJI.values():
        if emoji in text:
            text = text.replace(emoji, "").strip()
    # 移除[H]、[F]、[C]等前缀
    text = re.sub(r'^\[[A-Za-z]\]', '', text).strip()
    return text


# ============ 提示词构建 ============

def build_speaker_prompt(agent_id: str, round_num: int, topic: str, history: list) -> str:
    """构建发言提示词"""
    speaker = SPEAKERS.get(agent_id, agent_id)

    history_text = ""
    if history:
        history_text = "\n最近发言：\n"
        for rec in history[-6:]:
            emoji = EMOJI.get(rec['agent'], '')
            history_text += f"{emoji} {rec['text'][:80]}\n"

    return (
        f"【圆桌会议 第{round_num}轮】\n"
        f"议题：{topic}\n"
        f"你是{speaker}（{EMOJI.get(agent_id)}），请从你的角色视角发表2-3句看法。\n"
        f"{history_text}"
        f"回复格式：简单陈述你的观点即可。"
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

        result = sessions_spawn(agent_id, prompt, timeout=SPAWN_TIMEOUT)

        if result.get("ok"):
            reply = result.get("reply", "")
            reply = clean_reply(reply)
            if reply:
                log(f"[{EMOJI.get(agent_id)}] {reply[:60]}")
                history.append({
                    "agent": agent_id,
                    "text": reply,
                    "ts": datetime.now().isoformat()
                })
            else:
                log(f"[{agent_id}] 空回复")
        else:
            log(f"[{agent_id}] 调用失败: {result.get('error', 'unknown')}")

        time.sleep(2)

    # 第2轮起：智能调度（发言最少者优先）
    if num_rounds >= 2:
        log("--- 第2轮：深入阶段 ---")

        # 统计发言次数
        counts = {a: sum(1 for rec in history if rec['agent'] == a) for a in AGENTS}

        # 发言最少者
        next_agent = min(counts, key=counts.get)
        prompt = build_speaker_prompt(next_agent, 2, topic, history)
        log(f"[调用 {next_agent}]...")

        result = sessions_spawn(next_agent, prompt, timeout=SPAWN_TIMEOUT)

        if result.get("ok"):
            reply = clean_reply(result.get("reply", ""))
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

    # 洋葱圈使用自己的session
    result = sessions_spawn("onion", summary_prompt, timeout=SPAWN_TIMEOUT)
    summary = clean_reply(result.get("reply", "")) if result.get("ok") else "（总结生成失败）"

    if summary and summary != "（总结生成失败）":
        log(f"[🧅] {summary[:80]}")
    else:
        summary = "（总结生成失败）"
        log(f"[🧅] {summary}")

    # 三Agent投票
    log("--- 投票环节 ---")
    votes = {}
    for agent_id in AGENTS:
        vote_prompt = build_vote_prompt(agent_id, summary)
        vote_result = sessions_spawn(agent_id, vote_prompt, timeout=60)

        if vote_result.get("ok"):
            vote_reply = clean_reply(vote_result.get("reply", ""))
            vote = "YES" if "YES" in vote_reply.upper() else "NO"
        else:
            vote = "NO"
            vote_reply = ""

        votes[agent_id] = vote
        log(f"[{EMOJI.get(agent_id)} 投票] {vote} ({vote_reply[:30]})")

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
        speaker = SPEAKERS.get(rec["agent"], rec["agent"])
        lines.append(f"{emoji} {speaker}: {rec['text']}")

    lines.extend(["", "--- 总结 ---", f"🧅 {summary}", "", "--- 投票 ---"])

    yes_count = 0
    for agent_id, vote in votes.items():
        emoji = EMOJI.get(agent_id, "?")
        speaker = SPEAKERS.get(agent_id, agent_id)
        lines.append(f"{emoji} {speaker}: {vote}")
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
    log("洋葱圈圆桌导演 v2.2 启动 (sessions_spawn)")
    log("=" * 50)

    # 测试Gateway连接
    test = gateway_api("/api/status")
    if "error" in test and "Unauthorized" not in str(test.get("error", "")):
        log(f"[警告] Gateway连接: {test.get('error', 'unknown')}")
    else:
        log("[OK] Gateway连接正常")

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
    if output_to_feishu(result):
        log("[OK] 飞书发送成功")
    else:
        log("[错误] 飞书发送失败")

    # 存储记忆
    store_memory(result)

    log("=" * 50)
    log("圆桌会议完成")
    log("=" * 50)


if __name__ == "__main__":
    main()
