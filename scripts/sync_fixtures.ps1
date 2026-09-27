# Đồng bộ fixture dùng chung sang frontend.
#
# Nguồn sự thật là `src/fixtures/*.json`. Next.js không import được file ngoài thư mục
# project của nó, nên frontend đọc một bản sao trong `frontend/src/lib/fixtures/`.
# Bản sao là thứ SINH RA — đừng sửa tay. `tests/test_services/test_fixtures.py` so từng
# byte hai bản, nên sửa tay một bên là CI đỏ.
#
#   pwsh scripts/sync_fixtures.ps1
#
# Chạy lại sau mỗi lần đổi `src/fixtures/*.json`, rồi commit cả hai bên trong cùng một
# commit. Hai bên nằm ở hai commit khác nhau nghĩa là có một khoảng thời gian repo tự
# mâu thuẫn với chính nó.

$ErrorActionPreference = "Stop"

# Không có dòng này thì dấu tiếng Việt trong Write-Output ra ký tự hỏi trên console
# Windows mặc định — script chạy đúng nhưng nhìn như hỏng.
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$goc = Split-Path -Parent $PSScriptRoot
$nguon = Join-Path $goc "src/fixtures"
$dich = Join-Path $goc "frontend/src/lib/fixtures"

if (-not (Test-Path $nguon)) { throw "Không thấy thư mục nguồn: $nguon" }
if (-not (Test-Path $dich)) { New-Item -ItemType Directory -Force -Path $dich | Out-Null }

$soFile = 0
foreach ($file in Get-ChildItem -Path $nguon -Filter "*.json") {
    Copy-Item -Path $file.FullName -Destination (Join-Path $dich $file.Name) -Force
    Write-Output "  $($file.Name)"
    $soFile++
}

Write-Output "Đã đồng bộ $soFile file: $nguon -> $dich"
