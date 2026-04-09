"""
圆桌会议核心调度脚本
支持：轮转调度、上下文注入、角色扮演、投票协调、记忆存储、知识检索
"""

import json
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


def _configure_utf8_env():
    """配置 UTF-8 环境（Windows 兼容）"""
    if sys.platform == "win32":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_configure_utf8_env()


def run_openclaw(command: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """执行 OpenClaw CLI 命令"""
    import shutil

    if command[0] == "openclaw":
        npm_path = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm")
        command[0] = str(Path(npm_path) / "openclaw.cmd")
        if not Path(command[0]).exists():
            command[0] = str(Path(npm_path) / "openclaw.CMD")

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timeout"
    except Exception as e:
        return -1, "", str(e)


class OpenClawClient:
    """OpenClaw API 客户端 - 通过 CLI 调用"""

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.agents = {
            a["name"]: a for a in config.get("openclaw", {}).get("agents", [])
        }
        self.fallback_target = config.get("feishu", {}).get("group_id", "") or ""

    def call_agent(
        self,
        agent_name: str,
        message: str,
        system_prompt: str = "",
        timeout: int = 120,
        session_id: str = None,
    ) -> str:
        """调用 Agent 获取回复"""
        cmd = [
            "openclaw",
            "agent",
            "--agent",
            agent_name,
            "--message",
            message,
            "--local",
        ]

        if session_id:
            cmd.extend(["--session-id", session_id])

        if system_prompt:
            pass

        self.logger.info(f"[OpenClaw] 调用 {agent_name}: {message[:80]}...")

        code, stdout, stderr = run_openclaw(cmd, timeout)

        self.logger.info(
            f"[OpenClaw] code={code}, stdout长度={len(stdout)}, stderr长度={len(stderr)}"
        )
        self.logger.info(f"[OpenClaw] stdout原始: {repr(stdout[:100])}")
        if stderr:
            self.logger.info(f"[OpenClaw] stderr: {stderr[:300]}")

        if code == 0 and stdout:
            try:
                data = json.loads(stdout)
                if isinstance(data, dict):
                    reply = data.get("reply", data.get("text", ""))
                    self.logger.info(f"[OpenClaw] JSON解析成功, reply长度={len(reply)}")
                    return reply if reply else stdout.strip()
                return stdout.strip()
            except json.JSONDecodeError:
                return stdout.strip()
        else:
            self.logger.error(f"[OpenClaw] 调用失败: {stderr}")
            return f"[调用失败: {stderr}]"

    def send_message(
        self,
        message: str,
        channel: str = "feishu",
        account: str = "main",
        target: str = None,
    ) -> bool:
        """发送消息到指定渠道"""
        target = target or self.fallback_target

        cmd = [
            "openclaw",
            "message",
            "send",
            "--channel",
            channel,
            "--account",
            account,
            "--target",
            target,
            "--message",
            message,
        ]

        self.logger.info(f"[Feishu] 发送消息: {message[:80]}...")

        code, stdout, stderr = run_openclaw(cmd, timeout=30)

        if code == 0:
            return True
        else:
            self.logger.error(f"[Feishu] 发送失败: {stderr}")
            return False


class State:
    """状态机状态定义"""

    IDLE = "idle"
    DISCUSSING = "discussing"
    SUMMARIZING = "summarizing"
    VOTING = "voting"
    COMPLETED = "completed"
    ERROR = "error"


class Roundtable:
    """汉堡王圆桌会议核心调度器 - 状态机模式"""

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.openclaw = OpenClawClient(config, logger)
        self.feishu = FeishuClient(config["feishu"], logger)

        self.topic: str = "auto"
        self.turns: int = 10
        self.history: list[dict] = []
        self.turn_index: int = 0
        self.session_id: str = str(uuid.uuid4())[:8]
        self.status: str = State.IDLE

        from core.memory_store import MemoryStore
        from core.knowledge_base import KnowledgeBase

        self.voting_module = VotingModule(config["voting"], self.openclaw, logger)
        self.memory_module = MemoryStore(config["memory"], logger)
        self.knowledge_module = KnowledgeBase(config["knowledge_base"], logger)

        self._state_handlers = {
            State.IDLE: self._handle_idle,
            State.DISCUSSING: self._handle_discussing,
            State.SUMMARIZING: self._handle_summarizing,
            State.VOTING: self._handle_voting,
        }

    def _build_system_prompt(self, agent_name: str) -> str:
        """构建 Agent 系统提示词"""
        agent_config = self.openclaw.agents.get(agent_name)
        if not agent_config:
            return ""
        return agent_config.get("system_prompt", "")

    def _get_turn_order(self) -> list[str]:
        """获取轮转顺序"""
        return ["fries", "cola", "hamburger"]

    def _build_turn_prompt(self, agent_name: str, turn: int) -> str:
        """构建单轮发言提示词"""
        role_map = {a["name"]: a["role"] for a in self.config["openclaw"]["agents"]}
        role_instructions = {
            "hamburger": "作为主持，请主动推进讨论，提出关键问题，引导团队达成共识。",
            "fries": "作为智囊，请提供3个深度分析观点，指出风险和机会。",
            "cola": "作为执行者，请评估可行性，提出具体的实施步骤和潜在障碍。",
        }

        context = ""
        if self.history and len(self.history) > 1:
            recent = self.history[-4:]
            context_lines = []
            for h in recent:
                if (
                    h["agent"] != "system"
                    and "completed" not in h["content"]
                    and "收到" not in h["content"]
                ):
                    context_lines.append(f"{h['agent']}说：{h['content'][:100]}")
            if context_lines:
                context = "之前的讨论：\n" + "\n".join(context_lines) + "\n\n"

        knowledge_context = self._retrieve_knowledge()

        prompt = f"""圆桌会议进行中，第{turn}轮。

{context}主题是：{self.topic}

{knowledge_context}
{role_instructions.get(agent_name, "")}

请直接发表你的观点。"""

        return prompt

    def _retrieve_knowledge(self) -> str:
        """从知识库检索相关内容"""
        if not self.knowledge_module or not self.knowledge_module.enabled:
            return ""

        query = self.topic
        if self.history:
            recent_content = " ".join(
                [h.get("content", "")[:100] for h in self.history[-3:]]
            )
            query = f"{self.topic} {recent_content}"

        try:
            results = self.knowledge_module.retrieve(query, top_k=2)
            if results:
                return f"【相关经验参考】\n{results}\n"
        except Exception as e:
            self.logger.warning(f"知识检索失败: {e}")

        return ""

    def _send_intro(self):
        """发送开场介绍"""
        template = self.config["roundtable"]["intro_template"]
        intro = template.format(topic=self.topic, turns=self.turns)

        self.logger.info(f"【开场】{intro}")
        self.openclaw.send_message(intro)
        self._add_to_history("system", intro)

    def _add_to_history(self, agent: str, content: str):
        """添加发言到历史"""
        self.history.append(
            {
                "turn": self.turn_index,
                "agent": agent,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def _run_single_turn(self) -> bool:
        """执行单轮发言"""
        self.turn_index += 1

        turn_order = self._get_turn_order()
        current_agent = turn_order[(self.turn_index - 1) % len(turn_order)]

        prompt = self._build_turn_prompt(current_agent, self.turn_index)
        system_prompt = self._build_system_prompt(current_agent)

        self.logger.info(f"【第{self.turn_index}轮】{current_agent} 发言中...")

        try:
            response = self.openclaw.call_agent(
                agent_name=current_agent,
                message=prompt,
                system_prompt=system_prompt,
                timeout=self.config["scheduler"]["timeout"],
                session_id=self.session_id,
            )

            self._add_to_history(current_agent, response)
            self.logger.info(
                f"【第{self.turn_index}轮】{current_agent} 完成: {response[:100]}..."
            )

            # 发送消息到飞书群
            self.openclaw.send_message(f"[{current_agent}] {response}")

        except Exception as e:
            self.logger.error(f"【第{self.turn_index}轮】{current_agent} 失败: {e}")
            self._add_to_history(current_agent, f"[错误: {str(e)}]")

        # 等待发言间隔
        time.sleep(self.config["scheduler"]["turn_interval"])
        return True

    def _check_user_input(self) -> Optional[str]:
        """检查用户是否有介入"""
        return self.feishu.get_user_input()

    def _generate_summary(self) -> str:
        """生成讨论总结"""
        history_entries = [
            h
            for h in self.history
            if h["agent"] != "system"
            and "completed" not in h["content"]
            and "收到" not in h["content"]
            and len(h["content"]) > 10
        ]

        if not history_entries:
            return "讨论内容不足，无法生成总结。"

        history_text = "\n".join(
            [f"- {h['agent']}：{h['content'][:150]}" for h in history_entries]
        )

        summary_prompt = f"""请根据以下圆桌讨论内容，生成简短总结。

主题：{self.topic}

讨论内容：
{history_text}

请按以下格式回复：
1. 核心共识：（1-2句话）
2. 主要分歧：（如无则写"无"）
3. 建议行动：（1项）

直接回复，不要多余文字。"""

        try:
            summary = self.openclaw.call_agent(
                agent_name="hamburger",
                message=summary_prompt,
                timeout=120,
                session_id=f"sum_{uuid.uuid4().hex[:8]}",
            )
            return summary
        except Exception as e:
            self.logger.error(f"生成总结失败: {e}")
            return "总结生成失败"

    def _save_discussion(self, summary: str, vote_result: dict):
        """保存讨论到数据文件"""
        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)

        record = {
            "session_id": self.session_id,
            "topic": self.topic,
            "timestamp": datetime.now().isoformat(),
            "turns": self.turn_index,
            "summary": summary,
            "vote_result": vote_result,
            "history": self.history,
        }

        disc_file = data_dir / "discussions.json"
        discussions = []
        if disc_file.exists():
            with open(disc_file, "r", encoding="utf-8") as f:
                try:
                    discussions = json.load(f)
                except json.JSONDecodeError:
                    discussions = []
        discussions.append(record)
        with open(disc_file, "w", encoding="utf-8") as f:
            json.dump(discussions, f, ensure_ascii=False, indent=2)

        self.logger.info(f"讨论已保存: {self.session_id}")

    def run(self, topic: str = "auto", turns: int = 10) -> dict:
        """执行完整圆桌会议 - 状态机驱动"""
        self.topic = topic
        self.turns = turns
        self.session_id = str(uuid.uuid4())[:8]
        self.history = []
        self.turn_index = 0

        self.logger.info(f"=" * 50)
        self.logger.info(f"🍔 圆桌会议开始 | 主题: {topic} | 轮数: {turns}")
        self.logger.info(f"=" * 50)

        self._send_intro()
        self.status = State.DISCUSSING

        self.summary = ""
        self.vote_result = {}

        try:
            while self.status not in [State.COMPLETED, State.ERROR]:
                handler = self._state_handlers.get(self.status)
                if handler:
                    handler()
                else:
                    self.logger.error(f"未知状态: {self.status}")
                    break
        except Exception as e:
            self.status = State.ERROR
            self.logger.error(f"圆桌会议异常: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

        return {
            "status": self.status,
            "session_id": self.session_id,
            "turns": self.turn_index,
            "summary": self.summary,
            "vote": self.vote_result,
        }

    def _handle_idle(self):
        """IDLE 状态处理"""
        self.status = State.DISCUSSING

    def _handle_discussing(self):
        """DISCUSSING 状态处理"""
        user_input = self._check_user_input()
        if user_input:
            content = user_input.get("content", "")
            self.logger.info(f"【用户介入】{content}")
            self._add_to_history("user", content)
            self.openclaw.send_message(f"👤 用户介入：{content}")
            return

        if self.turn_index >= self.turns:
            self.status = State.SUMMARIZING
            return

        if not self._run_single_turn():
            self.status = State.SUMMARIZING

    def _handle_summarizing(self):
        """SUMMARIZING 状态处理"""
        self.logger.info("【总结】生成中...")
        self.summary = self._generate_summary()
        self._add_to_history("system", f"【总结】{self.summary}")
        self.openclaw.send_message(f"📋 本轮讨论总结：\n{self.summary}")
        self.status = State.VOTING

    def _handle_voting(self):
        """VOTING 状态处理"""
        self.logger.info("【投票】开始投票...")
        self.vote_result = self.voting_module.run_vote(
            self.summary, self.history, self.session_id
        )

        self.memory_module.process(self.summary, self.history, self.vote_result)

        if (
            self.vote_result["valuable_count"]
            >= self.config["memory"]["long_term_threshold"]
        ):
            self.knowledge_module.add(
                self.summary,
                {
                    "topic": self.topic,
                    "session_id": self.session_id,
                    "timestamp": datetime.now().isoformat(),
                },
            )

        self._save_discussion(self.summary, self.vote_result)

        end_msg = f"""🏁 圆桌会议结束

📊 统计：{self.turn_index}轮讨论 | 投票结果：{self.vote_result["valuable_count"]}票有价值
💾 记忆：{"已存入长期记忆" if self.vote_result["valuable_count"] >= 3 else "已存入短期记忆" if self.vote_result["valuable_count"] >= 2 else "未达到存储标准"}"""
        self.openclaw.send_message(end_msg)

        self.status = State.COMPLETED


# ---------------------------------------------------------------------------
# 投票模块
# ---------------------------------------------------------------------------
class VotingModule:
    """投票协调模块"""

    def __init__(self, config: dict, openclaw: OpenClawClient, logger):
        self.config = config
        self.openclaw = openclaw
        self.logger = logger

    def run_vote(self, summary: str, history: list, session_id: str = None) -> dict:
        """执行投票流程"""
        participants = self.config["participants"]
        votes = {}

        if self.config.get("auto_vote_hamburger"):
            votes["hamburger"] = "有价值"
            self.logger.info("[投票] 汉堡 -> 有价值")

        for agent in participants:
            if agent in ["hamburger", "user"]:
                continue

            vote_prompt = f"""{summary}

请评价上述讨论总结是否有价值。
只回复"有价值"或"无价值"。"""

            try:
                response = self.openclaw.call_agent(
                    agent_name=agent,
                    message=vote_prompt,
                    timeout=60,
                    session_id=session_id,
                )
                vote = "有价值" if "有价值" in response else "无价值"
                votes[agent] = vote
                self.logger.info(f"[投票] {agent} -> {vote}")
            except Exception as e:
                self.logger.error(f"[投票] {agent} 失败: {e}")
                votes[agent] = "无价值"

        valuable_count = sum(1 for v in votes.values() if v == "有价值")

        return {"votes": votes, "valuable_count": valuable_count, "total": len(votes)}


# ---------------------------------------------------------------------------
# 飞书客户端（接收用户消息）
# ---------------------------------------------------------------------------
class FeishuClient:
    """飞书客户端 - 监听用户消息"""

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.enabled = config.get("enabled", True)
        self.group_id = config.get("group_id", "")
        self.account = config.get("account", "main")
        self.bot_names = config.get("bot_names", ["汉堡", "薯条", "可乐"])
        self.user_keywords = config.get("user_keywords", {})

        self.user_input_queue: list[dict] = []

    def get_user_input(self) -> Optional[str]:
        """获取用户输入（轮询方式）"""
        if not self.enabled:
            return None

        try:
            cmd = [
                "openclaw",
                "message",
                "read",
                "--channel",
                "feishu",
                "--account",
                self.account,
                "--limit",
                "10",
            ]

            code, stdout, stderr = run_openclaw(cmd, timeout=15)

            if code == 0 and stdout:
                return self._parse_user_messages(stdout)
        except Exception as e:
            self.logger.error(f"读取飞书消息失败: {e}")

        return None

    def _parse_user_messages(self, raw_output: str) -> Optional[str]:
        """解析用户消息"""
        try:
            lines = raw_output.strip().split("\n")
            for line in lines[-5:]:
                line = line.strip()
                if not line:
                    continue
                # 过滤机器人消息（以bot名称开头）
                if any(line.startswith(bot) for bot in self.bot_names):
                    continue
                # 过滤系统消息
                if line.startswith("【") or line.startswith("🏁"):
                    continue
                # 有效用户消息
                if len(line) > 3:
                    return line
        except Exception as e:
            self.logger.error(f"解析消息失败: {e}")
        return None

    def send_message(self, message: str) -> bool:
        """发送消息"""
        if not self.enabled:
            return False

        cmd = [
            "openclaw",
            "message",
            "send",
            "--channel",
            "feishu",
            "--account",
            self.account,
            "--target",
            self.group_id,
            "--message",
            message,
        ]

        code, stdout, stderr = run_openclaw(cmd, timeout=30)
        return code == 0


def setup_utf8_logger(name: str = "burger_king") -> logging.Logger:
    """配置 UTF-8 安全的日志记录器"""
    import logging
    from logging.handlers import RotatingFileHandler

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        log_file = log_dir / f"burger_king_{datetime.now().strftime('%Y%m%d')}.log"

        file_handler = RotatingFileHandler(
            log_file, encoding="utf-8", maxBytes=10 * 1024 * 1024, backupCount=5
        )
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(console_formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


if __name__ == "__main__":
    logger = setup_utf8_logger()

    with open("config/settings.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    rt = Roundtable(config, logger)
    result = rt.run(topic="AI Agent的未来发展方向", turns=6)
    print(json.dumps(result, ensure_ascii=False, indent=2))
