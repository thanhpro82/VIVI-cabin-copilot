[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Validate", "Tests")]
    [string]$Stage
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = [IO.Path]::GetFullPath(
    (Join-Path $projectRoot "..\..\.venv\Scripts\python.exe")
)

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python is missing: $python"
}

$env:PYTHONUTF8 = "1"
Push-Location $projectRoot
try {
    Clear-Host
    Write-Host "VIVI SPIKE-001 - OFFLINE POC EVIDENCE" -ForegroundColor Cyan
    Write-Host "Stage: $Stage" -ForegroundColor Yellow
    Write-Host ""

    if ($Stage -eq "Validate") {
        Write-Host "Purpose: Validate benchmark fixtures and dataset contract."
        Write-Host "Runs: python -m offline_poc.runner validate"
        Write-Host "Reads: config/benchmark.yaml and eval/datasets/poc/v1/cases.jsonl"
        Write-Host "Does not: load models, benchmark latency/RAM, call the network, or prove full E2E."
        Write-Host ""
        & $python -m offline_poc.runner validate
    }
    else {
        Write-Host "Purpose: Run component contract regression tests."
        Write-Host "Runs: 17 tests in test_graph_hitl.py, test_rag.py, and test_voice.py."
        Write-Host "Covers: HITL/idempotency; RAG citations/refusal; voice adapters/offline guards."
        Write-Host "Does not: benchmark real Qwen, PhoWhisper, or Piper models, or prove full real-model E2E."
        Write-Host ""
        & $python -m pytest `
            tests\test_graph_hitl.py `
            tests\test_rag.py `
            tests\test_voice.py `
            -v --tb=short --disable-warnings
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Evidence stage '$Stage' failed with exit code $LASTEXITCODE."
    }

    Write-Host ""
    Write-Host "PASS - $Stage evidence is current." -ForegroundColor Green
}
finally {
    Pop-Location
}
