# 👑 汉堡王自治系统 V2

多Agent实时对话平台，支持自动调度、投票记忆与知识积累。

基于 OpenClaw Agent 框架，构建具备状态感知、决策能力和知识沉淀的自治团队。

---

## 核心特性

- 🤖 **三Agent协作** — 汉堡(主持)、薯条(智囊)、可乐(执行)
- ⏰ **自动定时调度** — 工作日8:00-18:00，每30分钟自动触发
- 🗳️ **投票评价机制** — 多参与者投票，决定内容价值
- 💾 **分级记忆存储** — 短期记忆(≥2票) / 长期记忆(≥3票)
- 🔍 **共享知识库** — Chroma向量库，支持RAG检索增强
- 💬 **用户实时介入** — 支持人类在讨论中随时参与
- 📊 **讨论总结生成** — AI自动提炼核心观点

---

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│                  汉堡王自治系统 V2                    │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌─────────────┐    ┌─────────────────────────────┐ │
│  │  定时调度器  │───▶│  核心调度脚本 (Roundtable)  │ │
│  │  Scheduler  │    │  - 轮转发言                  │ │
│  └─────────────┘    │  - 上下文注入                │ │
│                     │  - 角色扮演                   │ │
│                     │  - 投票协调 ──────────────────│ │
│                     │  - 记忆存储 ──────────────────│ │
│                     │  - 知识检索                   │ │
│                     └──────────────┬────────────────┘ │
│                                    │                 │
│         ┌───────────────────────────┼───────────────┐│
│         │                           ▼               ││
│  ┌──────┴──────┐  ┌─────────┐  ┌─────────┐        ││
│  │   汉堡 🍔   │  │  薯条 🍟 │  │ 可乐 🥤 │        ││
│  │  主持协调   │  │  智囊分析 │  │  执行落地 │        ││
│  └──────┬──────┘  └────┬────┘  └────┬────┘        ││
│         │               │              │            ││
│         └───────────────┼──────────────┘            ││
│                         │ OpenClaw                   ││
│                         ▼                            ││
│  ┌──────────────────────────────────────────────┐   ││
│  │            共享知识库 (Chroma)                │   ││
│  │  - 向量存储   - RAG检索   - 长期记忆沉淀     │   ││
│  └──────────────────────────────────────────────┘   ││
│                         │                            ││
│                         ▼                            ││
│  ┌──────────────────────────────────────────────┐   ││
│  │               飞书群交互层                    │   ││
│  │  - 消息发送   - 用户介入   - 实时展示        │   ││
│  └──────────────────────────────────────────────┘   ││
└──────────────────────────────────────────────────────┘
```

---

## 目录结构

```
burger-king-chat-v2/
├── config/
│   └── settings.yaml        # 系统配置
├── core/
│   ├── __init__.py
│   ├── scheduler.py         # 定时调度器
│   ├── roundtables.py      # 圆桌会议核心
│   ├── voting.py           # 投票模块
│   ├── memory_store.py     # 分级记忆存储
│   ├── knowledge_base.py   # 向量知识库
│   └── feishu_client.py    # 飞书接口
├── agents/                  # Agent定义（各Agent独立角色）
│   ├── hamburger/
│   ├── fries/
│   └── cola/
├── memory/                 # 记忆存储
│   ├── hamburger/
│   │   ├── short_term/     # 短期记忆
│   │   └── long_term/      # 长期记忆
│   ├── fries/
│   └── cola/
├── knowledge_base/         # 向量数据库
│   └── chroma_db/
├── data/                   # 数据持久化
│   ├── discussions.json    # 讨论记录
│   └── summaries.json     # 总结记录
├── templates/              # 前端模板
├── tests/                  # 测试
├── requirements.txt
├── README.md
└── .gitignore
```

---

## 快速开始

### 1. 安装依赖

```bash
cd burger-king-chat-v2
pip install -r requirements.txt

# 向量数据库依赖（首次运行自动下载模型）
# 约200MB
```

### 2. 配置

编辑 `config/settings.yaml`：

```yaml
openclaw:
  gateway_url: "http://127.0.0.1:18789"
  agents:
    - name: "hamburger"
      role: "主持协调"
      system_prompt: "你是汉堡，狼群的执行副手..."

scheduler:
  enabled: true
  cron: "*/30 8-18 * * 1-5"  # 工作日8-18点，每30分钟

feishu:
  enabled: true
  group_id: "你的群组ID"
```

### 3. 启动

```bash
# 启动调度器（守护进程）
python -m core.scheduler

# 或直接运行一次圆桌会议
python -m core.roundtables
```

---

## 配置说明

### 调度器配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `scheduler.cron` | Cron表达式 | `*/30 8-18 * * 1-5` |
| `scheduler.max_turns` | 每轮最大发言次数 | 10 |
| `scheduler.turn_interval` | 发言间隔(秒) | 30 |
| `scheduler.timeout` | 单次调度超时(秒) | 300 |

### 记忆配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `memory.short_term_threshold` | 短期记忆投票阈值 | 2 |
| `memory.long_term_threshold` | 长期记忆投票阈值 | 3 |

### 知识库配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `knowledge_base.embedding_model` | 向量模型 | `BAAI/bge-small-zh-v1.5` |
| `knowledge_base.top_k` | 检索返回条数 | 3 |

---

## API 接口

### 调度器

```bash
# 手动触发圆桌会议
curl -X POST http://localhost:5000/api/roundtable/trigger \
  -H "Content-Type: application/json" \
  -d '{"topic": "AI Agent的未来", "turns": 10}'

# 查询状态
curl http://localhost:5000/api/scheduler/status
```

### 记忆

```bash
# 获取Agent记忆
curl http://localhost:5000/api/memory/{agent_name}?type=all&limit=10

# 获取记忆摘要（用于上下文注入）
curl http://localhost:5000/api/memory/{agent_name}/summary
```

### 知识库

```bash
# 检索相关讨论
curl "http://localhost:5000/api/knowledge/retrieve?query=AI%20Agent&top_k=3"

# 知识库条数
curl http://localhost:5000/api/knowledge/count
```

---

## 记忆存储格式

### 短期/长期记忆 JSON

```json
[
  {
    "id": "20260408130045_1234",
    "timestamp": "2026-04-08T13:00:45",
    "summary": "讨论了AI Agent协作模式...",
    "history": [
      {"agent": "hamburger", "content": "作为主持...", "turn": 1},
      {"agent": "frenchFries", "content": "从战略角度看...", "turn": 2}
    ],
    "vote_result": {
      "valuable_count": 3,
      "total": 3,
      "votes": {"hamburger": "有价值", "frenchFries": "有价值", "cola": "有价值"}
    },
    "metadata": {"source": "roundtable", "topic": "Agent协作"},
    "tags": ["AI", "Agent", "协作"]
  }
]
```

---

## 投票机制

- **参与者**：汉堡(自动投有价值)、薯条、可乐、用户
- **阈值**：≥2票存入短期记忆，≥3票存入长期记忆
- **存储**：每个Agent独立记忆，按时间倒序

---

## 开发指南

### 添加新Agent

1. 在 `config/settings.yaml` 的 `openclaw.agents` 中添加配置
2. 在 `agents/` 目录创建对应的角色目录
3. 在 `core/roundtables.py` 的 `_get_turn_order()` 中注册

### 修改投票规则

编辑 `core/voting.py` 中的 `VotingModule` 类

### 扩展知识库

当前使用 ChromaDB，可替换为：
- Weaviate
- Milvus
- Pinecone（云端）
- Qdrant

---

## License

MIT
