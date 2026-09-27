[CmdletBinding()]
param(
    [string]$OutputDir = (Join-Path $PSScriptRoot "..\models\voice"),
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$zipformerRepo = "hynt/Zipformer-30M-RNNT-6000h"
$zipformerRevision = "24ed30248e1c96bb690c81c24ab4e056f8cd9fce"
$zipformerLicense = "cc-by-nc-nd-4.0"
$resolvedOutputDir = [IO.Path]::GetFullPath($OutputDir)
$modelOutputDir = Join-Path $resolvedOutputDir "zipformer-30m-rnnt-6000h"

# (repo filename, local filename). config.json in this HF repo is the
# sherpa-onnx tokens.txt token list, not a JSON config, so it is saved
# locally as tokens.txt directly.
$artifacts = @(
    @{ Repo = "encoder-epoch-20-avg-10.int8.onnx"; Local = "encoder.int8.onnx" }
    @{ Repo = "decoder-epoch-20-avg-10.int8.onnx"; Local = "decoder.int8.onnx" }
    @{ Repo = "joiner-epoch-20-avg-10.int8.onnx"; Local = "joiner.int8.onnx" }
    @{ Repo = "config.json"; Local = "tokens.txt" }
)

if ($DryRun) {
    [pscustomobject]@{
        Repository = $zipformerRepo
        Revision   = $zipformerRevision
        License    = $zipformerLicense
        OutputDir  = $modelOutputDir
        Artifacts  = $artifacts
    } | ConvertTo-Json -Depth 4
    exit 0
}

$hfCommand = Get-Command hf -ErrorAction SilentlyContinue
if (-not $hfCommand) {
    throw "Hugging Face CLI 'hf' was not found. Install huggingface_hub first."
}

New-Item -ItemType Directory -Path $modelOutputDir -Force | Out-Null

foreach ($artifact in $artifacts) {
    $targetPath = Join-Path $modelOutputDir $artifact.Local
    if (-not (Test-Path -LiteralPath $targetPath)) {
        $tempDir = Join-Path $modelOutputDir "_download_tmp"
        & $hfCommand.Source download $zipformerRepo $artifact.Repo --revision $zipformerRevision --local-dir $tempDir
        if ($LASTEXITCODE -ne 0) {
            throw "Download of $($artifact.Repo) failed with exit code $LASTEXITCODE."
        }
        Move-Item -LiteralPath (Join-Path $tempDir $artifact.Repo) -Destination $targetPath -Force
        Remove-Item -LiteralPath $tempDir -Recurse -Force
    }
    $hash = Get-FileHash -LiteralPath $targetPath -Algorithm SHA256
    "$($hash.Hash.ToLowerInvariant())  $($artifact.Local)" |
        Set-Content -LiteralPath "$targetPath.sha256" -Encoding utf8
    [pscustomobject]@{
        Repository      = $zipformerRepo
        Revision        = $zipformerRevision
        RepoFilename    = $artifact.Repo
        LocalFilename   = $artifact.Local
        License         = $zipformerLicense
        Sha256          = $hash.Hash.ToLowerInvariant()
        SizeBytes       = (Get-Item -LiteralPath $targetPath).Length
        DownloadedAtUtc = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath "$targetPath.metadata.json" -Encoding utf8
}

Write-Output "STT model ready: $modelOutputDir"
Write-Output "License: $zipformerLicense (non-commercial, no-derivatives)"
Write-Output ""
Write-Output "TTS setup is manual: download a Vietnamese Piper voice (.onnx + .onnx.json)"
Write-Output "from https://github.com/rhasspy/piper/blob/master/VOICES.md into $resolvedOutputDir"
Write-Output "as vi_VN-piper.onnx (matching Settings.tts_model_path default)."
