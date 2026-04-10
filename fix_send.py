import re

with open('core/roundtables.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修改OpenClawClient.__init__签名
old_init = 'def __init__(self, config: dict, logger):'
new_init = 'def __init__(self, config: dict, logger, feishu_config: dict = None):'
content = content.replace(old_init, new_init, 1)

# 2. 在__init__里添加feishu_config存储（在self.agents之后）
old_agents = 'self.agents = {a["name"]: a for a in config.get("agents", [])}'
new_agents = '''self.agents = {a["name"]: a for a in config.get("agents", [])}
        self.feishu_config = feishu_config or {}'''
content = content.replace(old_agents, new_agents, 1)

# 3. 修改send_message的target获取逻辑
old_target = 'target = target or self.config.get("feishu", {}).get("group_id", "")'
new_target = 'target = target or (self.feishu_config.get("group_id") if self.feishu_config else "")'
content = content.replace(old_target, new_target, 1)

# 4. 修改Roundtable.__init__传递feishu_config
old_client = 'self.openclaw = OpenClawClient(config["openclaw"], logger)'
new_client = 'self.openclaw = OpenClawClient(config["openclaw"], logger, config.get("feishu", {}))'
content = content.replace(old_client, new_client, 1)

with open('core/roundtables.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fix applied successfully')
