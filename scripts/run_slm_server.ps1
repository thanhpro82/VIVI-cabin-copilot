param(
    [string]$Model,
    [int]$Port = 8093,
    # BAT BUOC. "cpu" = khong offload; nguoc lai la MOT PHAN TEN thiet bi, vi du
    # "RTX 3050". KHONG con "auto" - xem khoi chu thich duoi.
    [string]$Device,
    [int]$Threads = 0,          # 0 = so nhan vat ly
    [switch]$Stop
)
$ErrorActionPreference = "Stop"
$bin = Join-Path $PSScriptRoot "..\tools\llama-vulkan\llama-server.exe"
$logDir = Join-Path $PSScriptRoot "..\eval\results\spike-003"

if ($Stop) { Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force; exit 0 }
if (-not $Model) { throw "Can -Model (hoac -Stop)" }
# Kiem tham so TRUOC kiem checksum: quen -Device la loi CACH GOI, con checksum lech
# la loi TOAN VEN. Bao loi cach goi truoc, vi khong sua duoc toan ven khi lenh goi
# con chua dung.
if (-not $Device) {
    Write-Host "Thiet bi hien co:"
    & $bin --list-devices 2>&1 | Write-Host
    throw "-Device la BAT BUOC. Dung 'cpu', hoac mot phan ten thiet bi o tren, vi du: -Device 'RTX 3050'"
}

# Kiem checksum model truoc khi load - ky luat "no unverified artifacts".
$side = "$Model.sha256"
if (-not (Test-Path $side)) { throw "Thieu sidecar $side" }
$want = (Get-Content $side).Split(" ")[0].Trim().ToLower()
if ($want -ne (Get-FileHash $Model -Algorithm SHA256).Hash.ToLower()) { throw "Checksum lech: $Model" }

# ADR-016: khong hardcode may-rieng. Threads = so nhan vat ly (SMT gay hai, bac A).
if ($Threads -le 0) {
    $Threads = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfCores -Sum).Sum
}

# --- Chon thiet bi (issue #145) ----------------------------------------------
#
# Ban truoc mac dinh `-Device auto`, va `auto` chon thiet bi Vulkan co VRAM LON NHAT.
# iGPU khai bao RAM he thong chia se nen no thuong lon hon VRAM that cua dGPU:
#
#     Vulkan0: AMD Radeon(TM) Graphics        (8034 MiB)   <- auto chon cai nay
#     Vulkan1: NVIDIA GeForce RTX 3050 Laptop (3962 MiB)   <- dGPU that
#
# Script in "auto-chon device: Vulkan0" roi chay ngon lanh, con nguoi do thi TUONG
# minh dang do dGPU. Do that cho thay khac biet that: 8,17 s tren iGPU so voi 3,81 s
# tren dGPU cho cung mot cau.
#
# Ky luat evidence cua repo doi moi so do phai kem TANG PHAN CUNG, va cai bay nay pha
# dung cho do — mot cach IM LANG. Hardcode `--device Vulkan1` cua ban cu con te hon ve
# tinh dung, nhung `auto` te hon ve tinh PHAT HIEN DUOC: hardcode it ra con bat nguoi
# ta nhin, con `auto` trong nhu da lo ho ban roi.
#
# Nen bo han `auto`. Doan mot cach im lang khong duoc thay bang doan thong minh hon —
# no duoc thay bang KHONG DOAN. Day cung la cach `scripts/spike3_server.ps1` da giai,
# va dung lai co che ay thay vi dung cai thu ba.
$resolved = @{ requested = $Device; device_spec = $null; device_name = $null; threads = $Threads }

$flags = @("-m", "`"$Model`"", "--host", "127.0.0.1", "--port", $Port, "-c", "2048",
           "--cache-reuse", "256", "-t", $Threads)

if ($Device -eq "cpu") {
    $flags += @("-ngl", "0")
    $resolved.device_name = "cpu ($Threads threads)"
} else {
    # Do bang scripts/vulkan_devices.py, KHONG regex trong PowerShell: parser an vao
    # output cua mot chuong trinh ben ngoai nen no can unit test, ma CI chay
    # ubuntu-latest thi test Pester bi bo qua dung o cho can nhat. Ham do cung TU CHOI
    # DOAN khi mot chuoi khop nhieu hon mot thiet bi.
    $venvPy = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
    $py = if (Test-Path $venvPy) { $venvPy } else { "python" }
    $dong = (& $py -m scripts.vulkan_devices --match $Device --bin $bin)
    if ($LASTEXITCODE -ne 0) { throw "khong chon duoc thiet bi cho -Device '$Device'" }
    $phan = $dong.Trim() -split "`t", 2
    if ($phan.Count -ne 2) { throw "vulkan_devices tra ve la: '$dong'" }
    $flags += @("-ngl", "99", "--device", $phan[0])
    $resolved.device_spec = $phan[0]
    $resolved.device_name = $phan[1]
}

# In CA danh sach chu khong chi cai duoc chon: nguoi do phai thay minh dang bo qua cai
# gi, nhat la tren may co ca iGPU lan dGPU.
Write-Host "Thiet bi hien co:"
& $bin --list-devices 2>&1 | Write-Host
Write-Host "-> dung: $($resolved.device_name)"

# Ghi ten da resolve ra device-last.json de manifest cua lan do lay tu do. Nhan phai do
# MAY dien, khong do nguoi go — mot con so khong duoc phep roi khoi tang phan cung cua no.
New-Item -ItemType Directory -Force $logDir | Out-Null
$resolved | ConvertTo-Json | Out-File (Join-Path $logDir "device-last.json") -Encoding utf8

$p = Start-Process -FilePath $bin -ArgumentList $flags -PassThru -WindowStyle Hidden
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    try {
        $null = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2
        Write-Host "slm-server pid=$($p.Id) device=$($resolved.device_name) threads=$Threads model=$(Split-Path $Model -Leaf)"
        exit 0
    } catch { Start-Sleep -Milliseconds 500 }
}
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
throw "llama-server khong len health trong 120s"
