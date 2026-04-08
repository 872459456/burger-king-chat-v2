"""
飞书交互接口
支持：消息接收、消息发送、用户介入检测、群组管理
"""
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import yaml


class FeishuClient:
    """飞书客户端"""

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.enabled = config.get("enabled", True)
        self.group_id = config.get("group_id", "")
        self.bot_names = config.get("bot_names", ["汉堡", "薯条", "可乐"])
        self.user_keywords = config.get("user_keywords", {})
        
        self.ws_client = None
        self.running = False
        self.message_handler: Optional[Callable] = None
        
        # 用户输入队列
        self.user_input_queue: list[dict] = []
        self.queue_lock = threading.Lock()

    def set_message_handler(self, handler: Callable):
        """设置消息处理器"""
        self.message_handler = handler

    def connect(self):
        """建立WebSocket连接"""
        if not self.enabled:
            self.logger.warning("飞书未启用")
            return
        
        try:
            # TODO: 实现实际的飞书WebSocket连接
            # 参考: https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/server-side-sdk/event-subscription-overview
            self.logger.info("飞书客户端初始化（WebSocket占位）")
        except Exception as e:
            self.logger.error(f"飞书连接失败: {e}")

    def disconnect(self):
        """断开连接"""
        self.running = False
        if self.ws_client:
            self.ws_client.close()
        self.logger.info("飞书客户端已断开")

    def send_message(self, content: str, msg_type: str = "text") -> bool:
        """发送消息到群组"""
        if not self.enabled:
            return False
        
        try:
            # TODO: 实现实际的飞书API调用
            # POST https://open.feishu.cn/open-apis/im/v1/messages
            # 需要：tenant_access_token, group_id, content
            
            self.logger.info(f"[Feishu发送] {content[:50]}...")
            return True
            
        except Exception as e:
            self.logger.error(f"发送消息失败: {e}")
            return False

    def send_text(self, text: str) -> bool:
        """发送文本消息"""
        return self.send_message(json.dumps({"text": text}))

    def _parse_message(self, raw_event: dict) -> Optional[dict]:
        """解析接收到的消息"""
        try:
            # TODO: 根据实际飞书事件格式调整
            event_type = raw_event.get("event", {}).get("type")
            
            if event_type == "im.message.receive_v1":
                message = raw_event["event"]["message"]
                sender = raw_event["event"]["sender"]
                
                # 过滤机器人消息
                if sender.get("sender_type") == "bot":
                    return None
                
                content = json.loads(message.get("content", "{}"))
                
                return {
                    "message_id": message.get("message_id"),
                    "chat_type": message.get("chat_type"),
                    "content": content.get("text", ""),
                    "sender_id": sender.get("sender_id", {}).get("open_id"),
                    "sender_type": sender.get("sender_type"),
                    "timestamp": datetime.now().isoformat()
                }
            
            return None
            
        except Exception as e:
            self.logger.error(f"解析消息失败: {e}")
            return None

    def _is_user_message(self, msg: dict) -> bool:
        """判断是否为用户介入消息"""
        if msg.get("sender_type") == "bot":
            return False
        
        content = msg.get("content", "").strip()
        
        # 过滤空消息
        if len(content) < 2:
            return False
        
        # 过滤纯符号
        import re
        if re.match(r'^[\s\W]+$', content):
            return False
        
        return True

    def _enqueue_user_input(self, msg: dict):
        """将用户输入加入队列"""
        with self.queue_lock:
            self.user_input_queue.append(msg)
            self.logger.info(f"[用户介入] {msg.get('content', '')[:50]}")

    def get_user_input(self) -> Optional[dict]:
        """获取队列中的用户输入"""
        with self.queue_lock:
            if self.user_input_queue:
                return self.user_input_queue.pop(0)
        return None

    def handle_event(self, raw_event: dict):
        """处理收到的事件"""
        msg = self._parse_message(raw_event)
        
        if not msg:
            return
        
        # 用户介入检测
        if self._is_user_message(msg):
            self._enqueue_user_input(msg)
        
        # 调用消息处理器
        if self.message_handler:
            try:
                self.message_handler(msg)
            except Exception as e:
                self.logger.error(f"消息处理失败: {e}")

    def start_listening(self):
        """开始监听消息"""
        if not self.enabled:
            return
        
        self.running = True
        self.logger.info("飞书消息监听启动")
        
        # TODO: 实现实际的WebSocket事件循环
        # 伪代码:
        # while self.running:
        #     event = self.ws_client.recv()
        #     self.handle_event(event)
        #     time.sleep(0.1)
        
        while self.running:
            time.sleep(1)

    def stop_listening(self):
        """停止监听"""
        self.running = False


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("test")
    
    config = {
        "enabled": False,
        "group_id": "oc_test",
        "bot_names": ["汉堡", "薯条", "可乐"]
    }
    
    client = FeishuClient(config, logger)
    client.connect()
    
    # 测试发送
    client.send_text("🍔 汉堡王系统测试消息")
