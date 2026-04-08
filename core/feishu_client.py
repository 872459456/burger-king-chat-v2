"""
飞书交互接口
基于 larksuiteoapi SDK，支持：消息接收、消息发送、用户介入检测
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import yaml


def run_openclaw(command: list, timeout: int = 30) -> tuple[int, str, str]:
    """执行 OpenClaw CLI 命令"""
    import subprocess
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


class FeishuClient:
    """飞书客户端 - 基于 OpenClaw 消息接口"""

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.enabled = config.get("enabled", True)
        self.group_id = config.get("group_id", "")
        self.group_name = config.get("group_name", "")
        self.account = config.get("account", "main")
        self.bot_names = set(config.get("bot_names", []))
        self.user_keywords = config.get("user_keywords", {})

        self._poll_thread: Optional[threading.Thread] = None
        self._running = False
        self.message_handler: Optional[Callable] = None
        self.user_input_queue: list[dict] = []
        self._queue_lock = threading.Lock()

        self._last_message_time: float = time.time()

    def set_message_handler(self, handler: Callable):
        """设置消息处理器"""
        self.message_handler = handler

    def send_message(self, content: str) -> bool:
        """发送文本消息到飞书群"""
        if not self.enabled:
            return False

        cmd = [
            "openclaw", "message", "send",
            "--channel", "feishu",
            "--account", self.account,
            "--target", self.group_id,
            "--message", content
        ]

        code, stdout, stderr = run_openclaw(cmd, timeout=30)

        if code == 0:
            self.logger.info(f"[Feishu发送] {content[:50]}...")
            return True
        else:
            self.logger.error(f"[Feishu] 发送失败: {stderr}")
            return False

    def send_text(self, text: str) -> bool:
        """发送文本（别名）"""
        return self.send_message(text)

    def _poll_messages(self):
        """轮询飞书消息"""
        self.logger.info("[Feishu] 消息轮询线程启动")

        while self._running:
            try:
                messages = self._read_recent_messages(limit=10)
                for msg in messages:
                    self._process_message(msg)
            except Exception as e:
                self.logger.error(f"[Feishu] 轮询异常: {e}")

            time.sleep(5)  # 每5秒轮询一次

        self.logger.info("[Feishu] 消息轮询线程退出")

    def _read_recent_messages(self, limit: int = 10) -> list[dict]:
        """读取最近消息"""
        cmd = [
            "openclaw", "message", "read",
            "--channel", "feishu",
            "--account", self.account,
            "--limit", str(limit)
        ]

        code, stdout, stderr = run_openclaw(cmd, timeout=15)

        if code != 0 or not stdout:
            return []

        messages = []
        try:
            # 尝试解析 JSON
            data = json.loads(stdout)
            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict) and "messages" in data:
                messages = data["messages"]
        except json.JSONDecodeError:
            # 降级：按行解析
            for line in stdout.strip().split("\n"):
                line = line.strip()
                if line and not self._is_bot_message_text(line):
                    messages.append({"content": line, "time": time.time()})

        return messages

    def _is_bot_message_text(self, text: str) -> bool:
        """判断是否为机器人消息"""
        text = text.strip()
        if not text:
            return True
        # 以 bot 名称开头的是机器人消息
        for bot in self.bot_names:
            if text.startswith(f"[{bot}]") or text.startswith(f"{bot}："):
                return True
        # 系统消息特征
        if any(text.startswith(x) for x in ["🐺", "🏁", "📊", "💾", "📋", "🍔", "🍟", "🥤"]):
            return True
        if "圆桌会议" in text and ("开始" in text or "结束" in text):
            return True
        return False

    def _is_valuable_user_message(self, msg: dict) -> bool:
        """判断是否为有价值的用户消息"""
        content = msg.get("content", "").strip()

        if len(content) < 2:
            return False

        # 过滤纯符号
        import re
        if re.match(r'^[\s\W]+$', content):
            return False

        # 过滤机器人消息
        if self._is_bot_message_text(content):
            return False

        # 检查是否在可接受的时间窗口内（避免处理历史消息）
        msg_time = msg.get("time", time.time())
        if time.time() - msg_time > 300:  # 5分钟前的消息
            return False

        return True

    def _process_message(self, msg: dict):
        """处理单条消息"""
        if not self._is_valuable_user_message(msg):
            return

        content = msg.get("content", "")
        sender = msg.get("sender", "unknown")

        with self._queue_lock:
            self.user_input_queue.append({
                "content": content,
                "sender": sender,
                "timestamp": datetime.now().isoformat()
            })

        self.logger.info(f"[用户介入] {content[:50]}")

        if self.message_handler:
            try:
                self.message_handler(msg)
            except Exception as e:
                self.logger.error(f"消息处理失败: {e}")

    def get_user_input(self) -> Optional[dict]:
        """获取队列中的用户输入"""
        with self._queue_lock:
            if self.user_input_queue:
                return self.user_input_queue.pop(0)
        return None

    def start_listening(self):
        """启动消息监听"""
        if not self.enabled:
            self.logger.warning("飞书未启用，跳过监听")
            return

        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_messages, daemon=True)
        self._poll_thread.start()
        self.logger.info("飞书消息监听已启动")

    def stop_listening(self):
        """停止消息监听"""
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
        self.logger.info("飞书消息监听已停止")

    def handle_vote_keyword(self, content: str) -> Optional[str]:
        """解析投票关键词"""
        content_lower = content.lower()
        for keyword, vote in self.user_keywords.items():
            if keyword in content:
                return vote
        return None


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("test")

    config = {
        "enabled": True,
        "account": "main",
        "group_id": "oc_9ea914f5ad7acbd9061c915a0f942d5c",
        "group_name": "汉堡王",
        "bot_names": ["汉堡", "薯条", "可乐"],
        "user_keywords": {"有价值": "有价值", "无价值": "无价值"}
    }

    client = FeishuClient(config, logger)
    client.start_listening()

    time.sleep(3)
    client.stop_listening()

    print("测试完成")
