"""
分级记忆存储模块
支持：短期记忆、长期记忆、按Agent分离、JSON格式持久化
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class MemoryStore:
    """汉堡王分级记忆存储"""

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.base_path = Path(config.get("base_path", "memory"))
        self.short_term_threshold = config.get("short_term_threshold", 2)
        self.long_term_threshold = config.get("long_term_threshold", 3)
        self.agents = config.get("agents", ["hamburger", "fries", "cola"])
        
        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保目录结构存在"""
        for agent in self.agents:
            for mem_type in ["short_term", "long_term"]:
                dir_path = self.base_path / agent / mem_type
                dir_path.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, agent: str, memory_type: str) -> Path:
        """获取记忆文件路径"""
        return self.base_path / agent / memory_type / "records.json"

    def _load_records(self, agent: str, memory_type: str) -> list:
        """加载记忆记录"""
        file_path = self._get_file_path(agent, memory_type)
        if not file_path.exists():
            return []
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"加载记忆失败 {agent}/{memory_type}: {e}")
            return []

    def _save_records(self, agent: str, memory_type: str, records: list):
        """保存记忆记录"""
        file_path = self._get_file_path(agent, memory_type)
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            self.logger.info(f"记忆已保存: {agent}/{memory_type} ({len(records)}条)")
        except IOError as e:
            self.logger.error(f"保存记忆失败: {e}")

    def _build_record(self, summary: str, history: list, vote_result: dict, metadata: dict = None) -> dict:
        """构建记忆记录"""
        return {
            "id": self._generate_id(),
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
            "history": history,
            "vote_result": vote_result,
            "metadata": metadata or {},
            "tags": self._extract_tags(summary)
        }

    def _generate_id(self) -> str:
        """生成唯一ID"""
        from datetime import datetime
        return f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{hash(datetime.now().isoformat()) % 10000:04d}"

    def _extract_tags(self, text: str) -> list[str]:
        """从文本中提取标签（简单实现）"""
        # TODO: 使用LLM提取标签
        keywords = []
        for kw in ["AI", "Agent", "协作", "知识", "管理", "技术", "产品"]:
            if kw in text:
                keywords.append(kw)
        return keywords[:5]

    def save_short_term(self, agent: str, summary: str, history: list, vote_result: dict, metadata: dict = None):
        """保存到短期记忆"""
        records = self._load_records(agent, "short_term")
        record = self._build_record(summary, history, vote_result, metadata)
        records.append(record)
        self._save_records(agent, "short_term", records)

    def save_long_term(self, agent: str, summary: str, history: list, vote_result: dict, metadata: dict = None):
        """保存到长期记忆"""
        records = self._load_records(agent, "long_term")
        record = self._build_record(summary, history, vote_result, metadata)
        records.append(record)
        self._save_records(agent, "long_term", records)
        
        # 同步到共享知识库
        self._sync_to_shared(agent, record)

    def _sync_to_shared(self, agent: str, record: dict):
        """同步到共享知识库"""
        # TODO: 调用KnowledgeBase的同步接口
        self.logger.info(f"[KnowledgeSync] 同步 {agent} 记录到共享知识库")

    def process(self, summary: str, history: list, vote_result: dict):
        """根据投票结果处理记忆存储"""
        valuable_count = vote_result.get("valuable_count", 0)
        
        if valuable_count >= self.long_term_threshold:
            # 存入长期记忆（所有Agent）
            for agent in self.agents:
                self.save_long_term(
                    agent, summary, history, vote_result,
                    {"source": "roundtable", "vote_threshold": "long_term"}
                )
            self.logger.info(f"✅ 存入长期记忆 (票数={valuable_count})")
        
        elif valuable_count >= self.short_term_threshold:
            # 存入短期记忆（所有Agent）
            for agent in self.agents:
                self.save_short_term(
                    agent, summary, history, vote_result,
                    {"source": "roundtable", "vote_threshold": "short_term"}
                )
            self.logger.info(f"📁 存入短期记忆 (票数={valuable_count})")
        
        else:
            self.logger.info(f"❌ 未达到存储标准 (票数={valuable_count})")

    def get_memory(self, agent: str, memory_type: str = "all", limit: int = 10) -> list:
        """获取Agent的记忆"""
        results = []
        
        if memory_type in ["short_term", "all"]:
            results.extend(self._load_records(agent, "short_term")[-limit:])
        
        if memory_type in ["long_term", "all"]:
            results.extend(self._load_records(agent, "long_term")[-limit:])
        
        # 按时间倒序
        results.sort(key=lambda x: x["timestamp"], reverse=True)
        return results[:limit]

    def get_summary(self, agent: str, memory_type: str = "all") -> str:
        """获取记忆摘要（用于注入上下文）"""
        records = self.get_memory(agent, memory_type, limit=5)
        
        if not records:
            return "暂无相关记忆"
        
        summaries = [r["summary"] for r in records]
        return "\n\n".join([f"- {s}" for s in summaries])


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("test")
    
    config = {
        "base_path": "memory",
        "short_term_threshold": 2,
        "long_term_threshold": 3,
        "agents": ["hamburger", "fries", "cola"]
    }
    
    store = MemoryStore(config, logger)
    
    # 测试
    test_history = [
        {"agent": "hamburger", "content": "我们应该改进沟通机制"},
        {"agent": "frenchFries", "content": "建议引入新的协作工具"},
        {"agent": "cola", "content": "落地执行需要明确时间表"}
    ]
    
    test_vote = {"valuable_count": 3, "total": 3}
    test_summary = "讨论了协作效率提升的三个方向：沟通机制、工具引入、时间管理。"
    
    store.process(test_summary, test_history, test_vote)
