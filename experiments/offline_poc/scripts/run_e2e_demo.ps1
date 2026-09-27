[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("qwen25-05b-q4", "qwen25-3b-q4")]
    [string]$Profile,

    [Parameter(Mandatory = $true)]
    [string]$AudioPath,

    [ValidateRange(1024, 65535)]
    [int]$Port = 8080
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$repoRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "..\.."))
$python = [IO.Path]::GetFullPath((Join-Path $repoRoot ".venv\Scripts\python.exe"))
$server = [IO.Path]::GetFullPath((Join-Path $projectRoot "tools\llama-b9637\llama-server.exe"))
$modelNames = @{
    "qwen25-05b-q4" = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
    "qwen25-3b-q4" = "qwen2.5-3b-instruct-q4_k_m.gguf"
}
$model = [IO.Path]::GetFullPath(
    (Join-Path $projectRoot ("models\" + $modelNames[$Profile]))
)
$resolvedAudio = (Resolve-Path -LiteralPath $AudioPath -ErrorAction Stop).Path

foreach ($required in @($python, $server, $model, $resolvedAudio)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing required E2E artifact: $required"
    }
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use."
}

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $server
$startInfo.Arguments = "-m `"$model`" --alias local-model --host 127.0.0.1 --port $Port -t 4 -c 4096 -n 256"
$startInfo.UseShellExecute = $true
$startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$process = [System.Diagnostics.Process]::Start($startInfo)

try {
    Write-Host "Starting local llama-server for $Profile..." -ForegroundColor Cyan
    $healthy = $false
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if ($process.HasExited) {
            throw "llama-server exited before health check: $($process.ExitCode)"
        }
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($response.status -eq "ok") {
                $healthy = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $healthy) {
        throw "llama-server did not become healthy within 60 seconds."
    }

    $env:PYTHONUTF8 = "1"
    Push-Location $projectRoot
    try {
        & $python -m offline_poc.runner e2e `
            --profile $Profile `
            --audio-path $resolvedAudio `
            --base-url "http://127.0.0.1:$Port/v1" `
            --server-pid $process.Id
        if ($LASTEXITCODE -ne 0) {
            throw "Interactive E2E run failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit(10000) | Out-Null
    }
}
