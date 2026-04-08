"""
圆桌会议核心调度脚本
支持：轮转调度、上下文注入、角色扮演、投票协调、记忆存储、知识检索
"""
import json
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


def run_openclaw(command: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """执行 OpenClaw CLI 命令"""
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
        return -1, "", "Command timeout"
    except Exception as e:
        return -1, "", str(e)


class OpenClawClient:
    """OpenClaw API 客户端 - 通过 CLI 调用"""

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.agents = {a["name"]: a for a in config.get("agents", [])}

    def call_agent(self, agent_name: str, message: str,
                   system_prompt: str = "", timeout: int = 120) -> str:
        """调用 Agent 获取回复"""
        cmd = [
            "openclaw", "agent",
            "--agent", agent_name,
            "--message", message
        ]

        if system_prompt:
            # 将 system prompt 写入临时文件，通过环境变量或间接方式传递
            pass

        self.logger.info(f"[OpenClaw] 调用 {agent_name}: {message[:80]}...")

        code, stdout, stderr = run_openclaw(cmd, timeout)

        if code == 0 and stdout:
            try:
                # 尝试解析 JSON 输出
                data = json.loads(stdout)
                if isinstance(data, dict):
                    return data.get("reply", data.get("text", stdout))
                return stdout.strip()
            except json.JSONDecodeError:
                return stdout.strip()
        else:
            self.logger.error(f"[OpenClaw] 调用失败: {stderr}")
            return f"[调用失败: {stderr}]"

    def send_message(self, message: str, channel: str = "feishu",
                    account: str = "main", target: str = None) -> bool:
        """发送消息到指定渠道"""
        target = target or self.config.get("feishu", {}).get("group_id", "")

        cmd = [
            "openclaw", "message", "send",
            "--channel", channel,
            "--account", account,
            "--target", target,
            "--message", message
        ]

        self.logger.info(f"[Feishu] 发送消息: {message[:80]}...")

        code, stdout, stderr = run_openclaw(cmd, timeout=30)

        if code == 0:
            return True
        else:
            self.logger.error(f"[Feishu] 发送失败: {stderr}")
            return False


class Roundtable:
    """汉堡王圆桌会议核心调度器"""

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.openclaw = OpenClawClient(config["openclaw"], logger)
        self.feishu = FeishuClient(config["feishu"], logger)

        self.topic: str = "auto"
        self.turns: int = 10
        self.history: list[dict] = []
        self.turn_index: int = 0
        self.session_id: str = str(uuid.uuid4())[:8]
        self.status: str = "idle"

        from core.memory_store import MemoryStore
        from core.knowledge_base import KnowledgeBase

        self.voting_module = VotingModule(config["voting"], self.openclaw, logger)
        self.memory_module = MemoryStore(config["memory"], logger)
        self.knowledge_module = KnowledgeBase(config["knowledge_base"], logger)

    def _build_system_prompt(self, agent_name: str) -> str:
        """构建 Agent 系统提示词"""
        agent_config = self.openclaw.agents.get(agent_name)
        if not agent_config:
            return ""
        return agent_config.get("system_prompt", "")

    def _get_turn_order(self) -> list[str]:
        """获取轮转顺序"""
        return ["hamburger", "frenchFries", "cola"]

    def _build_turn_prompt(self, agent_name: str, turn: int) -> str:
        """构建单轮发言提示词"""
        role_map = {a["name"]: a["role"] for a in self.config["openclaw"]["agents"]}
        role_instructions = {
            "hamburger": "作为主持，请协调各方观点，推动讨论深入，适时总结进展。",
            "frenchFries": "作为智囊，请提供深度分析、战略建议和备选方案。",
            "cola": "作为执行者，请关注落地细节、实际挑战和可执行性。"
        }

        context = ""
        if self.history:
            recent = self.history[-6:]
            context = "【近期讨论】\n" + "\n".join([
                f"[{h['agent']}] {h['content'][:200]}"
                for h in recent
            ]) + "\n"

        prompt = f"""【圆桌会议 #{self.session_id} | 第{turn}轮】

{context}
主题：{self.topic}

你的角色：{role_map.get(agent_name, '未知')}
{role_instructions.get(agent_name, '')}

请围绕主题，发表你的观点。简洁有力，不超过200字。
格式：[你的代号] 内容"""

        return prompt

    def _send_intro(self):
        """发送开场介绍"""
        template = self.config["roundtable"]["intro_template"]
        intro = template.format(topic=self.topic, turns=self.turns)

        self.logger.info(f"【开场】{intro}")
        self.openclaw.send_message(intro)
        self._add_to_history("system", intro)

    def _add_to_history(self, agent: str, content: str):
        """添加发言到历史"""
        self.history.append({
            "turn": self.turn_index,
            "agent": agent,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

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
                timeout=self.config["scheduler"]["timeout"]
            )

            self._add_to_history(current_agent, response)
            self.logger.info(f"【第{self.turn_index}轮】{current_agent} 完成: {response[:100]}...")

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
        history_text = "\n".join([
            f"[{h['agent']}] {h['content']}"
            for h in self.history
        ])

        summary_prompt = f"""你是一个专业的内容总结师。请对以下圆桌讨论进行精炼总结：

主题：{self.topic}

讨论记录：
{history_text}

请按以下格式总结：
1. 核心共识：（2-3句话）
2. 主要分歧：（如有）
3. 关键洞见：（1-2个）

保持简洁，专业。"""

        try:
            summary = self.openclaw.call_agent(
                agent_name="hamburger",
                message=summary_prompt,
                timeout=120
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
            "history": self.history
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
        """执行完整圆桌会议"""
        self.topic = topic
        self.turns = turns
        self.status = "running"
        self.session_id = str(uuid.uuid4())[:8]

        self.logger.info(f"=" * 50)
        self.logger.info(f"🍔 圆桌会议开始 | 主题: {topic} | 轮数: {turns}")
        self.logger.info(f"=" * 50)

        self._send_intro()

        try:
            for i in range(turns):
                if not self._run_single_turn():
                    break

                user_input = self._check_user_input()
                if user_input:
                    content = user_input.get("content", "")
                    self.logger.info(f"【用户介入】{content}")
                    self._add_to_history("user", content)
                    self.openclaw.send_message(f"👤 用户介入：{content}")

            self.logger.info("【总结】生成中...")
            summary = self._generate_summary()
            self._add_to_history("system", f"【总结】{summary}")
            self.openclaw.send_message(f"📋 本轮讨论总结：\n{summary}")

            self.logger.info("【投票】开始投票...")
            vote_result = self.voting_module.run_vote(summary, self.history)

            self.memory_module.process(summary, self.history, vote_result)

            if vote_result["valuable_count"] >= self.config["memory"]["long_term_threshold"]:
                self.knowledge_module.add(summary, {
                    "topic": self.topic,
                    "session_id": self.session_id,
                    "timestamp": datetime.now().isoformat()
                })

            self._save_discussion(summary, vote_result)

            end_msg = f"""🏁 圆桌会议结束

📊 统计：{self.turn_index}轮讨论 | 投票结果：{vote_result['valuable_count']}票有价值
💾 记忆：{'已存入长期记忆' if vote_result['valuable_count'] >= 3 else '已存入短期记忆' if vote_result['valuable_count'] >= 2 else '未达到存储标准'}"""
            self.openclaw.send_message(end_msg)

            self.status = "completed"
            return {
                "status": "completed",
                "session_id": self.session_id,
                "turns": self.turn_index,
                "summary": summary,
                "vote": vote_result
            }

        except Exception as e:
            self.status = "error"
            self.logger.error(f"圆桌会议异常: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# 投票模块
# ---------------------------------------------------------------------------
class VotingModule:
    """投票协调模块"""

    def __init__(self, config: dict, openclaw: OpenClawClient, logger):
        self.config = config
        self.openclaw = openclaw
        self.logger = logger

    def run_vote(self, summary: str, history: list) -> dict:
        """执行投票流程"""
        participants = self.config["participants"]
        votes = {}

        if self.config.get("auto_vote_hamburger"):
            votes["hamburger"] = "有价值"
            self.logger.info("[投票] 汉堡 -> 有价值")

        for agent in participants:
            if agent in ["hamburger", "user"]:
                continue

            vote_prompt = f"""请对以下圆桌讨论总结进行评价，仅回复"有价值"或"无价值"，无需说明理由：

{summary}"""

            try:
                response = self.openclaw.call_agent(
                    agent_name=agent,
                    message=vote_prompt,
                    timeout=60
                )
                vote = "有价值" if "有价值" in response else "无价值"
                votes[agent] = vote
                self.logger.info(f"[投票] {agent} -> {vote}")
            except Exception as e:
                self.logger.error(f"[投票] {agent} 失败: {e}")
                votes[agent] = "无价值"

        valuable_count = sum(1 for v in votes.values() if v == "有价值")

        return {
            "votes": votes,
            "valuable_count": valuable_count,
            "total": len(votes)
        }


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
                "openclaw", "message", "read",
                "--channel", "feishu",
                "--account", self.account,
                "--limit", "10"
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
            "openclaw", "message", "send",
            "--channel", "feishu",
            "--account", self.account,
            "--target", self.group_id,
            "--message", message
        ]

        code, stdout, stderr = run_openclaw(cmd, timeout=30)
        return code == 0


if __name__ == "__main__":
    import logging
    from logging.handlers import RotatingFileHandler

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("burger_king")

    with open("config/settings.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    rt = Roundtable(config, logger)
    result = rt.run(topic="AI Agent的未来发展方向", turns=6)
    print(json.dumps(result, ensure_ascii=False, indent=2))
