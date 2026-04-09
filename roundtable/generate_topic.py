#!/usr/bin/env python3
# generate_topic.py - 三Agent轮流生成话题
import sys
import os
import json
import subprocess
import time
import re

LOG = r"D:\works\Project\burger-king-chat-v2\roundtable\logs"
OPENCLAW = os.path.expanduser(r"~\AppData\Roaming\npm\node_modules\openclaw\openclaw.mjs")
TOPIC_FILE = os.path.join(LOG, "topic.txt")

def run_agent(agent, prompt, timeout=50):
    out_file = os.path.join(LOG, f"topic_{agent}.txt")
    
    cmd = [
        "node", OPENCLAW, "agent",
        "--agent", agent,
        "--message", prompt,
        "--timeout", str(timeout)
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout + 10,
            cwd=LOG
        )
        output = (result.stdout or b"") + (result.stderr or b"")
        try:
            text = output.decode("utf-8", errors="replace")
        except:
            text = output.decode("gbk", errors="replace")
        
        with open(out_file, "w", encoding="utf-8", errors="replace") as f:
            f.write(text)
        return text
    except Exception as e:
        print(f"Error: {e}")
        return ""

def extract_topic(text):
    if not text:
        return ""
    
    # Find quoted text first
    for match in re.finditer(r'"([^"]{4,25})"', text):
        return match.group(1)
    
    # Remove [F] [C] [H] prefixes and clean up
    lines = text.split("\n")
    for line in lines:
        line = re.sub(r'^\[[FCHe]\]\s*', '', line).strip()
        if len(line) >= 4 and not line.startswith("error") and not line.startswith("node"):
            # Further clean - remove any remaining prefixes
            line = re.sub(r'^[A-Za-z]+\s*:?\s*', '', line)
            if len(line) >= 4:
                return line[:25]
    return ""

def main():
    topics = []
    
    prompts = {
        "fries": '"AI Agent的自我意识边界"',
        "cola": 'AI Agent如何在职场中提升效率'
    }
    
    print("=== Topic Generation ===")
    
    for agent, prompt in prompts.items():
        print(f"[{agent}] generating...")
        reply = run_agent(agent, prompt)
        topic = extract_topic(reply)
        print(f"[{agent}] topic: {topic}")
        if topic and not topic.startswith("error"):
            topics.append(topic)
        time.sleep(3)
    
    chosen = topics[0] if topics else "AI Agent的未来协作模式"
    print(f"\n[chosen] {chosen}")
    
    # Save
    with open(TOPIC_FILE, "w", encoding="utf-8") as f:
        f.write(chosen)
    
    with open(os.path.join(LOG, "topic.json"), "w", encoding="utf-8") as f:
        json.dump({
            "topic": chosen,
            "all": topics,
            "timestamp": time.time()
        }, f, ensure_ascii=False)
    
    print(f"[done] {chosen}")

if __name__ == "__main__":
    main()
