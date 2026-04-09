$cfg = Get-Content "$env:APPDATA\npm\node_modules\openclaw\config\gateway.json" -Raw | ConvertFrom-Json
$port = $cfg.gateway.port
$token = $cfg.gateway.auth.token
$headers = @{ Authorization = "Bearer $token" }
try {
    $resp = Invoke-RestMethod "http://localhost:$port/api" -Headers $headers -TimeoutSec 5
    $resp | ConvertTo-Json -Depth 3
} catch {
    Write-Host "Error: $_"
}
