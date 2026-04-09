# generate_hamburger.py - 动态生成hamburger协调者视角 v2
# 根据fries和cola的回复，生成总结性协调观点
import sys
import os
import re

sys.stdout.reconfigure(encoding='utf-8')

LOG = r"D:\works\Project\burger-king-chat-v2\roundtable\logs"

def read_file(name):
    path = os.path.join(LOG, name)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return ""

def extract_content(text):
    """提取回复中的核心内容"""
    if not text:
        return ""
    # 移除 [F] 或 [C] 前缀
    text = re.sub(r'^\[[FC]\]\s*', '', text)
    return text.strip()

def generate_coordinator_view(fries_msg, cola_msg, topic):
    """生成协调者视角 - 基于话题和回复内容"""
    fries_content = extract_content(fries_msg)
    cola_content = extract_content(cola_msg)
    
    # 关键词检测
    fries_keywords = []
    cola_keywords = []
    
    if '风险' in fries_content or '危机' in fries_content or '边界' in fries_content:
        fries_keywords.append("风险管控")
    if '协作' in fries_content or '协同' in fries_content or '配合' in fries_content:
        fries_keywords.append("协作")
    if '技术' in fries_content or '架构' in fries_content or '系统' in fries_content:
        fries_keywords.append("技术")
    if '伦理' in fries_content or '法律' in fries_content or '责任' in fries_content:
        fries_keywords.append("伦理法律")
    if '身份' in fries_content or '政治' in fries_content or '价值观' in fries_content:
        fries_keywords.append("价值观")
        
    if '执行' in cola_content or '落地' in cola_content or '行动' in cola_content:
        cola_keywords.append("执行力")
    if '效率' in cola_content or '速度' in cola_content or '快速' in cola_content:
        cola_keywords.append("效率")
    if '验证' in cola_content or '尝试' in cola_content or '试验' in cola_content:
        cola_keywords.append("验证")
    if '话语权' in cola_content or '定义' in cola_content or '标准' in cola_content:
        cola_keywords.append("定义权")
    if '信任' in cola_content or '配合' in cola_content or '分工' in cola_content:
        cola_keywords.append("协作")
    
    # 生成个性化总结
    if not fries_keywords and not cola_keywords:
        summary = f"关于{topic}：fries从战略视角分析，cola强调行动落地。两者形成闭环——思考与行动的平衡才是关键。"
    elif '风险管控' in fries_keywords or '伦理法律' in fries_keywords:
        summary = f"{topic}的核心挑战在于风险管控。fries提出风险边界问题，cola主张先行动再优化。关键结论：管得住才能走得远，但过度谨慎也会错失机会。"
    elif '价值观' in fries_keywords:
        summary = f"{topic}引发深层思考——Agent的价值观设计将影响社会决策。fries提出身份政治视角，cola主张行动优先。核心：技术与社会价值需要同步设计。"
    elif '协作' in fries_keywords or '协作' in cola_keywords:
        summary = f"{topic}的本质是协作系统。fries强调协同机制，cola注重执行落地。狼群战术精髓：分工明确、信任传递、配合默契才能笑到最后。"
    elif '效率' in cola_keywords or '验证' in cola_keywords:
        summary = f"{topic}的关键是速度与验证。cola主张快速试错，fries提供分析框架。核心洞察：先跑通场景再优化，比完美设计更重要。"
    else:
        summary = f"关于{topic}：fries与cola的观点形成闭环——战略分析+行动落地。核心结论：狼群战术精髓，分工明确各司其职，管得住才能走得远。"
    
    return f"[H] hamburger: {summary}"

def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else "AI Agent"
    
    fries = read_file("fries_reply.txt")
    cola = read_file("cola_reply.txt")
    
    msg = generate_coordinator_view(fries, cola, topic)
    
    output_path = os.path.join(LOG, "hamburger_msg.txt")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(msg)
    
    print(f"OK: {msg[:60]}...")

if __name__ == "__main__":
    main()
