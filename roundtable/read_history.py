import json, sys
with open(r'D:\works\Project\burger-king-chat-v2\roundtable\logs\history.jsonl','r',encoding='utf-8') as f:
    lines = f.readlines()
out = []
for line in lines[-15:]:
    try:
        r = json.loads(line)
        out.append(f"{r['agent']}: {r['text'][:100]}")
    except:
        out.append(line.strip()[:100])
with open(r'D:\works\Project\burger-king-chat-v2\roundtable\logs\history_out.txt','w',encoding='utf-8') as f:
    f.write('\n'.join(out))
print("done")
