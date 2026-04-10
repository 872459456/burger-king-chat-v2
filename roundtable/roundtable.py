#!/usr/bin/env python3
# roundtable.py - 圆桌会议脚本（洋葱圈智能导演模式）
# 洋葱圈作为导演，智能决定发言者和调度顺序
import sys
import os
import time
import json
import re
from datetime import datetime

# 配置
LOG = r"D:\works\Project\burger-king-chat-v2\roundtable\logs"
GID = "oc_9ea914f5ad7acbd9061c915a0f942d5c"
MAX_TURNS = 6  # 最大轮次

def get_timestamp():
    return datetime.now().strftime("%H:%M")

def send_feishu(message):
    """发送消息到飞书（通过PowerShell脚本）"""
    ps_script = r"D:\works\Project\burger-king-chat-v2\roundtable\send2feishu.ps1"
    
    msg_file = os.path.join(LOG, "feishu_msg.txt")
    with open(msg_file, 'w', encoding='utf-8') as f:
        f.write(message)
    
    import subprocess
    cmd = ['powershell', '-ExecutionPolicy', 'Bypass', '-File', ps_script]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30
        )
        output = (result.stdout or b"") + (result.stderr or b"")
        try:
            text = output.decode('utf-8', errors='replace')
        except:
            text = output.decode('gbk', errors='replace')
        
        if '"ok": true' in text:
            print(f"Feishu sent OK")
            return True
        else:
            print(f"Feishu response: {text[:200]}")
            return False
    except Exception as e:
        print(f"Feishu error: {e}")
        return False

def cleanup_agent_session(agent):
    """清理指定agent的session，防止session卡住导致无响应"""
    session_file = f"C:\\Users\\Administrator\\.openclaw\\agents\\{agent}\\sessions\\sessions.json"
    
    if os.path.exists(session_file):
        try:
            # 检查文件大小，如果太大说明可能有问题
            size = os.path.getsize(session_file)
            if size > 100000:  # 超过100KB
                print(f"[清理] {agent} session文件过大({size} bytes)，清理中...")
                os.remove(session_file)
                print(f"[清理] {agent} session已清理")
                return True
        except Exception as e:
            print(f"[清理] {agent} 清理失败: {e}")
    return False

def ensure_agent_responsive(agent):
    """确保agent可以响应，必要时清理session"""
    import subprocess
    
    # 先尝试调用一次快速检测
    openclaw_path = os.path.expandvars(r"%APPDATA%\npm\openclaw.cmd")
    test_cmd = [openclaw_path, "agent", "--agent", agent, "--message", "ping", "--json"]
    
    try:
        result = subprocess.run(
            test_cmd,
            capture_output=True,
            timeout=20,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        output = (result.stdout or "") + (result.stderr or "")
        
        # 检查输出是否包含有效响应
        try:
            data = json.loads(output)
            payloads = data.get("result", {}).get("payloads", [])
            if payloads and any(p.get("type") == "text" for p in payloads if isinstance(p, dict)):
                return True  # agent正常
        except:
            pass
        
        # 如果没有有效响应，清理session
        print(f"[检测] {agent} 响应异常，尝试清理...")
        cleanup_agent_session(agent)
        
        # 再试一次
        result = subprocess.run(
            test_cmd,
            capture_output=True,
            timeout=20,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        output = (result.stdout or "") + (result.stderr or "")
        
        try:
            data = json.loads(output)
            payloads = data.get("result", {}).get("payloads", [])
            if payloads and any(p.get("type") == "text" for p in payloads if isinstance(p, dict)):
                print(f"[检测] {agent} 清理后恢复正常")
                return True
        except:
            pass
        
        print(f"[检测] {agent} 可能仍然异常")
        return False
        
    except Exception as e:
        print(f"[检测] {agent} 检测失败: {e}")
        return False

def call_agent(agent, prompt, timeout=70):
    """调用openclaw agent获取回复"""
    out_file = os.path.join(LOG, f"{agent}_reply.txt")
    
    import subprocess
    import json
    
    try:
        openclaw_path = os.path.expandvars(r"%APPDATA%\npm\openclaw.cmd")
        result = subprocess.run(
            [openclaw_path, "agent", "--agent", agent, "--message", prompt, "--json"],
            capture_output=True,
            timeout=timeout + 10,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        
        output = (result.stdout or "") + (result.stderr or "")
        
        # 尝试从JSON提取实际回复文本
        try:
            data = json.loads(output)
            payloads = data.get("result", {}).get("payloads", [])
            for p in payloads:
                if isinstance(p, dict) and p.get("type") == "text":
                    text = p.get("content", "")
                    if text.strip():
                        with open(out_file, "w", encoding="utf-8") as f:
                            f.write(text)
                        return text
            # 检查summary
            if data.get("summary") and "completed" not in data["summary"].lower():
                with open(out_file, "w", encoding="utf-8") as f:
                    f.write(data["summary"])
                return data["summary"]
        except:
            pass
        
        # 回退：保存原始输出
        with open(out_file, "w", encoding="utf-8", errors="replace") as f:
            f.write(output)
        
        return output
        
    except subprocess.TimeoutExpired:
        print(f"[{agent}] timeout")
        return ""
    except Exception as e:
        print(f"[{agent}] error: {e}")
        return ""

def extract_content(text):
    """从agent输出中提取回复内容"""
    if not text:
        return ""
    
    # 清理ANSI转义
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    text = re.sub(r'\bcompleted\b', '', text, flags=re.IGNORECASE)
    
    # 移除开头和结尾的无用行
    lines = text.strip().split('\n')
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('[') and ('%' in line or '✓' in line):
            continue
        if 'node' in line.lower() or 'error' in line.lower() or 'timeout' in line.lower():
            continue
        if len(line) > 5:
            cleaned_lines.append(line)
    
    result = ' '.join(cleaned_lines)
    
    # 如果结果太短，从文件读取
    if len(result) < 30:
        LOG_LOCAL = r"D:\works\Project\burger-king-chat-v2\roundtable\logs"
        out_file = os.path.join(LOG_LOCAL, "cola_reply.txt")
        if os.path.exists(out_file):
            with open(out_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            content = re.sub(r'\x1b\[[0-9;]*m', '', content)
            matches = re.findall(r'\*\*[^*]+\*\*[^\n]*', content)
            if matches:
                result = ' '.join(matches)
    
    return result[:800] if result else ""

def build_discussion_state(history):
    """构建当前讨论状态"""
    if not history:
        return "暂无历史记录"
    
    lines = []
    for i, turn in enumerate(history, 1):
        speaker = turn.get("speaker", "未知")
        content = turn.get("content", "")
        if content and content != "[无响应]":
            lines.append(f"第{i}轮 {speaker}：{content[:150]}...")
    
    return "\n".join(lines) if lines else "暂无有效历史记录"

def onion_decide(topic, history, available_agents, turn_num):
    """让洋葱圈决定下一步调度"""
    
    state = build_discussion_state(history)
    
    # 根据轮次选择下一个agent的默认逻辑
    if turn_num == 0:
        default_next = "汉堡"
        default_prompt = f"议题：{topic}\n\n作为圆桌第一位发言人，请从你的角色视角（执行协调）开场，提出核心观点，150字以内。"
        default_end = "no"
    elif turn_num == 1:
        default_next = "薯条"
        default_prompt = f"议题：{topic}\n\n作为智囊，请对前一位发言人的观点进行深度分析或补充，150字以内。"
        default_end = "no"
    elif turn_num == 2:
        default_next = "可乐"
        default_prompt = f"议题：{topic}\n\n作为执行者，请从落地实践角度补充观点或提出行动建议，150字以内。"
        default_end = "no"
    else:
        default_next = None
        default_prompt = ""
        default_end = "yes"  # 3轮后默认总结
    
    # 尝试让洋葱圈做智能决策
    prompt = f"""你是洋葱圈，圆桌导演。

议题: {topic}
当前第 {turn_num + 1} 轮
可用发言者: {', '.join(available_agents)}
历史: {state[:300] if state else '暂无'}

**输出要求** - 只需输出3行，不要其他内容：
1. 第一行：下一个发言者名字（汉堡/薯条/可乐/洋葱圈）
2. 第二行：给该发言者的提示词（50字以内，简洁直接）
3. 第三行：yes表示讨论结束，no表示继续

不要生成发言内容，只做调度决策。"""

    print(f"[洋葱圈] 分析第 {turn_num + 1} 轮调度...")
    
    response = call_agent("onion", prompt, timeout=45)
    content = extract_content(response)
    
    # 解析响应
    lines = content.strip().split('\n') if content else []
    lines = [l.strip() for l in lines if l.strip()]
    
    next_agent = None
    agent_prompt = ""
    should_end = turn_num >= 3  # 默认3轮后结束
    
    for line in lines:
        line_lower = line.lower()
        if '汉堡' in line and next_agent is None:
            next_agent = "汉堡"
            # 提取提示词（冒号后面的内容）
            if '：' in line or ':' in line:
                parts = line.split('：') if '：' in line else line.split(':')
                if len(parts) > 1:
                    agent_prompt = parts[1].strip()
        elif '薯条' in line and next_agent is None:
            next_agent = "薯条"
            if '：' in line or ':' in line:
                parts = line.split('：') if '：' in line else line.split(':')
                if len(parts) > 1:
                    agent_prompt = parts[1].strip()
        elif '可乐' in line and next_agent is None:
            next_agent = "可乐"
            if '：' in line or ':' in line:
                parts = line.split('：') if '：' in line else line.split(':')
                if len(parts) > 1:
                    agent_prompt = parts[1].strip()
        elif '结束' in line_lower or '总结' in line_lower:
            should_end = True
        elif next_agent and not agent_prompt:
            # 这行可能是提示词
            if len(line) > 10 and len(line) < 100:
                agent_prompt = line
    
    # 使用默认值
    if not next_agent:
        next_agent = default_next
        agent_prompt = default_prompt
        should_end = default_end == "yes"
    
    if not agent_prompt:
        agent_prompt = default_prompt
    
    print(f"[洋葱圈] 决策: {next_agent} | 结束: {should_end}")
    
    return {
        "next_agent": next_agent,
        "prompt": agent_prompt,
        "should_end": should_end
    }

def run_speaker(agent_name, prompt):
    """运行指定发言者"""
    speaker_map = {
        "汉堡": ("cola", "🍔 汉堡"),
        "薯条": ("cola", "🍟 薯条"),
        "可乐": ("cola", "🥤 可乐"),
        "洋葱圈": ("onion", "🧅 洋葱圈")
    }
    
    if agent_name not in speaker_map:
        print(f"[错误] 未知Agent: {agent_name}")
        return None
    
    agent_id, speaker_label = speaker_map[agent_name]
    
    # 在调用前检测/清理session
    if agent_id != "onion":  # onion不需要清理
        ensure_agent_responsive(agent_id)
    
    print(f"\n[发言] {speaker_label} 发言中...")
    
    response = call_agent(agent_id, prompt, timeout=70)
    content = extract_content(response)
    
    if content:
        print(f"[发言] {speaker_label}: {content[:80]}...")
        return {"speaker": speaker_label, "content": content}
    else:
        print(f"[发言] {speaker_label} 无响应")
        return {"speaker": speaker_label, "content": "[无响应]"}

def main():
    if len(sys.argv) < 2:
        print("Usage: roundtable.py <topic>")
        return
    
    TOPIC = sys.argv[1]
    print(f"[Roundtable] 议题: {TOPIC}")
    print(f"[Roundtable] 模式: 洋葱圈智能导演")
    print(f"[Roundtable] 最大轮次: {MAX_TURNS}")
    
    history = []
    available_agents = ["汉堡", "薯条", "可乐"]
    
    # 洋葱圈开场引导
    print("\n[洋葱圈] 开场引导中...")
    intro_prompt = f"""议题是：{TOPIC}

请以圆桌主持人身份开场，简短介绍议题背景，设定讨论方向（2-3个切入角度），然后邀请汉堡先发言。

开场格式：
🧅 洋葱圈：[你的开场白，包括对议题的简要介绍和切入角度]

然后邀请：首先请🍔汉堡从执行协调的角度谈谈他的看法。"""
    
    intro_response = call_agent("onion", intro_prompt, timeout=70)
    intro_content = extract_content(intro_response)
    
    if intro_content:
        history.append({"speaker": "🧅 洋葱圈", "content": intro_content})
        print(f"[洋葱圈] 开场完成")
    else:
        print(f"[洋葱圈] 开场失败，使用默认开场")
        default_intro = f"议题是：{TOPIC}。这个问题涉及多个层面，请各位从不同角度分享看法。"
        history.append({"speaker": "🧅 洋葱圈", "content": default_intro})
    
    # 智能调度循环
    for turn in range(MAX_TURNS):
        print(f"\n=== 第 {turn + 1} 轮调度 ===")
        
        # 让洋葱圈决定下一步
        decision = onion_decide(TOPIC, history, available_agents, turn)
        
        if decision["should_end"] and turn >= 2:  # 至少2轮后才允许结束
            print(f"[洋葱圈] 决定结束讨论")
            break
        
        next_agent = decision["next_agent"]
        agent_prompt = decision["prompt"]
        
        if not next_agent or not agent_prompt:
            print(f"[洋葱圈] 决策无效，使用默认调度")
            default_schedule = ["汉堡", "薯条", "可乐", "洋葱圈"]
            next_agent = default_schedule[min(turn, len(default_schedule) - 1)]
            agent_prompt = f"议题：{TOPIC}\n\n请分享你的观点。"
        
        # 运行发言者
        turn_result = run_speaker(next_agent, agent_prompt)
        if turn_result:
            history.append(turn_result)
        
        time.sleep(2)
    
    # 洋葱圈总结
    print("\n[洋葱圈] 生成最终总结...")
    summary_prompt = f"""议题：{TOPIC}

讨论历史：
{build_discussion_state(history)}

请作为洋葱圈导演，总结本次讨论的核心观点、共识和结论。格式：
🧅 洋葱圈总结：
[总结内容]"""
    
    summary_response = call_agent("onion", summary_prompt, timeout=70)
    summary_content = extract_content(summary_response)
    
    if summary_content:
        history.append({"speaker": "🧅 洋葱圈", "content": summary_content})
    else:
        # 默认总结
        default_summary = f"议题「{TOPIC}」讨论完成。感谢各位参与。"
        history.append({"speaker": "🧅 洋葱圈", "content": default_summary})
    
    # 构建并发送消息
    time_str = get_timestamp()
    intro = f"🐺 圆桌会议 #{time_str} | 议题：{TOPIC}"
    
    msg_parts = [intro]
    for turn_info in history:
        msg_parts.append(f"\n\n{turn_info['speaker']}：\n{turn_info['content']}")
    
    full_msg = "\n".join(msg_parts)
    
    print(f"\n[完整消息]\n{full_msg}\n")
    
    # 发送到飞书
    print(f"[发送到飞书...]")
    success = send_feishu(full_msg)
    
    # 保存到文件
    with open(os.path.join(LOG, "roundtable_full.txt"), 'w', encoding='utf-8') as f:
        f.write(full_msg)
    
    if success:
        print(f"[Roundtable] 完成 - 已发送到飞书")
        # 更新下一议题（伪随机选择，避免重复）
        next_topics = [
            "AI Agent的记忆机制设计",
            "多Agent系统的信任传递",
            "狼群战术的边界与局限",
            "AI Agent的情感模拟是否必要",
            "AGI时代的职业分工展望"
        ]
        import random
        next_topic = random.choice([t for t in next_topics if t != TOPIC])
        topic_file = os.path.join(LOG, "..", "current_topic.txt")
        with open(topic_file, 'w', encoding='utf-8') as f:
            f.write(next_topic)
        print(f"[议题] 下一议题已更新为: {next_topic}")
    else:
        print(f"[Roundtable] 完成 - 飞书发送失败")

if __name__ == "__main__":
    main()
