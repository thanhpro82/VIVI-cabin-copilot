# Sinh password cho hai identity MQTT và ghi file passwd cho Mosquitto.
#
# docs/devops.md yêu cầu MQTT_ALLOW_ANONYMOUS=false với hai identity tách biệt.
# Chạy một lần trước `docker compose up`. File sinh ra KHÔNG được commit.
#
#   pwsh scripts/bootstrap_mqtt_secrets.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$configDir = Join-Path $repoRoot "config/mosquitto"
$passwdFile = Join-Path $configDir "passwd"
$envFile = Join-Path $repoRoot ".env"

function New-Password {
    $bytes = New-Object byte[] 24
    # RandomNumberGenerator::Fill là API .NET Core/5+, không có trên .NET Framework
    # mà Windows PowerShell 5.1 chạy — script sẽ chết ngay nếu gọi nó. Create().GetBytes()
    # có trên cả hai, nên script chạy được bằng `powershell` lẫn `pwsh`.
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes) -replace '[+/=]', 'x'
}

if (Test-Path $passwdFile) {
    Write-Host "$passwdFile đã tồn tại — xoá đi nếu muốn xoay vòng mật khẩu." -ForegroundColor Yellow
    exit 0
}

$backendPassword = New-Password
$simulatorPassword = New-Password

# mosquitto_passwd nằm trong image, không cần cài Mosquitto lên Windows.
# Mount cả thư mục để `-c` tự tạo file — nếu tạo sẵn file rỗng thì `-c` sẽ
# từ chối ghi với "File exists" và user đầu tiên không được thêm.
docker run --rm -v "${configDir}:/work" eclipse-mosquitto:2 `
    mosquitto_passwd -b -c /work/passwd vivi-backend $backendPassword
if ($LASTEXITCODE -ne 0) { throw "mosquitto_passwd -c thất bại" }

docker run --rm -v "${configDir}:/work" eclipse-mosquitto:2 `
    mosquitto_passwd -b /work/passwd vehicle-simulator $simulatorPassword
if ($LASTEXITCODE -ne 0) { throw "mosquitto_passwd (simulator) thất bại" }

# mosquitto_passwd tạo file 0600 thuộc root, trong khi broker chạy dưới user
# `mosquitto` (uid 1883) nên không đọc nổi -> container restart liên tục với
# "Unable to open pwfile". Chuyển sở hữu, vẫn giữ 0640 để không dính cảnh báo
# world-readable.
docker run --rm -v "${configDir}:/work" eclipse-mosquitto:2 `
    sh -c "chown 1883:1883 /work/passwd && chmod 0640 /work/passwd"
if ($LASTEXITCODE -ne 0) { throw "không đặt được quyền cho passwd" }

Write-Host "Đã tạo $passwdFile cho vivi-backend và vehicle-simulator." -ForegroundColor Green
Write-Host ""
Write-Host "Thêm vào $envFile :" -ForegroundColor Cyan
Write-Host "MQTT_BACKEND_USERNAME=vivi-backend"
Write-Host "MQTT_BACKEND_PASSWORD=$backendPassword"
Write-Host "MQTT_SIMULATOR_USERNAME=vehicle-simulator"
Write-Host "MQTT_SIMULATOR_PASSWORD=$simulatorPassword"
