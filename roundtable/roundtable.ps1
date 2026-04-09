# roundtable.ps1 - Final version with Python-based Feishu sender
param([int]$Timeout=45, [string]$Topic="")

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$ErrorActionPreference = "SilentlyContinue"
$OPENCLAW = "$env:APPDATA\npm\node_modules\openclaw\openclaw.mjs"
$GID = "oc_9ea914f5ad7acbd9061c915a0f942d5c"
$LOG = "D:\works\Project\burger-king-chat-v2\roundtable\logs"
$PY = "python"

if (-not $Topic) {
    $topics = @("AI Agent Future","Multi-Agent Collaboration","Memory Persistence","AI-Human Boundary","Vertical vs Platform","Wolf Pack Tactics")
    $Topic = $topics[(Get-Random -Maximum $topics.Length)]
}

function Send-Feishu($text) {
    # Write message to temp file (UTF-8)
    $msgFile = "$LOG\send_msg.txt"
    $Utf8NoBom = New-Object System.Text.UTF8Encoding $False
    [System.IO.File]::WriteAllText($msgFile, $text, $Utf8NoBom)
    
    # Use Python to send via Gateway API (handles UTF-8 correctly)
    $sendPy = @"
import sys
import os
import json
import urllib.request

msg_file = r"$msgFile"
with open(msg_file, 'r', encoding='utf-8') as f:
    message = f.read()

cfg_path = os.path.expandvars(r'%APPDATA%\npm\node_modules\openclaw\config\gateway.json')
try:
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    port = cfg.get('gateway', {}).get('port', 18789)
    token = cfg.get('gateway', {}).get('auth', {}).get('token', 'openclaw')
except:
    port = 18789
    token = 'openclaw'

url = f'http://localhost:{port}/api/messages/send'
data = {
    'channel': 'feishu',
    'accountId': 'main',
    'target': '$GID',
    'message': message
}

req = urllib.request.Request(
    url,
    data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
    headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    },
    method='POST'
)

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = resp.read().decode('utf-8')
        print(f'Sent: {result}')
except Exception as e:
    print(f'Error: {e}')
"@
    
    $sendPyFile = "$LOG\send_feishu_temp.py"
    [System.IO.File]::WriteAllText($sendPyFile, $sendPy, $Utf8NoBom)
    
    $proc = Start-Process python -ArgumentList "`"$sendPyFile`"" -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5
    if (-not $proc.HasExited) { $proc.Kill() }
}

function Get-AgentReply($agent, $prompt) {
    $outFile = "$LOG\${agent}_reply.txt"
    $cmd = "node `"$OPENCLAW`" agent --agent $agent --message `"$prompt`" --timeout $Timeout"
    $proc = Start-Process cmd -ArgumentList "/c $cmd > `"$outFile`" 2>&1" -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds ($Timeout + 3)
    if ((Test-Path $outFile) -and ($proc.HasExited -eq $false)) {
        $content = Get-Content $outFile -Raw -Encoding UTF8
        $proc.Kill()
    } elseif (-not $proc.HasExited) {
        $proc.Kill()
        $content = ""
    } else {
        $content = Get-Content $outFile -Raw -Encoding UTF8
    }
    $content = $content -replace "(?s).*?(\[[HFC][\s\]].*)", '$1'
    if (-not $content) { $content = Get-Content $outFile -Raw -Encoding UTF8 }
    return $content.Trim()
}

Write-Host "[Roundtable] Topic: $Topic"

$friesPrompt = "You are fries (智囊). Topic: $Topic. Reply 2-3 sentences, format: [F] fries your view."
$f = Get-AgentReply "fries" $friesPrompt
if ($f) { Write-Host "[fries] $f" } else { Write-Host "[fries] no response" }

$colaPrompt = "You are cola (执行者). Topic: $Topic. Reply 2-3 sentences, format: [C] cola your view."
$c = Get-AgentReply "cola" $colaPrompt
if ($c) { Write-Host "[cola] $c" } else { Write-Host "[cola] no response" }

# Hamburger - dynamic generation
Write-Host "[hamburger] generating..."
$genCmd = "$PY `"$LOG\..\generate_hamburger.py`" `"$Topic`""
$genProc = Start-Process cmd -ArgumentList "/c $genCmd" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 3
if (-not $genProc.HasExited) { $genProc.Kill() }

# Read all replies
$fFile = "$LOG\fries_reply.txt"
$cFile = "$LOG\cola_reply.txt"
$hFile = "$LOG\hamburger_msg.txt"
$fMsg = if (Test-Path $fFile) { Get-Content $fFile -Raw -Encoding UTF8 } else { "no response" }
$cMsg = if (Test-Path $cFile) { Get-Content $cFile -Raw -Encoding UTF8 } else { "no response" }
$hMsg = if (Test-Path $hFile) { Get-Content $hFile -Raw -Encoding UTF8 } else { "[H] hamburger: Coordinator perspective" }

# Build and send full message
$timeStr = Get-Date -Format "HH:mm"
$introMsg = "🐺 圆桌会议 #$timeStr | 议题：$Topic"
$fullMsg = "$introMsg`n`n🍟 [F] $fMsg`n`n🥤 [C] $cMsg`n`n🍔 $hMsg"
Write-Host "[Sending to Feishu...]"
Write-Host $fullMsg
Send-Feishu $fullMsg

Write-Host "[Roundtable] Done"
