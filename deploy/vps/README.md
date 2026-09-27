# `deploy/vps/` — file cấu hình soạn sẵn cho VPS

## Vì sao thư mục này tồn tại

Runbook gốc dựng các file cấu hình bằng **heredoc** (`cat > file <<'EOF' … EOF`).
Cách đó hỏng khi chép từ khung code: trình duyệt/terminal thêm **2 dấu cách** vào mọi
dòng sau dòng đầu, làm hai thứ gãy cùng lúc —

- dòng đóng `EOF` bị thụt vào nên bash **không nhận ra dấu kết thúc**, treo ở dấu
  nhắc `>` và nuốt luôn chữ `EOF` vào nội dung file;
- YAML thì khoá cấp cao nhất (`services:`) không còn ở cột 0.

Nên toàn bộ nội dung nhiều dòng chuyển thành **file thật**, `scp` lên rồi `cp` vào
chỗ. Không còn khối nào phải dán.

## Cách dùng

**Trên PowerShell (máy Windows), tại thư mục gốc repo:**

```powershell
scp -r deploy\vps vivi@103.146.23.41:/tmp/
```

**Trên VPS**, mỗi lệnh một dòng — xem `docs/deploy_vps_thuc_te_2026-08-21.md` mục
tương ứng để biết chạy lệnh nào ở bước nào.

## Có gì trong đây

| File | Đặt vào đâu | Bước | Ghi chú |
|---|---|---|---|
| `daemon.json` | `/etc/docker/daemon.json` | V6 | Xoay vòng log, `no-new-privileges` |
| `env.runtime` | `/opt/vivi/frontend/.env.runtime` | V16 | **`chmod 600`** sau khi chép |
| `env.production.tunnel` | `/opt/vivi/frontend/.env.production` | V15 | Bản **chưa có tên miền** |
| `env.production.domain` | `/opt/vivi/frontend/.env.production` | 7.4 | Bản **có tên miền**, phải `sed` thay `DOMAIN_PLACEHOLDER` |
| `vivi-frontend.service` | `/etc/systemd/system/` | V18 | |
| `vivi-slm.service` | `/etc/systemd/system/` | 8.4 | `-t 5` (5 nhân vật lý sau khi nâng vCPU 2026-08-22); sửa nếu số nhân khác |
| `Caddyfile` | `/etc/caddy/Caddyfile` | 7.5 | Phải `sed` thay `DOMAIN_PLACEHOLDER` |

## Hai chỗ có placeholder

`env.production.domain` và `Caddyfile` chứa chuỗi `DOMAIN_PLACEHOLDER`. Thay bằng tên
miền thật **sau khi đã chép vào chỗ**:

```bash
sudo sed -i 's|DOMAIN_PLACEHOLDER|vivi.id.vn|g' /etc/caddy/Caddyfile
```

```bash
sed -i 's|DOMAIN_PLACEHOLDER|vivi.id.vn|g' /opt/vivi/frontend/.env.production
```

Kiểm không còn chuỗi nào sót:

```bash
grep -rn DOMAIN_PLACEHOLDER /etc/caddy/Caddyfile /opt/vivi/frontend/.env.production
```

Không in gì là đúng.

## Cái thư mục này KHÔNG chứa

- **`.env` của backend** — nó có mật khẩu MQTT sinh ngẫu nhiên **trên chính VPS**
  (bước V11), nên không soạn trước được. Sửa bằng `nano` trên máy chủ.
- **Model và chỉ mục RAG** — `models/voice/` và `data/rag/` nằm ngoài git, đi bằng
  `scp` riêng ở bước W6.
- **`config/mosquitto/passwd`** — sinh tại chỗ, **không bao giờ commit**.
- **`docker-compose.override.yml`** — `.gitignore:65` bỏ qua **tên file này ở mọi
  cấp thư mục**, nên bản mẫu *không thể* nằm trong `deploy/vps/` — bảng trên vì thế
  không có dòng nào cho nó. Tạo thẳng trên VPS bằng heredoc ở bước **V12** —
  `docs/deploy_ubuntu24_tung_buoc.md`, mục *“Ép backend chỉ nghe loopback”*. Thẻ
  `!override` trong đó là **bắt buộc**: thiếu nó Compose *gộp* danh sách `ports`
  chứ không thay thế, và `"8000:8000"` vẫn mở API ra Internet không HTTPS.
