"""
圆桌会议核心调度脚本
负责：轮转调度、上下文注入、角色扮演、投票协调、记忆存储、知识检索
"""
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


class Roundtable:
    """汉堡王圆桌会议核心调度器"""

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.openclaw = OpenClawClient(config["openclaw"], logger)
        
        # 状态
        self.topic: str = "auto"
        self.turns: int = 10
        self.history: list[dict] = []
        self.turn_index: int = 0
        self.session_id: str = str(uuid.uuid4())[:8]
        self.status: str = "idle"

        # 组件
        self.voting_module = VotingModule(config["voting"], self.openclaw, logger)
        self.memory_module = MemoryStore(config["memory"], logger)
        self.knowledge_module = KnowledgeBase(config["knowledge_base"], logger)

    def _build_system_prompt(self, agent_name: str) -> str:
        """构建Agent系统提示词"""
        agents = self.config["openclaw"]["agents"]
        agent_config = next((a for a in agents if a["name"] == agent_name), None)
        if not agent_config:
            return ""
        
        base = agent_config["system_prompt"]
        
        # 注入相关历史记忆
        if self.config["roundtable"]["context_injection"]:
            related = self.knowledge_module.retrieve(self.topic, top_k=2)
            if related:
                base += f"\n\n【相关历史讨论参考】\n{related}"
        
        return base

    def _get_turn_order(self) -> list[str]:
        """获取轮转顺序"""
        return [
            self.config["openclaw"]["agents"][0]["name"],  # 汉堡主持
            self.config["openclaw"]["agents"][1]["name"],  # 薯条分析
            self.config["openclaw"]["agents"][2]["name"],  # 可乐执行
        ]

    def _build_turn_prompt(self, agent_name: str, turn: int) -> str:
        """构建单轮发言提示词"""
        agents_config = self.config["openclaw"]["agents"]
        role_map = {a["name"]: a["role"] for a in agents_config}
        
        # 构建上下文摘要
        context = ""
        if self.history:
            recent = self.history[-6:]  # 最近6轮
            context = "【近期讨论】\n" + "\n".join([
                f"[{h['agent']}] {h['content'][:200]}"
                for h in recent
            ]) + "\n"
        
        # 角色特定指令
        role_instruction = {
            "hamburger": "作为主持，请协调各方观点，推动讨论深入。",
            "frenchFries": "作为智囊，请提供深度分析和战略建议。",
            "cola": "作为执行者，请关注落地细节和实际问题。"
        }
        
        prompt = f"""【圆桌会议 #{self.session_id} | 第{turn}轮】

{context}
主题：{self.topic}

你的角色：{role_map.get(agent_name, '未知')}
{role_instruction.get(agent_name, '')}

请围绕主题，发表你的观点。简洁有力，不超过200字。
格式：[你的代号] 内容"""
        
        return prompt

    def _send_intro(self):
        """发送开场介绍"""
        template = self.config["roundtable"]["intro_template"]
        intro = template.format(
            topic=self.topic,
            turns=self.turns
        )
        
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
        
        # 轮转顺序：汉堡 -> 薯条 -> 可乐
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
            
        except Exception as e:
            self.logger.error(f"【第{self.turn_index}轮】{current_agent} 失败: {e}")
            self._add_to_history(current_agent, f"[错误: {str(e)}]")
        
        # 等待间隔
        time.sleep(self.config["scheduler"]["turn_interval"])
        return True

    def _check_user_input(self) -> Optional[str]:
        """检查用户是否有介入"""
        # TODO: 实现用户输入队列检查
        return None

    def _generate_summary(self) -> str:
        """生成讨论总结"""
        summary_prompt = f"""你是一个专业的内容总结师。请对以下圆桌讨论进行精炼总结：

主题：{self.topic}

讨论记录：
{chr(10).join([f"[{h['agent']}] {h['content']}" for h in self.history])}

请按以下格式总结：
1. 核心共识：（2-3句话）
2. 主要分歧：（如有）
3. 关键洞见：（1-2个）

保持简洁，专业。"""

        try:
            summary = self.openclaw.call_agent(
                agent_name="hamburger",
                message=summary_prompt,
                timeout=60
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
        
        # 追加到 discussions.json
        disc_file = data_dir / "discussions.json"
        discussions = []
        if disc_file.exists():
            with open(disc_file, "r", encoding="utf-8") as f:
                discussions = json.load(f)
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
        
        # 开场
        self._send_intro()
        
        try:
            # 执行讨论轮次
            for i in range(turns):
                if not self._run_single_turn():
                    break
                
                # 检查用户介入
                user_input = self._check_user_input()
                if user_input:
                    self.logger.info(f"【用户介入】{user_input}")
                    self._add_to_history("user", user_input)
            
            # 生成总结
            self.logger.info("【总结】生成中...")
            summary = self._generate_summary()
            self._add_to_history("system", f"【总结】{summary}")
            self.openclaw.send_message(f"📋 本轮讨论总结：\n{summary}")
            
            # 投票
            self.logger.info("【投票】开始投票...")
            vote_result = self.voting_module.run_vote(summary, self.history)
            
            # 分级记忆存储
            self.memory_module.process(summary, self.history, vote_result)
            
            # 更新知识库（票数达标）
            if vote_result["valuable_count"] >= self.config["memory"]["long_term_threshold"]:
                self.knowledge_module.add(summary, {
                    "topic": self.topic,
                    "session_id": self.session_id,
                    "timestamp": datetime.now().isoformat()
                })
            
            # 保存讨论记录
            self._save_discussion(summary, vote_result)
            
            # 发送结束消息
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
# OpenClaw 客户端（简化版，实际使用需要根据OpenClaw的API调整）
# ---------------------------------------------------------------------------
class OpenClawClient:
    """OpenClaw API 客户端"""
    
    def __init__(self, config: dict, logger):
        self.gateway_url = config.get("gateway_url", "http://127.0.0.1:18789")
        self.agents = {a["name"]: a for a in config.get("agents", [])}
        self.logger = logger
        
        # TODO: 实际初始化HTTP/WebSocket客户端
        self._session = None
    
    def call_agent(self, agent_name: str, message: str, 
                   system_prompt: str = "", timeout: int = 60) -> str:
        """调用Agent获取回复"""
        # TODO: 实现实际的OpenClaw API调用
        # 目前为占位实现
        self.logger.info(f"[OpenClaw] 调用 {agent_name}: {message[:50]}...")
        
        # 模拟延迟
        import time
        time.sleep(2)
        
        # 模拟回复
        responses = {
            "hamburger": "作为主持人，我认为我们应该先梳理一下各方观点，找到共识点。",
            "frenchFries": "从战略角度看，这个问题需要分阶段处理。关键是要把握好节奏。",
            "cola": "执行层面，我们需要考虑资源调配和时间节点的可操作性。"
        }
        
        return responses.get(agent_name, "收到，继续讨论。")
    
    def send_message(self, message: str) -> bool:
        """发送消息到飞书群"""
        # TODO: 实现飞书消息发送
        self.logger.info(f"[Feishu] 发送消息: {message[:50]}...")
        return True


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
        
        # 汉堡自动投票
        if self.config.get("auto_vote_hamburger"):
            votes["hamburger"] = "有价值"
            self.logger.info("[投票] 汉堡 -> 有价值")
        
        # 其他参与者投票（通过调用Agent）
        for agent in participants:
            if agent in ["hamburger", "user"]:
                continue
            
            vote_prompt = f"""请对以下圆桌讨论总结进行评价，仅回复"有价值"或"无价值"，无需说明理由：

{summary}"""
            
            try:
                response = self.openclaw.call_agent(
                    agent_name=agent,
                    message=vote_prompt,
                    timeout=30
                )
                vote = "有价值" if "有价值" in response else "无价值"
                votes[agent] = vote
                self.logger.info(f"[投票] {agent} -> {vote}")
            except Exception as e:
                self.logger.error(f"[投票] {agent} 失败: {e}")
                votes[agent] = "无价值"
        
        # 统计
        valuable_count = sum(1 for v in votes.values() if v == "有价值")
        
        return {
            "votes": votes,
            "valuable_count": valuable_count,
            "total": len(votes)
        }


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("test")
    
    with open("config/settings.yaml", "r") as f:
        config = yaml.safe_load(f)
    
    rt = Roundtable(config, logger)
    result = rt.run(topic="AI Agent的未来发展方向", turns=6)
    print(json.dumps(result, ensure_ascii=False, indent=2))
