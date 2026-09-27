param(
    [string]$Model,
    [ValidateSet("cpu6","cpu12","vulkan")][string]$Backend,
    # Chuoi con cua TEN thiet bi Vulkan, vd "RX 5500M" hoac "Radeon(TM) Graphics".
    # Bat buoc khi -Backend vulkan. KHONG nhan so thu tu: xem chu thich duoi.
    [string]$Device,
    [int]$Port = 8093,
    [switch]$Stop
)
$ErrorActionPreference = "Stop"
$bin = Join-Path $PSScriptRoot "..\tools\llama-vulkan\llama-server.exe"
$logDir = Join-Path $PSScriptRoot "..\eval\results\spike-003"

if ($Stop) { Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force; exit 0 }
if (-not $Model -or -not $Backend) { throw "Can -Model va -Backend (hoac -Stop)" }

# Kiem checksum model truoc khi load - ky luat "no unverified artifacts".
$side = "$Model.sha256"
if (-not (Test-Path $side)) { throw "Thieu sidecar $side" }
$want = (Get-Content $side).Split(" ")[0].Trim().ToLower()
$have = (Get-FileHash $Model -Algorithm SHA256).Hash.ToLower()
if ($want -ne $have) { throw "Checksum lech: $Model" }

# --- Do thiet bi theo TEN, khong bao gio hardcode so thu tu ---
#
# Ban truoc cua file nay ghi cung "--device Vulkan1" kem chu thich "Vulkan1 = RX
# 5500M". Ngay 13/08/2026 `--list-devices` tren cung may nay tra ve THU TU NGUOC
# LAI: Vulkan0 = RX 5500M (rHoi), Vulkan1 = Radeon(TM) Graphics (tich hop).
#
# Nghia la so thu tu Vulkan khong on dinh giua cac lan boot/driver, va moi con so
# cua ADR-016 gan nhan "dGPU" deu KHONG con chung minh duoc la do tren dGPU. Do la
# mot lo hong bang chung, khong phai mot chi tiet cau hinh.
#
# Nen: nhan ten, doi khop DUNG MOT thiet bi, va ghi ten da resolve ra device-last.json
# de manifest lay tu do. Nhan phai do may dien, khong do nguoi go.
$resolved = @{ backend = $Backend; device_ordinal = $null; device_name = $null; requested = $Device }
$flags = @("-m", "`"$Model`"", "--host", "127.0.0.1", "--port", $Port, "-c", "2048",
           "--cache-reuse", "256")
switch ($Backend) {
    "cpu6"   { $flags += @("-t", "6",  "-ngl", "0"); $resolved.device_name = "cpu (6 threads)" }
    "cpu12"  { $flags += @("-t", "12", "-ngl", "0"); $resolved.device_name = "cpu (12 threads)" }
    "vulkan" {
        if (-not $Device) { throw "-Backend vulkan can -Device '<mot phan ten thiet bi>'. Chay: $bin --list-devices" }
        # Do thiet bi bang scripts/vulkan_devices.py, KHONG regex trong PowerShell.
        #
        # Ly do (Thanh nêu o PR #114, phoenix nêu cung cho): parser an vao output cua
        # mot chuong trinh ben ngoai, tuc thu doi duoc ma khong ai bao truoc — no can
        # unit test. Ma CI chay ubuntu-latest nen test Pester se bi bo qua dung o cho
        # can nhat. Dat o Python thi no chay trong suite binh thuong, va chi co MOT
        # cai dat thay vi hai ban regex phai giu dong bo.
        $venvPy = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
        $py = if (Test-Path $venvPy) { $venvPy } else { "python" }
        $dong = (& $py -m scripts.vulkan_devices --match $Device --bin $bin)
        if ($LASTEXITCODE -ne 0) { throw "khong chon duoc thiet bi cho -Device '$Device'" }
        $phan = $dong.Trim() -split "`t", 2
        if ($phan.Count -ne 2 -or $phan[0] -notmatch '^([A-Za-z]+)(\d+)$') {
            throw "vulkan_devices tra ve la: '$dong'"
        }
        $flags += @("-ngl", "99", "--device", $phan[0])
        $resolved.device_ordinal = [int]$Matches[2]
        $resolved.device_name = $phan[1]
    }
}

New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "server-last.log"
# Bat CA stdout: llama.cpp in dong "Device 0: ..." va so lop offload ra stdout, con
# ban truoc chi bat stderr - nen log khong chung minh duoc run da chay tren GPU nao.
# Do dung la lo hong da lam ca bang dGPU cua ADR-016 mat kha nang kiem chung.
$logOut = Join-Path $logDir "server-last.out.log"
$resolved | ConvertTo-Json | Out-File (Join-Path $logDir "device-last.json") -Encoding utf8
$p = Start-Process -FilePath $bin -ArgumentList $flags -PassThru -WindowStyle Hidden `
     -RedirectStandardError $log -RedirectStandardOutput $logOut
# Cho health toi da 120 s (lan dau Vulkan compile shader co the lau)
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    try {
        $null = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2
        Write-Host "server pid=$($p.Id) backend=$Backend device=$($resolved.device_name) model=$(Split-Path $Model -Leaf)"
        exit 0
    } catch { Start-Sleep -Milliseconds 500 }
}
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
throw "llama-server khong len health trong 120s - xem $log"
