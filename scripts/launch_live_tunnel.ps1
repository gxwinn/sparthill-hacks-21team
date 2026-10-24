<#
.SYNOPSIS
    One-command launcher for MedBill Shield Live Cloudflare Tunnel & Mobile QR Code.
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
$ScriptPath = Join-Path $PSScriptRoot "launch_live_tunnel.py"

if (Test-Path $VenvPython) {
    & $VenvPython $ScriptPath @args
} else {
    python $ScriptPath @args
}

