#!/usr/bin/env python3
# send_feishu.py - Send message to Feishu via Gateway API
import sys
import os
import json

LOG = r"D:\works\Project\burger-king-chat-v2\roundtable\logs"

def main():
    if len(sys.argv) < 2:
        print("Usage: send_feishu.py <msg_file>")
        return
    
    msg_file = sys.argv[1]
    
    # Read message
    with open(msg_file, 'r', encoding='utf-8') as f:
        message = f.read().strip()
    
    if not message:
        print("Empty message")
        return
    
    # Gateway config
    cfg_path = os.path.expanduser(r"~\AppData\Roaming\npm\node_modules\openclaw\config\gateway.json")
    with open(cfg_path, 'r', encoding='utf-8') as f:
        import json
        cfg = json.load(f)
    
    port = cfg.get('gateway', {}).get('port', 18789)
    token = cfg.get('gateway', {}).get('auth', {}).get('token', 'openclaw')
    
    # Build request
    import urllib.request
    url = f"http://localhost:{port}/api/messages/send"
    data = {
        "channel": "feishu",
        "accountId": "main",
        "target": "oc_9ea914f5ad7acbd9061c915a0f942d5c",
        "message": message
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        },
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = resp.read().decode('utf-8')
            print(f"Sent: {result[:100]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
