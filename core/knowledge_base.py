"""
共享知识库模块
基于向量数据库（Chroma），支持：存储、检索、相关度排序
RAG（检索增强生成）核心组件
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


class KnowledgeBase:
    """汉堡王共享知识库"""

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.enabled = config.get("enabled", True)
        self.persist_path = Path(config.get("persist_path", "knowledge_base/chroma_db"))
        self.embedding_model = config.get("embedding_model", "BAAI/bge-small-zh-v1.5")
        self.top_k = config.get("top_k", 3)
        
        self._client = None
        self._collection = None
        self._embedder = None
        
        if self.enabled:
            self._init_vector_db()

    def _init_vector_db(self):
        """初始化向量数据库"""
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer
            
            # 初始化Chroma
            self.persist_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.persist_path))
            self._collection = self._client.get_or_create_collection(
                name="burger_king_discussions"
            )
            
            # 初始化Embedding模型
            self._embedder = SentenceTransformer(self.embedding_model)
            
            self.logger.info(f"知识库初始化完成: {self.persist_path}")
            
        except ImportError as e:
            self.logger.warning(f"知识库依赖未安装: {e}")
            self.enabled = False
        except Exception as e:
            self.logger.error(f"知识库初始化失败: {e}")
            self.enabled = False

    def _generate_id(self) -> str:
        """生成唯一ID"""
        return f"disc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{id(self) % 10000:04d}"

    def add(self, summary: str, metadata: dict = None):
        """添加讨论到知识库"""
        if not self.enabled:
            self.logger.warning("知识库未启用，跳过添加")
            return
        
        if not self._collection or not self._embedder:
            self.logger.error("知识库未初始化")
            return
        
        try:
            # 生成向量
            embedding = self._embedder.encode(summary).tolist()
            
            # 生成ID和元数据
            doc_id = self._generate_id()
            meta = {
                "summary": summary[:500],  # 截断以节省空间
                "timestamp": datetime.now().isoformat(),
                **(metadata or {})
            }
            
            # 存入向量数据库
            self._collection.add(
                documents=[summary],
                embeddings=[embedding],
                metadatas=[meta],
                ids=[doc_id]
            )
            
            self.logger.info(f"知识库新增: {doc_id}")
            
        except Exception as e:
            self.logger.error(f"添加知识失败: {e}")

    def retrieve(self, query: str, top_k: int = None) -> str:
        """检索相关讨论"""
        if not self.enabled:
            return ""
        
        if not self._collection or not self._embedder:
            self.logger.error("知识库未初始化")
            return ""
        
        try:
            top_k = top_k or self.top_k
            
            # 查询向量
            query_embedding = self._embedder.encode(query).tolist()
            
            # 检索
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
            
            # 格式化结果
            if not results.get("documents") or not results["documents"][0]:
                return ""
            
            related = []
            for i, (doc, meta) in enumerate(zip(
                results["documents"][0],
                results["metadatas"][0]
            )):
                timestamp = meta.get("timestamp", "")[:10]
                topic = meta.get("topic", "未知主题")
                related.append(
                    f"[{i+1}] 主题：{topic}（{timestamp}）\n"
                    f"摘要：{doc[:150]}..."
                )
            
            output = "\n\n".join(related)
            return output if output else ""
            
        except Exception as e:
            self.logger.error(f"检索知识失败: {e}")
            return ""

    def count(self) -> int:
        """获取知识库条目数"""
        if not self._collection:
            return 0
        return self._collection.count()

    def clear(self):
        """清空知识库"""
        if not self._collection:
            return
        
        try:
            self._client.delete_collection("burger_king_discussions")
            self._collection = self._client.get_or_create_collection(
                name="burger_king_discussions"
            )
            self.logger.info("知识库已清空")
        except Exception as e:
            self.logger.error(f"清空知识库失败: {e}")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("test")
    
    config = {
        "enabled": False,  # 测试时不启用向量模型
        "persist_path": "knowledge_base/chroma_db",
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "top_k": 3
    }
    
    kb = KnowledgeBase(config, logger)
    
    # 测试添加
    kb.add(
        summary="AI Agent的协作模式可以分为三类：中心调度、平等协作、分层治理。",
        metadata={"topic": "Agent协作模式", "source": "roundtable"}
    )
    
    # 测试检索
    result = kb.retrieve("AI Agent如何协作")
    print(f"检索结果:\n{result}")
