# Dựng chỉ mục RAG cho sổ tay VF9 từ corpus có sẵn trên máy.
# KHÔNG tải gì từ mạng: agent_spec.md cấm network lúc chạy, và corpus có bản quyền.
[CmdletBinding()]
param(
    [string]$CorpusDir = "VF9_2026_vi",
    [string]$ManualDir = "data/manuals/vf9_2026_vi",
    [switch]$SkipChecksum
)
$ErrorActionPreference = "Stop"
$python = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $CorpusDir)) {
    throw "Khong thay corpus tai '$CorpusDir'. Corpus khong nam trong git - xem $CorpusDir/README.md."
}
foreach ($needed in @("manifest.json", "html", "pdf")) {
    if (-not (Test-Path (Join-Path $CorpusDir $needed))) {
        throw "Corpus thieu '$needed'. Ingest can ca html/ (noi dung) lan pdf/ (so trang)."
    }
}

if (-not $SkipChecksum) {
    $sumFile = Join-Path $CorpusDir "corpus.sha256"
    if (Test-Path $sumFile) {
        Write-Host "Dang verify checksum corpus..."
        $root = (Resolve-Path $CorpusDir).Path
        $bad = 0
        # -Encoding utf8 la bat buoc: ten chuong trong so tay co dau tieng Viet, doc
        # bang codepage ANSI mac dinh se bien "06_Lai xe" thanh rac va bao thieu 116 file.
        foreach ($line in Get-Content $sumFile -Encoding utf8) {
            if (-not $line.Trim()) { continue }
            $parts = $line -split '\s+', 2
            $path = Join-Path $root ($parts[1] -replace '/', '\')
            if (-not (Test-Path $path)) { Write-Warning "thieu: $($parts[1])"; $bad++; continue }
            $actual = (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $parts[0]) { Write-Warning "lech: $($parts[1])"; $bad++ }
        }
        if ($bad -gt 0) {
            throw "$bad file lech/thieu so voi corpus.sha256. Index sinh ra se khong tai lap duoc."
        }
        Write-Host "Checksum khop."
    }
}

New-Item -ItemType Directory -Force -Path $ManualDir | Out-Null
foreach ($item in @("manifest.json", "html", "pdf")) {
    Copy-Item -Path (Join-Path $CorpusDir $item) -Destination $ManualDir -Recurse -Force
}

& $python -m src.rag.cli --manual $ManualDir ingest
if (-not $?) { throw "ingest that bai" }
& $python -m src.rag.cli --manual $ManualDir verify
if (-not $?) { throw "verify that bai - index khong dat cong chat luong" }

Write-Host "Xong. Index tai data/rag/vf9_2026_vi/"
