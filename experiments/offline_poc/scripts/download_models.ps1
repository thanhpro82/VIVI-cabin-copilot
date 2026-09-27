[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("qwen25-05b-q4", "qwen25-3b-q4", "qwen25-3b-q8", "qwen3-4b-q4")]
    [string]$Profile,

    [string]$OutputDir = (Join-Path $PSScriptRoot "..\models"),

    [string]$HfExecutable,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$artifacts = @{
    "qwen25-05b-q4" = [pscustomobject]@{
        Repository = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
        Revision = "9217f5db79a29953eb74d5343926648285ec7e67"
        FileName = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
        License = "Apache-2.0"
    }
    "qwen25-3b-q4" = [pscustomobject]@{
        Repository = "Qwen/Qwen2.5-3B-Instruct-GGUF"
        Revision = "7dabda4d13d513e3e842b20f0d435c732f172cbe"
        FileName = "qwen2.5-3b-instruct-q4_k_m.gguf"
        License = "Qwen Research"
    }
    # The-he moi, va giay phep RONG HON han: Apache-2.0 thay vi Qwen Research.
    # Them 19/08 vi phep chan doan cho thay nut that o tang tom tat la CHAT LUONG
    # MODEL chu khong phai cong kiem: tren rieng cac ca ban tom duoc nhan, Qwen2.5-3B
    # van kem cau trich nguyen van 12-28 diem o moi muc dung sai.
    # Xem eval/results/tom-tat/.
    "qwen3-4b-q4" = [pscustomobject]@{
        Repository = "lmstudio-community/Qwen3-4B-Instruct-2507-GGUF"
        Revision = "4edb920b6f14e3b9284d4502a6485103d72cde05"
        FileName = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
        License = "Apache-2.0"
    }
    "qwen25-3b-q8" = [pscustomobject]@{
        Repository = "Qwen/Qwen2.5-3B-Instruct-GGUF"
        Revision = "7dabda4d13d513e3e842b20f0d435c732f172cbe"
        FileName = "qwen2.5-3b-instruct-q8_0.gguf"
        License = "Qwen Research"
    }
}

$artifact = $artifacts[$Profile]
$resolvedOutputDir = [IO.Path]::GetFullPath($OutputDir)
$targetPath = Join-Path $resolvedOutputDir $artifact.FileName
$workspaceHf = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..\..\..\.venv\Scripts\hf.exe")
)
if (-not $HfExecutable) {
    if (Test-Path -LiteralPath $workspaceHf -PathType Leaf) {
        $HfExecutable = $workspaceHf
    }
    else {
        $hfCommand = Get-Command hf -ErrorAction SilentlyContinue
        if ($hfCommand) {
            $HfExecutable = $hfCommand.Source
        }
    }
}

if ($DryRun) {
    [pscustomobject]@{
        Profile = $Profile
        Repository = $artifact.Repository
        Revision = $artifact.Revision
        FileName = $artifact.FileName
        License = $artifact.License
        TargetPath = $targetPath
        HfExecutable = $HfExecutable
    } | ConvertTo-Json
    exit 0
}

if (-not $HfExecutable -or -not (Test-Path -LiteralPath $HfExecutable -PathType Leaf)) {
    throw "Hugging Face CLI 'hf' was not found. Install huggingface_hub first."
}

New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null

& $HfExecutable download $artifact.Repository $artifact.FileName `
    --revision $artifact.Revision `
    --local-dir $resolvedOutputDir
if ($LASTEXITCODE -ne 0) {
    throw "Model download failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
    throw "Downloaded artifact was not found at $targetPath."
}

$hash = Get-FileHash -LiteralPath $targetPath -Algorithm SHA256
$checksumPath = "$targetPath.sha256"
"$($hash.Hash.ToLowerInvariant())  $($artifact.FileName)" |
    Set-Content -LiteralPath $checksumPath -Encoding utf8

$metadataPath = "$targetPath.metadata.json"
[pscustomobject]@{
    Profile = $Profile
    Repository = $artifact.Repository
    Revision = $artifact.Revision
    FileName = $artifact.FileName
    License = $artifact.License
    Sha256 = $hash.Hash.ToLowerInvariant()
    SizeBytes = (Get-Item -LiteralPath $targetPath).Length
    DownloadedAtUtc = [DateTime]::UtcNow.ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath $metadataPath -Encoding utf8

Write-Output "Downloaded: $targetPath"
Write-Output "SHA-256: $($hash.Hash.ToLowerInvariant())"
Write-Output "Metadata: $metadataPath"
