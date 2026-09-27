# Cập nhật code trên VPS — sổ tay redeploy

Tách riêng khỏi `docs/deploy_vps_thuc_te_2026-08-21.md` (dựng máy lần đầu, làm một
lần) vì việc này lặp lại **mỗi lần đẩy code mới lên GitHub**. Máy: LANIT
`103.146.23.41`, domain `https://c4-app-192.io.vn/`. Theo
[[cap-nhat-runbook-md-lien-tuc]] — file này cập nhật ngay khi có lệnh thật chạy qua,
không đợi gộp cuối buổi.

## Câu hỏi đầu tiên: cái gì đổi, quyết định cái gì phải build lại

**Không có "cập nhật" chung chung — chỉ có bốn loại thay đổi, mỗi loại một đường
khác nhau.** Chạy nhầm đường (ví dụ `restart` thay vì `build`) thì lệnh chạy xong
không báo lỗi gì, nhưng code cũ vẫn đang chạy — loại lỗi im lặng nguy hiểm nhất.

| Đổi cái gì | Có cần build lại? | Lệnh |
|---|---|---|
| `src/**/*.py`, `requirements*.txt`, `Dockerfile` | **Có — rebuild image backend** | §2 |
| `frontend/src/**`, `frontend/package.json` | **Có — build lại frontend** | §3 |
| `.env` (biến backend đọc lúc chạy: `CORS_ORIGINS`, `SLM_*`, `MQTT_*`...) | Không build, nhưng phải **tái tạo container** | §4 |
| `frontend/.env.production` (biến `NEXT_PUBLIC_*`) | **Có — build lại frontend**, `restart` không đủ | §3 |
| `frontend/.env.runtime` (biến server-side, không `NEXT_PUBLIC_`) | Không build, chỉ `systemctl restart vivi-frontend` | §3.3 |
| `deploy/vps/vivi-slm.service`, `slm_warmup.sh` | Không build, chỉ cài lại unit + `daemon-reload` | §5 |
| `deploy/vps/Caddyfile` | Không build, chỉ `caddy validate` + `reload` | §6 |

## 0. Luôn bắt đầu bằng `git pull` — và đọc kỹ `git status` trước

**Trên VPS, đứng ở đâu cũng được:**

```bash
cd /opt/vivi && git status --short
```

Chỉ được thấy dòng `??` (untracked — `models/slm/`, `tools/llama/`, đúng vì chúng
nằm ngoài git) hoặc `M` ở đúng 4 file `models/voice/*.metadata.json` /
`*.sha256` (khác biệt CRLF/LF vô hại, xem `deploy_vps_thuc_te_2026-08-21.md` mục
V16b). **Thấy `M` ở file khác thì DỪNG** — có thay đổi tay chưa commit trên máy này,
`git pull` có thể conflict hoặc âm thầm ghi đè.

```bash
cd /opt/vivi && git pull
```

```bash
cd /opt/vivi && git log --oneline -1
```

So hai commit hash trước/sau `git pull` — nếu **giống nhau** thì không có gì mới,
dừng lại ở đây, không cần làm gì tiếp.

### Xem đúng cái gì vừa đổi, để biết đi nhánh nào ở bảng trên

```bash
cd /opt/vivi && git diff --stat HEAD@{1} HEAD
```

Đọc cột file để chọn từ §2 đến §6 — có thể phải làm **nhiều nhánh cùng lúc** nếu một
commit đụng cả backend lẫn frontend.

## 1. `models/voice/` đổi — kiểm trước khi lo

Nếu `git status` báo `M` ở 4 file metadata giọng nói, kiểm nội dung thật khác hay chỉ
khác xuống dòng:

```bash
cd /opt/vivi && git diff models/voice/vi_VN-piper.onnx.metadata.json
```

Rỗng hoặc chỉ khác `DownloadedAtUtc` → bình thường, đi tiếp. Khác `Sha256` hoặc
`SizeBytes` → **dừng, đây là dấu hiệu file `.onnx` trên máy không khớp file nhóm đã
kiểm** — không tự sửa, hỏi lại.

## 2. Backend đổi (`src/`, `requirements*.txt`, `Dockerfile`)

```bash
tmux new -s deploy-backend
```

```bash
cd /opt/vivi && docker compose build backend
```

Đo được **513,9 s ≈ 8,6 phút** trên 4 vCPU (2026-08-21); nhanh hơn trên máy đã nâng
5 vCPU nhưng chưa đo lại. Thoát tmux mà giữ chạy: `Ctrl+B` rồi `D`.

```bash
cd /opt/vivi && docker compose up -d backend
```

**`up -d`, không phải `restart`** — container mới nướng đúng image vừa build.

```bash
curl -s https://c4-app-192.io.vn/healthz | python3 -m json.tool
```

Tất cả thành phần phải `ready` (hoặc `llm: disabled`/`ready` tuỳ đã bật SLM chưa).

## 3. Frontend đổi

### 3.1. Nếu `package.json`/`package-lock.json` đổi — cài lại phụ thuộc

```bash
cd /opt/vivi/frontend && npm ci
```

### 3.2. Luôn build lại khi có code hoặc `NEXT_PUBLIC_*` đổi

`NEXT_PUBLIC_*` bị nướng vào JS lúc build — `systemctl restart` không đọc lại được
biến này, phải build.

```bash
cd /opt/vivi/frontend && npm run build
```

`Killed` = OOM (RAM đang bận SLM), khi đó:

```bash
sudo systemctl stop vivi-slm
```

```bash
cd /opt/vivi/frontend && npm run build
```

```bash
sudo systemctl start vivi-slm
```

### 3.3. Nếu chỉ `frontend/.env.runtime` đổi (route `/api/auth/demo-driver` đọc lúc
chạy, không phải `NEXT_PUBLIC_*`) — không cần build, chỉ cần khởi động lại:

```bash
sudo systemctl restart vivi-frontend
```

### 3.4. Sau MỌI lần build — bắt lỗi quên đổi domain

```bash
grep -rl "localhost:8000" /opt/vivi/frontend/.next/static/ | head
```

**Trống = đúng.** Ra kết quả nghĩa là `.env.production` không trỏ đúng domain lúc
build — sửa `frontend/.env.production` rồi build lại, đừng bỏ qua bước này: đây là
lỗi mà chính người deploy **không tự phát hiện được** khi test qua SSH tunnel, vì
`localhost:8000` trên máy họ *có thật*.

```bash
sudo systemctl restart vivi-frontend
```

## 4. `.env` đổi (biến backend, không phải frontend)

```bash
cd /opt/vivi && docker compose up -d backend
```

**Không phải `restart`.** `docker compose restart` khởi động lại container với cấu
hình **cũ** — nó không đọc lại `.env`. Chỉ `up -d` mới tái tạo container và nạp biến
mới. Cùng bẫy với `NEXT_PUBLIC_*` ở §3.2, khác cơ chế.

Kiểm biến đã vào tới container chưa:

```bash
cd /opt/vivi && docker compose exec backend printenv <TÊN_BIẾN>
```

## 5. `vivi-slm.service` / `slm_warmup.sh` đổi

```bash
scp "D:\HASON\2025.2\VIN\P192\P-192\deploy\vps\vivi-slm.service" vivi@103.146.23.41:~/vivi-slm.service
```

**Trên VPS:**

```bash
sudo cp ~/vivi-slm.service /etc/systemd/system/vivi-slm.service
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart vivi-slm
```

```bash
sudo journalctl -u vivi-slm -n 20 --no-pager | grep -E "warmup|Main PID"
```

> **Bẫy đã vấp 2026-08-22:** `ExecStart`/`WorkingDirectory` phải trỏ đúng
> `/opt/vivi/tools/llama/llama-b10358/` (có tên phiên bản), không phải
> `/opt/vivi/tools/llama/` trần — sai thì systemd báo `status=203/EXEC`
> (không tìm thấy file để exec), còn `slm_warmup.sh` vẫn chạy đơn độc, chờ đủ 120 s
> rồi tự thoát với thông báo "server khong len sau 120s — bo qua", **không có gì báo
> lỗi rõ ràng** ngoài dòng đó trong journal.

Nếu `src/agents/slm.py` đổi phần `SLM_UNION_PROMPT`, **bắt buộc** kiểm lại
`scripts/spike3_prompt.txt` còn khớp không — lệch thì warm-up nạp sai tiền tố và trở
nên vô dụng trong im lặng:

**Trên Windows (PowerShell), tại thư mục gốc repo:**

```powershell
python -c "import io,re,ast; u=ast.literal_eval(re.search(r'^SLM_UNION_PROMPT = (\'.*?\')\n', io.open('src/agents/slm.py',encoding='utf-8').read(), re.S|re.M).group(1)); s=io.open('scripts/spike3_prompt.txt',encoding='utf-8').read(); print('KHOP' if u==s else 'DA TROI — dong bo lai scripts/spike3_prompt.txt')"
```

Lệch thì đồng bộ:

```powershell
python -c "import io,re,ast; u=ast.literal_eval(re.search(r'^SLM_UNION_PROMPT = (\'.*?\')\n', io.open('src/agents/slm.py',encoding='utf-8').read(), re.S|re.M).group(1)); io.open('scripts/spike3_prompt.txt','w',encoding='utf-8',newline='\n').write(u)"
```

## 6. `Caddyfile` đổi (đổi domain, thêm route...)

```bash
scp "D:\HASON\2025.2\VIN\P192\P-192\deploy\vps\Caddyfile" vivi@103.146.23.41:~/Caddyfile
```

**Trên VPS:**

```bash
sudo cp ~/Caddyfile /etc/caddy/Caddyfile
```

**Luôn `validate` trước khi `reload`** — cấu hình sai mà cứ áp là đốt hạn mức Let's
Encrypt (5 lần thất bại/giờ cho mỗi domain):

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

```bash
sudo systemctl reload caddy
```

```bash
curl -sI https://c4-app-192.io.vn/healthz | head -3
```

## 7. Kiểm cuối — chạy sau MỌI lần cập nhật, bất kể đổi gì

```bash
curl -s https://c4-app-192.io.vn/healthz | python3 -m json.tool
```

```bash
grep -rl "localhost:8000" /opt/vivi/frontend/.next/static/ | head
```

```bash
docker compose -f /opt/vivi/docker-compose.yml ps
```

Ba container `mqtt`, `vehicle-simulator`, `backend` đều `Up`/`healthy`. Mở
`https://c4-app-192.io.vn/` từ **điện thoại tắt WiFi (4G)** — phép thử không có SSH
tunnel nào che giấu lỗi domain.

## 8. Việc KHÔNG cần làm mỗi lần cập nhật

- **Không** cần đổi lại DNS, chứng chỉ Caddy đã cấp thì tự gia hạn.
- **Không** cần chạy lại `bootstrap_mqtt_secrets.ps1` — mật khẩu MQTT không đổi trừ
  khi cố tình xoay.
- **Không** cần tải lại model 3B hay llama.cpp — chúng nằm ngoài git, `git pull`
  không đụng tới (xác nhận: `git diff --stat` giữa hai mốc không có `models/` trừ
  khi đúng là commit đó đổi model).
