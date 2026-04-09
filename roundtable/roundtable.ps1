# roundtable.ps1 - Final version with full content send to Feishu
param([int]$Timeout=45, [string]$Topic="")

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$ErrorActionPreference = "SilentlyContinue"
$cfgPath = "$env:APPDATA\npm\node_modules\openclaw\config\gateway.json"
if (-not (Test-Path $cfgPath)) {
    $cfgPath = "$env:USERPROFILE\.openclaw\openclaw.json"
}
$cfg = Get-Content $cfgPath -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
if (-not $cfg) {
    $port = $env:OPENCLAW_GATEWAY_PORT
    $token = $env:OPENCLAW_GATEWAY_TOKEN
} else {
    $port = $cfg.gateway.port
    $token = $cfg.gateway.auth.token
}
$baseUrl = "http://localhost:$port"
$headers = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }
$OPENCLAW = "$env:APPDATA\npm\node_modules\openclaw\openclaw.mjs"
$GID = "oc_9ea914f5ad7acbd9061c915a0f942d5c"
$MAIN = "main"
$LOG = "D:\works\Project\burger-king-chat-v2\roundtable\logs"
$PY = "python"

if (-not $Topic) {
    $topics = @("AI Agent Future","Multi-Agent Collaboration","Memory Persistence","AI-Human Boundary","Vertical vs Platform","Wolf Pack Tactics")
    $Topic = $topics[(Get-Random -Maximum $topics.Length)]
}

function Out-Feishu($text) {
    try {
        $body = @{ channel="feishu"; accountId=$MAIN; target=$GID; message=$text } | ConvertTo-Json
        $null = Invoke-WebRequest "$baseUrl/api/messages/send" -Method POST -Headers $headers -Body $body -TimeoutSec 10
    } catch {}
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
Out-Feishu "[Wolf Pack] Roundtable starting - Topic: $Topic"

$friesPrompt = "You are fries (智囊). Topic: $Topic. Reply 2-3 sentences, format: [F] fries your view."
$f = Get-AgentReply "fries" $friesPrompt
if ($f) { Write-Host "[fries] $f"; Out-Feishu "[F] $f" } else { Write-Host "[fries] no response" }

$colaPrompt = "You are cola (执行者). Topic: $Topic. Reply 2-3 sentences, format: [C] cola your view."
$c = Get-AgentReply "cola" $colaPrompt
if ($c) { Write-Host "[cola] $c"; Out-Feishu "[C] $c" } else { Write-Host "[cola] no response" }

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

# Send full roundtable to Feishu
$timeStr = Get-Date -Format "HH:mm"
$introMsg = "🐺 圆桌会议 #$timeStr | 议题：$Topic"
$fullMsg = "$introMsg`n`n🍟 [F] $fMsg`n`n🥤 [C] $cMsg`n`n🍔 $hMsg"
Write-Host "[Sending full content to Feishu...]"
Out-Feishu $fullMsg

Write-Host "[Roundtable] Done"
