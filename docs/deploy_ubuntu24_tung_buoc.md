# Deploy VIVI lên VPS Ubuntu 24.04 — hướng dẫn tuần tự, từng lệnh một

> Soạn 2026-08-21. Đây là **bản thi hành** của `docs/deploy_vps_fullstack.md`
> (hình dạng A: một máy chạy hết, một tên miền). File gốc giải thích *vì sao*;
> file này chỉ trả lời *gõ gì, ở đâu, trước đó phải có gì*.
>
> **Trạng thái: chưa ai chạy trọn quy trình trên VPS thật.** Mọi đường định
> tuyến và tên biến đã đối chiếu vào code ngày 2026-08-21.

## Quy ước đọc

Mỗi bước có 3 dòng cố định:

- **Máy:** `WINDOWS` (PowerShell trên máy Sơn) hoặc `VPS` (bash qua SSH)
- **Cần có trước:** điều kiện tiên quyết — thiếu là lệnh chạy sai, hoặc sai âm thầm
- **Đúng thì thấy:** dấu hiệu để biết bước đó xong

Ký hiệu thay thế: `<IP>` = IP VPS, `<domain>` = tên miền của bạn (ví dụ
`vivi.id.vn`), `<user-gh>` = tên tài khoản GitHub của bạn.

**Chép từng khối một.** Đừng dán cả loạt — mỗi lệnh có một kỳ vọng riêng.

---

# BẢNG TỔNG

| # | Máy | Việc |
|---|---|---|
| W1–W2 | WINDOWS | Khoá SSH, đưa khoá lên VPS |
| W3–W5 | WINDOWS | Chốt nhánh, kiểm artifact, kiểm checksum |
| V1–V7 | VPS | User `vivi`, tường lửa, **swap**, Docker, Node 22 |
| V8–V9 | VPS/WIN | Lấy mã nguồn (`git clone` **hoặc** `scp` tarball) |
| W6 | WINDOWS | `scp models/` + `data/rag/` — **bắt buộc, không bỏ được** |
| V10–V14 | VPS | `.env`, mật khẩu MQTT, override cổng, build, chạy backend |
| V15–V18 | VPS | `.env.production`, `.env.runtime`, build + systemd frontend |
| V19–V21 | VPS | Caddy + HTTPS |
| V22–V25 | VPS + trình duyệt | Kiểm chứng 4 tầng |
| V26–V31 | VPS | (tuỳ chọn) Bật SLM Qwen 3B |
| V32 | VPS | Vận hành: cập nhật, sao lưu, dọn cache |

---

# PHẦN 0 — TRƯỚC KHI GÕ LỆNH NÀO

## 0.1. Mua VPS — cấu hình tối thiểu

| | SLM **tắt** (mặc định, khuyến nghị) | SLM **bật** (Qwen 3B) |
|---|---|---|
| RAM | **4 GB** | **5 GB** |
| Đĩa | **25 GB** | **30 GB** |
| CPU | 2 vCPU chạy được, **4 vCPU nên chọn** | **4 nhân *vật lý*** — 2 nhân là hỏng |
| OS | **Ubuntu 24.04 LTS** | như trên |

**Tránh:** gói "shared/burstable" rẻ nhất, và CPU nền Xeon E5 v3/v4 (đời 2014–2016).
Lý do ở `deploy_vps_fullstack.md` mục 1.1.

## 0.2. Tên miền — **bắt buộc**, làm trước tiên

Không có tên miền = không có HTTPS = **micro không chạy** (`getUserMedia` chỉ chạy
trên secure context) và trang HTTPS không được phép gọi `http://<ip>:8000`.

**Làm ngay bây giờ, trước khi đọc tiếp:** vào trang quản trị DNS của nhà cung cấp
tên miền, tạo một bản ghi:

```
Type: A     Name: @ (hoặc tên subdomain)     Value: <IP VPS>     TTL: 300
```

DNS mất vài phút tới vài giờ để lan. Tới bước V19 là vừa kịp.

> Chưa có tên miền? `.id.vn` của VNNIC **miễn phí 2 năm** cho công dân VN 18–23
> tuổi, đăng ký qua iNET/PA/Nhân Hoà/Tenten. **Đừng dùng `nip.io`/`sslip.io`** —
> hạn mức Let's Encrypt của chúng đã cạn từ 02/2026.

## 0.3. Ba thứ **không** nằm trong git — phải tự mang lên

| Thứ | Ở đâu trên máy Windows | Dung lượng | Đi bằng |
|---|---|---:|---|
| `models/voice/` (STT + TTS) | `<repo>/models/voice/` | **89 MB** | `scp` (W6) |
| `data/rag/vf9_2026_vi/` (chỉ mục FAISS) | `<repo>/data/rag/` | **2 MB** | `scp` (W6) |
| `qwen2.5-3b….gguf` (chỉ khi bật SLM) | `C:\vivi-models\` | **2,0 GB** | `scp` (V27) |

**`git clone` không mang theo ba thứ này.** Quên `models/voice/` thì
`docker compose build` **chết ngay lúc build** (Dockerfile có chốt chặn). Quên
`data/rag/` thì build vẫn xanh, container vẫn `healthy`, nhưng mọi câu tra sổ tay
trả về *"Tôi không tìm thấy thông tin này trong sổ tay xe."*

---

# PHẦN A — MÁY WINDOWS (chuẩn bị)

## W1. Tạo khoá SSH

- **Máy:** WINDOWS
- **Cần có trước:** không có gì
- **Đúng thì thấy:** hai file `id_ed25519` và `id_ed25519.pub`

Kiểm đã có khoá chưa:

```powershell
Get-ChildItem $env:USERPROFILE\.ssh\id_ed25519.pub
```

Chưa có thì tạo (Enter 3 lần để bỏ qua passphrase):

```powershell
ssh-keygen -t ed25519 -C "vivi-deploy"
```

## W2. Đưa khoá công khai lên VPS

- **Máy:** WINDOWS
- **Cần có trước:** VPS đã tạo, biết `<IP>` và mật khẩu `root` (nhà cung cấp gửi qua email)
- **Đúng thì thấy:** lần SSH sau không hỏi mật khẩu nữa

Nhiều nhà cung cấp cho dán khoá công khai ngay lúc tạo máy — nếu đã làm thì bỏ qua W2.

Xem nội dung khoá công khai:

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

Đẩy lên VPS (Windows **không có** `ssh-copy-id`, dùng cách này):

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@<IP> "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

Kiểm:

```powershell
ssh root@<IP> "hostnamectl; lsb_release -a"
```

Phải in `Ubuntu 24.04`. Không phải 24.04 thì **dừng lại** — hướng dẫn này viết cho
đúng bản đó (NodeSource `setup_22.x`, đường dẫn systemd, `get.docker.com`).

## W3. Chốt nhánh mã nguồn — bước dễ sai nhất

- **Máy:** WINDOWS, tại thư mục gốc repo
- **Cần có trước:** repo đã clone
- **Đúng thì thấy:** một dòng có chữ `requirements-voice`

**Vì sao có bước này.** Nhánh `develop` đang dùng `Dockerfile` boilerplate của môn
học — nó **chỉ** cài `requirements.txt`, **không** cài RAG và voice, **không** nướng
sẵn embedder E5. Build từ `develop` trần thì image lên xanh, container `healthy`,
nhưng `/healthz` báo `stt`/`tts`/`rag_index` = `down`, micro câm và mọi câu hỏi sổ
tay trả về "không tìm thấy". Đó là **ba lỗi build-xanh-rồi-hỏng-sau**.

Thứ cần deploy là `develop` **cộng** `Dockerfile` của PR #214
(`feat/issue-184-deploy-image`).

Cập nhật refs trước:

```powershell
git fetch origin
```

Kiểm nhánh PR #214 có bị bỏ lại sau `develop` không — **phải in ra `0`**:

```powershell
git rev-list --count origin/feat/issue-184-deploy-image..origin/develop
```

> Đo 2026-08-21: ra `0`, tức nhánh đó **đã có mọi thứ `develop` có**, cộng đúng 3
> file: `Dockerfile`, `.dockerignore`, `requirements-voice.txt`. (Cảnh báo "thiếu 37
> commit" trong `deploy_vps_fullstack.md` mục 7 là của ngày 2026-08-20 và **đã lỗi
> thời** — nhánh đã được cập nhật.)
>
> Ra số khác `0` nghĩa là `develop` đã đi tiếp — khi đó đừng deploy nhánh này, hãy
> gộp cục bộ theo khối dưới.

**Trường hợp thường (in ra `0`):** deploy thẳng nhánh đó. Tên nhánh dùng ở V9 là
`feat/issue-184-deploy-image`.

**Trường hợp in ra số > 0** (hoặc PR #214 đã merge vào `develop`) — kiểm `develop` đã
có `Dockerfile` đúng chưa; in ra một dòng là đã có:

```powershell
git show origin/develop:Dockerfile | Select-String requirements-voice
```

Có rồi → dùng nhánh `develop` ở V9. Chưa có → gộp cục bộ:

```powershell
git checkout -b deploy-20260821 origin/develop
```

```powershell
git merge origin/feat/issue-184-deploy-image
```

```powershell
git show HEAD:Dockerfile | Select-String requirements-voice
```

Nhánh cục bộ này **chưa có trên GitHub**, nên V9 phải đi **Đường 2** (`git archive`
+ `scp`), không `git clone` được.

## W4. Kiểm artifact có đủ không

- **Máy:** WINDOWS, tại thư mục gốc repo
- **Cần có trước:** không có gì
- **Đúng thì thấy:** đủ **6 file voice** và **5 file RAG**

Sáu file voice — thiếu **một** cái là `docker compose build` ở V13 chết:

```powershell
Get-ChildItem models\voice\vi_VN-piper.onnx, models\voice\vi_VN-piper.onnx.json, models\voice\zipformer-30m-rnnt-6000h\encoder.int8.onnx, models\voice\zipformer-30m-rnnt-6000h\decoder.int8.onnx, models\voice\zipformer-30m-rnnt-6000h\joiner.int8.onnx, models\voice\zipformer-30m-rnnt-6000h\tokens.txt | Select-Object Name, Length
```

Năm file chỉ mục RAG:

```powershell
Get-ChildItem data\rag\vf9_2026_vi | Select-Object Name, Length
```

Phải thấy `chunks.db`, `index.faiss`, `manifest.json`, `page_map.json`,
`vector_ids.json`.

## W5. Đối chiếu checksum

- **Máy:** WINDOWS
- **Cần có trước:** W4 xong
- **Đúng thì thấy:** hai chuỗi hash giống hệt nhau

```powershell
Get-FileHash -Algorithm SHA256 models\voice\zipformer-30m-rnnt-6000h\encoder.int8.onnx
```

```powershell
Get-Content models\voice\zipformer-30m-rnnt-6000h\encoder.int8.onnx.sha256
```

Không khớp → tải lại model, đừng gửi lên.

---

# PHẦN B — VPS: DỰNG NỀN

> Từ V1 tới hết V32 là **bash trên VPS**, trừ khi ghi rõ khác.

## V1. Đăng nhập lần đầu và cập nhật hệ

- **Máy:** WINDOWS → mở SSH vào VPS
- **Cần có trước:** W2 xong
- **Đúng thì thấy:** dấu nhắc `root@...`

```powershell
ssh root@<IP>
```

> Từ đây các khối là bash. Cập nhật hệ trước (1–3 phút):

```bash
apt update && apt upgrade -y
```

Đặt múi giờ cho log dễ đọc:

```bash
timedatectl set-timezone Asia/Ho_Chi_Minh
```

## V2. Tạo user `vivi` và chuyển khoá SSH sang

- **Máy:** VPS (đang là `root`)
- **Cần có trước:** V1
- **Đúng thì thấy:** SSH vào được bằng `vivi@<IP>` không cần mật khẩu

```bash
adduser --disabled-password --gecos "" vivi
```

```bash
usermod -aG sudo vivi
```

```bash
rsync --archive --chown=vivi:vivi ~/.ssh /home/vivi/
```

Cho `vivi` chạy `sudo` không cần mật khẩu. Tài khoản này **không có** mật khẩu
(`--disabled-password`), nên thiếu dòng này thì mọi lệnh `sudo` về sau sẽ treo ở ô
nhập mật khẩu không bao giờ đúng:

```bash
echo 'vivi ALL=(ALL) NOPASSWD:ALL' | tee /etc/sudoers.d/90-vivi && chmod 0440 /etc/sudoers.d/90-vivi
```

## V3. Tường lửa

- **Máy:** VPS (`root`)
- **Cần có trước:** V2
- **Đúng thì thấy:** `Status: active`, có 3 dòng `22`, `80`, `443`

```bash
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

```bash
ufw status
```

> **Cảnh báo quan trọng:** `ufw` **không** chặn được cổng do Docker publish — Docker
> ghi rule thẳng vào chain `DOCKER` của iptables, đứng **trước** rule của ufw. Đó là
> lý do V12 phải dùng file override để ép backend chỉ bind `127.0.0.1`. Đừng dựa vào
> ufw để giấu cổng 8000.

## V4. Kiểm máy thật sự là máy gì

- **Máy:** VPS (`root`)
- **Cần có trước:** V1
- **Đúng thì thấy:** biết số nhân **vật lý** và steal time

Khối này in thẳng kết luận. Cố ý viết **không dấu** — một số ảnh cloud tối giản chưa
đặt locale UTF-8, và output tiếng Việt sẽ ra ký tự hỏng đúng lúc đang cần đọc:

```bash
echo "== CPU =="; lscpu | grep -E "Model name|^CPU\(s\)|Thread\(s\) per core|Core\(s\) per socket|Socket\(s\)"; PHYS=$(( $(lscpu | awk -F: '/Core\(s\) per socket/{print $2}') * $(lscpu | awk -F: '/^Socket\(s\)/{print $2}') )); echo "-> nhan VAT LY = $PHYS"; echo "== steal time (5 giay) =="; vmstat 1 5 | awk 'NR==2{for(i=1;i<=NF;i++) if($i=="st") c=i} NR>2{print "st="$c}'; echo "== RAM / dia / swap =="; free -h; df -h /
```

Ghi lại **hai con số** để dùng về sau:

- `nhan VAT LY` → dùng cho `OMP_NUM_THREADS` (V10) và cờ `-t` của llama-server (V28).
- `st=` liên tục lớn hơn `0` → máy đang bị hàng xóm giành CPU. Đó là gói
  "shared/burst" — demo sẽ giật.

`nhan VAT LY` < 4 → **để `SLM_ENABLED=false`** và bỏ hẳn Phần H (V26–V31). Ở 2 nhân,
planner đo được p50 **8 561 ms**, vượt trần 8 000 ms → quá nửa số lời gọi hỏng.

## V5. Swap 4 GB — **làm trước, không phải khi đã hết RAM**

- **Máy:** VPS (`root`)
- **Cần có trước:** V4 cho thấy cột `Swap` = `0B`, và đĩa còn ≥ 6 GB
- **Đúng thì thấy:** `free -h` in ra `Swap: 4.0Gi`

Ảnh cloud thường không có swap. `next build` (V17) đỉnh **1 173 MB** — trên máy 4–5 GB
đó là chỗ chật nhất của cả quy trình. Không có swap thì nó bị OOM kill giữa chừng.

```bash
fallocate -l 4G /swapfile
```

```bash
chmod 600 /swapfile
```

```bash
mkswap /swapfile && swapon /swapfile
```

```bash
echo '/swapfile none swap sw 0 0' | tee -a /etc/fstab
```

```bash
echo 'vm.swappiness=10' | tee /etc/sysctl.d/99-vivi-swap.conf && sysctl -p /etc/sysctl.d/99-vivi-swap.conf
```

```bash
free -h
```

> Swap ở đây là **lưới chống OOM lúc build, không phải RAM cộng thêm.** Một lượt
> thoại lúc demo mà phải chạm swap là độ trễ hỏng hẳn. `vm.swappiness=10` để nhân hệ
> điều hành đừng đẩy tiến trình đang rảnh ra swap khi RAM còn trống.

## V6. Docker và xoay vòng log

- **Máy:** VPS (`root`)
- **Cần có trước:** V1 (mạng ra được Internet)
- **Đúng thì thấy:** `docker --version` in ra 27.x hoặc mới hơn

```bash
curl -fsSL https://get.docker.com | sh
```

```bash
usermod -aG docker vivi
```

**Đừng bỏ bước xoay vòng log.** Xe ảo phát heartbeat mỗi 5 giây và để
`restart: unless-stopped` → log phình cho tới lúc đầy đĩa:

```bash
tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "no-new-privileges": true
}
EOF
```

```bash
systemctl restart docker
```

```bash
docker --version && docker compose version
```

**Bây giờ thoát ra và SSH vào lại bằng `vivi`** — nhóm `docker` chỉ có hiệu lực ở
phiên đăng nhập mới:

```bash
exit
```

- **Máy:** WINDOWS

```powershell
ssh vivi@<IP>
```

Kiểm nhóm `docker` đã ăn (không được có chữ `permission denied`):

```bash
docker ps
```

> **Từ V7 trở đi mọi lệnh chạy dưới user `vivi`, không phải `root`.**

## V7. Node 22 cho frontend

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V6
- **Đúng thì thấy:** `v22.x.x` và `10.x.x`

Next 16.3.0 cần Node ≥ 20; Ubuntu 24.04 mặc định có Node 18 — **không đủ**.

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
```

```bash
sudo apt install -y nodejs
```

```bash
node -v && npm -v
```

---

# PHẦN C — ĐƯA MÃ NGUỒN VÀ ARTIFACT LÊN

## V8. Tạo thư mục đích

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V6
- **Đúng thì thấy:** không báo lỗi

```bash
sudo mkdir -p /opt/vivi && sudo chown vivi:vivi /opt/vivi
```

## V9. Lấy mã nguồn — chọn **một** trong hai đường

### Đường 1 — `git clone` (khi VPS vào được GitHub và bạn có PAT)

- **Máy:** VPS (`vivi`)
- **Cần có trước:** W3 chốt được **tên nhánh đã có trên GitHub**; repo `P-192` là
  **private** nên phải có token
- **Đúng thì thấy:** `/opt/vivi` có `src/`, `frontend/`, `Dockerfile`

Kiểm mạng và quyền trước — **đừng ngồi đợi nó chết**:

```bash
curl -sS -m 10 -o /dev/null -w '%{http_code}\n' https://github.com
```

```bash
GIT_TERMINAL_PROMPT=0 git ls-remote https://github.com/AI20K-Build-Phase-Cohort-3/P-192.git
```

`GIT_TERMINAL_PROMPT=0` là phần quan trọng: thiếu nó, lệnh **ngồi đợi bạn gõ mật
khẩu** thay vì trả lời câu hỏi.

| Lệnh 1 | Lệnh 2 | Làm gì |
|---|---|---|
| `200` | in ra SHA + tên nhánh | Clone được, chạy tiếp |
| `200` | `could not read Username` | Mạng OK, thiếu quyền → tạo PAT (dưới) **hoặc** đi Đường 2 |
| treo / `Could not resolve host` | — | Mạng chặn → **Đường 2** |

**Tạo PAT** (trên máy Windows, bằng trình duyệt): ảnh đại diện GitHub → *Settings* →
*Developer settings* → *Personal access tokens* → **Tokens (classic)** →
*Generate new token* → tick **đúng một ô `repo`** → hạn **7 days** → *Generate*.
Chuỗi `ghp_...` chỉ hiện **một lần**, chép ngay.

> **Dùng bản *classic*, không dùng *fine-grained*.** Repo thuộc org
> `AI20K-Build-Phase-Cohort-3`; token fine-grained mặc định chỉ thấy repo cá nhân,
> triệu chứng là "tìm mãi không thấy repo đâu".
>
> Bạn **không phải admin repo** nên *Settings → Deploy keys* sẽ không mở được —
> đừng mất thời gian ở đó.

Clone (thay `<nhánh>` bằng nhánh chốt ở W3):

```bash
git clone -b <nhánh> https://github.com/AI20K-Build-Phase-Cohort-3/P-192.git /opt/vivi
```

Nó hỏi `Username` → gõ `<user-gh>`; hỏi `Password` → **dán PAT** (terminal không
hiện ký tự nào, đó là bình thường).

> Token nằm **nguyên văn** trong `/opt/vivi/.git/config` trên một máy đi thuê. Đặt
> hạn 7 ngày, và **xoá token sau buổi demo**.

### Đường 2 — đóng gói bằng `git archive` rồi `scp` (khuyến nghị cho demo một lần)

- **Máy:** WINDOWS rồi VPS
- **Cần có trước:** W3 xong, và bạn đang **đứng đúng nhánh muốn deploy**
- **Đúng thì thấy:** `/opt/vivi` có `src/`, `frontend/`, `Dockerfile`

**Vì sao đường này đơn giản hơn:** bạn **đằng nào cũng phải** `scp` `models/` và
`data/rag/` ở W6. Đường 2 chỉ là thêm **đúng một lệnh `scp` nữa**, và không cần
token, không cần cấu hình xác thực nào trên máy đi thuê.

- **Máy:** WINDOWS, tại thư mục gốc repo

Kiểm đang đứng đúng nhánh — `git archive` đóng gói `HEAD`, không phải nhánh bạn nghĩ
trong đầu:

```powershell
git branch --show-current
```

Nếu đang ở nhánh khác thì chuyển sang nhánh chốt ở W3:

```powershell
git checkout feat/issue-184-deploy-image
```

Đóng gói (ra ~66 MB / 1 549 file):

```powershell
git archive --format=tar.gz -o ..\vivi-src.tar.gz HEAD
```

```powershell
scp ..\vivi-src.tar.gz vivi@<IP>:/tmp/
```

- **Máy:** VPS (`vivi`)

```bash
tar -xzf /tmp/vivi-src.tar.gz -C /opt/vivi
```

```bash
ls /opt/vivi
```

Phải thấy `src`, `frontend`, `Dockerfile`, `docker-compose.yml`, `.env.example`.

> **Hai cái mất khi bỏ `git clone`:** trên VPS không có `.git` nên `git pull` ở V32
> không dùng được (cập nhật = gửi lại tarball); và `git archive` **chỉ đóng file đã
> commit** — sửa dở chưa commit thì thay đổi đó không đi theo, triệu chứng là "sửa
> rồi mà VPS không đổi".
>
> Cần cả file chưa commit thì thay lệnh `git archive` bằng:
>
> ```powershell
> tar -czf ..\vivi-src.tar.gz --exclude=.git --exclude=node_modules --exclude=.next --exclude=.venv --exclude=data/manuals --exclude=__pycache__ .
> ```
>
> `--exclude=data/manuals` là dòng đáng giá nhất ở đây: **154 MB PDF nguồn** chỉ
> dùng lúc `ingest`, backend lúc chạy không đọc file nào trong đó.

## W6. `scp` artifact ngoài git — **không bỏ được, kể cả khi đã `git clone`**

- **Máy:** WINDOWS, tại thư mục gốc repo
- **Cần có trước:** V9 xong (thư mục `/opt/vivi` đã có mã nguồn); W4/W5 đã kiểm artifact
- **Đúng thì thấy:** V9b liệt kê đủ file

`models/` — 89 MB, khoảng 1–3 phút:

```powershell
scp -r models vivi@<IP>:/opt/vivi/
```

`data/rag/` — 2 MB:

```powershell
scp -r data\rag vivi@<IP>:/opt/vivi/data/
```

### V9b. Kiểm artifact đã lên đủ

- **Máy:** VPS (`vivi`)
- **Đúng thì thấy:** 6 file voice (kèm `.sha256`/`.metadata.json`) và 5 file trong
  `data/rag/vf9_2026_vi/`

```bash
find /opt/vivi/models/voice /opt/vivi/data/rag -type f | sort
```

```bash
ls -la /opt/vivi/data/rag/vf9_2026_vi/index.faiss
```

Không thấy `index.faiss` → quay lại `scp`. Build vẫn chạy được nhưng RAG sẽ chết câm
mà không báo gì.

---

# PHẦN D — BACKEND

## V10. File `.env`

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V9b; biết `<domain>`; biết số nhân vật lý (V4)
- **Đúng thì thấy:** `grep` ở cuối bước in ra đúng các dòng đã sửa

```bash
cd /opt/vivi && cp .env.example .env
```

```bash
nano /opt/vivi/.env
```

Sửa **năm** dòng sau (tìm dòng cũ và sửa tại chỗ, đừng thêm dòng trùng):

```
APP_ENV=production
MQTT_ENABLED=true
MQTT_URL=mqtt://mqtt:1883
CORS_ORIGINS=https://<domain>
OMP_NUM_THREADS=4
```

Lưu bằng `Ctrl+O` → `Enter` → `Ctrl+X`.

**Bốn cái bẫy trong năm dòng này:**

1. **`MQTT_URL` là `mqtt://mqtt:1883`, KHÔNG phải `localhost`.** Backend chạy trong
   container và nói chuyện với broker qua **tên service** trong mạng Docker. Để
   `localhost` thì backend tự gọi chính nó → `/healthz` báo `mqtt: down`, mọi lệnh
   điều khiển hỏng.
2. **`CORS_ORIGINS` phải khớp chính xác từng ký tự.** `src/api/ws.py:176` **không
   làm CORS** — nó tự đối chiếu header `Origin` của WebSocket với chính biến này.
   Không dấu `/` cuối, không kèm cổng, đúng scheme `https`. Sai một ký tự →
   **WebSocket đóng mã `4403` trong khi REST vẫn xanh**, trông y hệt "backend chết".
3. **`OMP_NUM_THREADS` là cái phanh, không phải tinh chỉnh.** Không đặt thì ONNX
   Runtime lấy hết số nhân thấy được, và một lượt TTS chiếm trọn máy trong nửa giây
   mà **không nhanh hơn** (cả bốn thành phần đều bão hoà ở 4 luồng). Đặt bằng **số
   nhân vật lý** đọc ở V4.
4. **Xoay `AI_LOG_API_KEY`.** Giá trị trong `.env.example` là key dùng chung của
   nhóm, và `.env` này sắp nằm trên một máy đi thuê.

Kiểm lại:

```bash
grep -E "^(APP_ENV|MQTT_ENABLED|MQTT_URL|CORS_ORIGINS|OMP_NUM_THREADS|DATABASE_URL|RAG_INDEX_DIR)=" /opt/vivi/.env
```

## V11. Sinh mật khẩu Mosquitto

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V6 (Docker chạy được), V9 (có thư mục `config/mosquitto/`)
- **Đúng thì thấy:** file `config/mosquitto/passwd` thuộc uid `1883`, mode `0640`

`scripts/bootstrap_mqtt_secrets.ps1` là PowerShell. Đây là bản bash tương đương, giữ
nguyên hai điều quan trọng: `-c` **chỉ dùng cho user đầu tiên**, và file phải thuộc
uid 1883.

```bash
cd /opt/vivi
```

```bash
BACKEND_PW=$(openssl rand -base64 24 | tr '+/=' 'xxx')
```

```bash
SIM_PW=$(openssl rand -base64 24 | tr '+/=' 'xxx')
```

```bash
docker run --rm -v /opt/vivi/config/mosquitto:/work eclipse-mosquitto:2 mosquitto_passwd -b -c /work/passwd vivi-backend "$BACKEND_PW"
```

```bash
docker run --rm -v /opt/vivi/config/mosquitto:/work eclipse-mosquitto:2 mosquitto_passwd -b /work/passwd vehicle-simulator "$SIM_PW"
```

```bash
docker run --rm -v /opt/vivi/config/mosquitto:/work eclipse-mosquitto:2 sh -c "chown 1883:1883 /work/passwd && chmod 0640 /work/passwd"
```

> Bước `chown` **không phải dọn dẹp, nó bắt buộc**: `mosquitto_passwd` tạo file mode
> 0600 thuộc `root`, trong khi broker chạy dưới user `mosquitto` (uid 1883) nên
> không đọc nổi — container sẽ **restart vô hạn** với "Unable to open pwfile".

In hai mật khẩu ra:

```bash
echo "MQTT_BACKEND_PASSWORD=$BACKEND_PW" && echo "MQTT_SIMULATOR_PASSWORD=$SIM_PW"
```

Chép hai dòng đó, rồi mở `.env` và sửa **bốn** dòng:

```bash
nano /opt/vivi/.env
```

```
MQTT_BACKEND_USERNAME=vivi-backend
MQTT_BACKEND_PASSWORD=<dán giá trị vừa in>
MQTT_SIMULATOR_USERNAME=vehicle-simulator
MQTT_SIMULATOR_PASSWORD=<dán giá trị vừa in>
```

> **Không commit `config/mosquitto/passwd`.**

## V12. Ép backend chỉ nghe loopback

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V9
- **Đúng thì thấy:** file `/opt/vivi/docker-compose.override.yml` tồn tại

`docker-compose.yml:101` publish `"8000:8000"` — **không có địa chỉ bind**, nghĩa là
cổng 8000 mở ra mọi interface. Trên VPS đó là **API công khai không HTTPS**, đi vòng
qua cả Caddy lẫn ufw. Đừng sửa file đã commit (có test khoá lại) — tạo file override,
Compose tự đọc:

```bash
cat > /opt/vivi/docker-compose.override.yml <<'EOF'
services:
  backend:
    ports: !override
      - "127.0.0.1:8000:8000"
EOF
```

```bash
cat /opt/vivi/docker-compose.override.yml
```

> **Thẻ `!override` là bắt buộc.** Compose **gộp** danh sách `ports` chứ không thay
> thế — viết `ports:` thường là được thêm một mapping nữa còn `"8000:8000"` vẫn còn
> nguyên và vẫn hỏng y hệt.

## V13. Build image backend

- **Máy:** VPS (`vivi`)
- **Cần có trước:** **W6 đã xong** (Dockerfile có chốt chặn 6 file voice, thiếu là
  fail); `.env` đã có (V10); mạng ra được PyPI và Hugging Face
- **Đúng thì thấy:** dòng cuối là `naming to docker.io/library/...`, không có `ERROR`

Kiểm hai mạng trước — build gọi ra cả hai, đừng ngồi đợi nó chết ở phút thứ mười:

```bash
curl -sS -m 10 -o /dev/null -w 'pypi=%{http_code}\n' https://pypi.org/simple/ && curl -sS -m 10 -o /dev/null -w 'hf=%{http_code}\n' https://huggingface.co
```

Cả hai phải ra `200` hoặc `301`. Một trong hai hỏng → xem `deploy_vps_fullstack.md`
mục 7.1 đường **B3** (build trên Windows, `docker save` + `scp` image 2,6 GB).

```bash
cd /opt/vivi && docker compose build
```

**Lần đầu tính bằng chục phút** (2 vCPU có thể 20–40 phút): tải torch CPU-only
(528 MB), sherpa-onnx, piper, rồi `snapshot_download` nạp sẵn embedder E5 (471 MB)
vào image. Image ra khoảng **2,6 GB**.

Build chết ở dòng `THIEU ARTIFACT VOICE: ...` → quay lại **W6**, `models/voice/`
chưa lên đủ.

## V14. Khởi động backend

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V11 (passwd), V12 (override), V13 (image)
- **Đúng thì thấy:** 3 container `running`, `/healthz` báo 5 thành phần `ready`

```bash
cd /opt/vivi && docker compose up -d --wait mqtt vehicle-simulator backend
```

> `--wait` quan trọng: cả `backend` lẫn `vehicle-simulator` đều gate trên healthcheck
> của `mqtt`. Lệnh này chỉ trả về khi cả ba thật sự lên.

```bash
docker compose ps
```

```bash
curl -s http://127.0.0.1:8000/healthz | python3 -m json.tool
```

Đọc `components` — đây là bảng chẩn đoán quan trọng nhất của cả quy trình:

| Thành phần | Phải là | `down` nghĩa là |
|---|---|---|
| `mqtt` | `ready` | Sai `MQTT_URL` (V10 bẫy 1), hoặc sai mật khẩu (V11) |
| `vehicle_simulator` | `ready` | Xe ảo chưa nối được broker |
| `stt`, `tts` | `ready` | **Image thiếu model** → build từ `Dockerfile` sai nhánh (W3) |
| `rag_index` | `ready` | **Thiếu `data/rag/` trên host** (W6) |
| `llm` | `disabled` | Đúng khi `.env` ghi rõ `SLM_ENABLED=false` — từ ADR-027 mặc định repo là `true`, bỏ trống sẽ ra `down` (cũng không phải lỗi, cũng không kéo 503) |

Container `mqtt` restart vô hạn → gần như chắc chắn quên `chown 1883` ở V11:

```bash
docker compose logs mqtt --tail 30
```

---

# PHẦN E — FRONTEND

## V15. Sáu biến `NEXT_PUBLIC_*` — **build-time**

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V9; biết `<domain>`
- **Đúng thì thấy:** file `.env.production` có đủ 6 dòng, không còn dấu `<`

Next.js **nướng** các biến này vào bundle JS lúc `npm run build`, **không đọc lúc
chạy**. Sửa xong là phải build lại; `systemctl restart` một mình không đổi được gì.

```bash
cat > /opt/vivi/frontend/.env.production <<'EOF'
NEXT_PUBLIC_API_URL=https://<domain>/api/v1
NEXT_PUBLIC_WS_IVI_URL=wss://<domain>/ws/ivi
NEXT_PUBLIC_WS_ENGINEER_URL=wss://<domain>/ws/engineer
NEXT_PUBLIC_USE_MOCK_TURN=false
NEXT_PUBLIC_USE_MOCK_SESSION=false
NEXT_PUBLIC_USE_MOCK_ENGINEER=false
EOF
```

**Rồi thay `<domain>` bằng tên miền thật** — heredoc `'EOF'` cố ý không thay biến,
nên ba dòng đầu hiện vẫn là chữ `<domain>` nguyên văn (sửa `vivi.id.vn` thành tên
miền của bạn):

```bash
sed -i 's|<domain>|vivi.id.vn|g' /opt/vivi/frontend/.env.production
```

```bash
cat /opt/vivi/frontend/.env.production
```

**Hai bẫy chết người ở bước này:**

- **Thiếu một trong ba cờ `USE_MOCK_*` là frontend chạy mock**, và nhìn **y hệt** như
  đang nối backend thật. `turn/index.ts:7` so sánh `!== "false"` — không khai cũng
  là mock, khai `"0"` cũng là mock. Ảnh chụp màn hình không chứng minh được gì nếu
  chưa tắt cả ba.
- **Giữ `NEXT_PUBLIC_API_URL` là URL tuyệt đối, đừng rút thành `/api/v1`.** Biến này
  được đọc ở **hai** nơi: trong trình duyệt (tương đối chạy tốt) **và trong Node**
  (`app/api/auth/demo-driver/route.ts:3` chạy server-side, `fetch("/api/v1/...")`
  ném `TypeError: Failed to parse URL`). Triệu chứng là **nút đăng nhập 1 chạm ở
  `/login` hỏng trong khi mọi thứ khác xanh**.

## V16. Hai biến demo — **runtime**

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V15
- **Đúng thì thấy:** file mode `600`

Hai biến này **cố ý không có** prefix `NEXT_PUBLIC_` để không bị bundle vào JS
client. Giá trị lấy từ `src/db.py:267` (`DEMO_USERS`):

```bash
cat > /opt/vivi/frontend/.env.runtime <<'EOF'
DEMO_DRIVER_EMAIL=driver.demo@example.com
DEMO_DRIVER_PASSWORD=DemoDriver123!
EOF
```

```bash
chmod 600 /opt/vivi/frontend/.env.runtime
```

```bash
ls -l /opt/vivi/frontend/.env.runtime
```

## V17. Cài và build frontend

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V7 (Node 22), V15 + V16 (hai file `.env`), V5 (swap),
  `registry.npmjs.org` vào được
- **Đúng thì thấy:** `Compiled successfully`, thư mục `.next/` xuất hiện

```bash
curl -sS -m 10 -o /dev/null -w 'npm=%{http_code}\n' https://registry.npmjs.org
```

```bash
cd /opt/vivi/frontend && npm ci
```

Mất 2–5 phút, ra `node_modules/` **633 MB**.

**Trên máy 4–5 GB: nhường chỗ trước khi build.** `next build` đỉnh **1 173 MB**; lúc
chạy chỉ trống 0,86–1,21 GB nếu có SLM. **Dừng MỘT dịch vụ là đủ, không cần cả hai:**

```bash
cd /opt/vivi && docker compose stop backend
```

```bash
cd /opt/vivi/frontend && npm run build
```

```bash
cd /opt/vivi && docker compose start backend
```

> Máy 8 GB thì bỏ qua hai lệnh `stop`/`start`.
>
> Đã dựng SLM (Phần H) thì dừng `sudo systemctl stop vivi-slm` gọn hơn — nó giải
> phóng 2 109 MB so với 1 208 MB của backend.

Build chết mà chỉ in `Killed` → đó là OOM. Kiểm swap có bật không (`free -h`) và
dừng thêm một dịch vụ nữa.

## V18. Chạy frontend bằng systemd

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V17 (`.next/` đã build)
- **Đúng thì thấy:** `curl` trả `200`

```bash
sudo tee /etc/systemd/system/vivi-frontend.service > /dev/null <<'EOF'
[Unit]
Description=VIVI frontend (Next.js)
After=network.target

[Service]
Type=simple
User=vivi
WorkingDirectory=/opt/vivi/frontend
EnvironmentFile=/opt/vivi/frontend/.env.runtime
Environment=NODE_ENV=production
ExecStart=/usr/bin/npm run start -- -H 127.0.0.1 -p 3000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now vivi-frontend
```

```bash
sudo systemctl status vivi-frontend --no-pager
```

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
```

Phải ra `200`. Chưa ra thì:

```bash
sudo journalctl -u vivi-frontend -n 50 --no-pager
```

---

# PHẦN F — HTTPS

## V19. Kiểm DNS đã lan chưa

- **Máy:** VPS (`vivi`)
- **Cần có trước:** đã tạo A record ở bước 0.2
- **Đúng thì thấy:** in ra đúng IP VPS

```bash
sudo apt install -y dnsutils
```

```bash
dig +short <domain>
```

**Chưa ra IP thì đừng cài Caddy vội** — Let's Encrypt sẽ từ chối, và bạn có thể chạm
hạn mức thất bại của tên miền đó. Đợi vài phút rồi kiểm lại.

## V20. Cài Caddy

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V19 ra đúng IP; cổng 80 và 443 đã mở (V3)
- **Đúng thì thấy:** `caddy version` in ra `v2.x`

Caddy tự xin và gia hạn chứng chỉ Let's Encrypt, và **proxy WebSocket không cần cấu
hình thêm** — đó là lý do chọn nó thay nginx.

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
```

```bash
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
```

```bash
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
```

```bash
sudo apt update && sudo apt install -y caddy
```

```bash
caddy version
```

## V21. Cấu hình Caddy

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V14 (backend nghe `127.0.0.1:8000`), V18 (Next nghe `127.0.0.1:3000`)
- **Đúng thì thấy:** `reload` không báo lỗi; sau 10–30 giây `https://<domain>` có ổ khoá

```bash
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
<domain> {
    handle /api/v1/* {
        reverse_proxy 127.0.0.1:8000
    }
    handle /ws/* {
        reverse_proxy 127.0.0.1:8000
    }
    handle /healthz {
        reverse_proxy 127.0.0.1:8000
    }
    handle {
        reverse_proxy 127.0.0.1:3000
    }
}
EOF
```

Thay `<domain>` bằng tên miền thật:

```bash
sudo sed -i 's|<domain>|vivi.id.vn|g' /etc/caddy/Caddyfile
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

```bash
sudo systemctl reload caddy
```

Theo dõi quá trình xin chứng chỉ (10–30 giây, `Ctrl+C` để thoát):

```bash
sudo journalctl -u caddy -f
```

**Ba điều phải hiểu trước khi sửa Caddyfile:**

1. **Đừng viết `handle /api/*`.** `/api/auth/demo-driver` là **route của Next.js**,
   không phải của backend — backend chỉ đăng ký prefix `/api/v1`. Gom cả `/api/*` về
   cổng 8000 là backend trả 404 cho nó → **nút đăng nhập 1 chạm chết trong khi mọi
   thứ khác xanh**. Đây là lỗi hay gặp nhất trong cả runbook.
2. **`/docs`, `/redoc`, `/openapi.json` của FastAPI sẽ rơi vào khối `handle` cuối**
   → Next.js trả 404. Đây là **kết quả mong muốn** — Swagger không nên mở công khai.
   Cần xem thì `curl` qua SSH tới `127.0.0.1:8000/docs`.
3. Khối `handle` loại trừ lẫn nhau và xét theo độ cụ thể, nên thứ tự viết không đổi
   kết quả.

Xin chứng chỉ thất bại → kiểm lại `dig +short <domain>` (V19) và cổng 80 (Let's
Encrypt cần nó để xác thực).

---

# PHẦN G — KIỂM CHỨNG (4 tầng, theo đúng thứ tự)

## V22. Tầng 1 — backend qua HTTPS

- **Máy:** VPS (`vivi`)
- **Đúng thì thấy:** JSON `/healthz` với 5 thành phần `ready`

```bash
curl -s https://<domain>/healthz | python3 -m json.tool
```

## V23. Tầng 2 — frontend qua HTTPS

- **Máy:** VPS (`vivi`)
- **Đúng thì thấy:** `HTTP/2 200`

```bash
curl -sI https://<domain>/ | head -1
```

Phải là `200` **từ Next**. Ra `404` → khối `handle` cuối trong Caddyfile sai.

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<domain>/api/v1/status
```

## V24. Tầng 3 — trình duyệt, **bốn** thứ phải kiểm

- **Máy:** trình duyệt trên máy Windows
- **Cần có trước:** V22, V23 xanh

**Trước tiên: xoá service worker lạ.** Một service worker do **dự án khác** từng
chạy trên `localhost:3000` đăng ký sẽ chặn mọi navigation — trang render nhưng React
không hydrate, click không ăn, không báo lỗi gì. Mở Console (F12) tại `<domain>` và
chạy:

```js
(await navigator.serviceWorker.getRegistrations()).forEach(r => r.unregister());
(await caches.keys()).forEach(k => caches.delete(k));
```

Rồi kiểm bốn thứ, không phải một:

| # | Việc | Hỏng thì là lỗi ở đâu |
|---|---|---|
| 1 | Vào `/login`, bấm nút **đăng nhập 1 chạm** | V15 (URL tuyệt đối) hoặc V16 (thiếu `.env.runtime`) |
| 2 | Vào `/driver`, gõ lệnh văn bản *"bật điều hoà"* | REST — xem V22 |
| 3 | Tab **Network → WS**: `/ws/ivi` phải **mở**, không đóng `4403` | `CORS_ORIGINS` ở V10 sai |
| 4 | **Bấm micro và nói một câu** | Chứng chỉ (V21) + STT/TTS (V14) |

Mục 4 là chặng duy nhất chứng minh **cả chuỗi** micro → STT → agent → TTS → loa thật
sự sống. Ba mục trên không thay được nó.

> **Cửa sổ trình duyệt phải đang ở tiền cảnh.** Tab bị ẩn/chạy nền có timer bị bóp và
> media loading bị hoãn — `Audio` sẽ nằm ở `readyState 0` mãi mãi, và không có số đo
> nào ở đó là thật.

## V25. Hâm nóng trước khi demo — đừng bỏ qua

- **Máy:** trình duyệt
- **Cần có trước:** V24 xanh

`src/main.py` warm sẵn embedder E5 lúc khởi động, **nhưng không warm STT và TTS**.
Lượt thoại **đầu tiên** sau khi container mới lên đo được `stt` **1 144 ms**, trong
khi run đã ấm chỉ **106 ms** — chênh **10 lần**.

**Trước buổi demo, tự bấm micro nói một câu.** Lượt đó gánh phần chậm, người xem
không phải chịu.

Đo lại RAM thật trên máy đích để thay số ước lượng:

```bash
docker stats --no-stream
```

```bash
systemctl status vivi-frontend --no-pager | grep Memory
```

---

# PHẦN H — (TUỲ CHỌN) BẬT SLM QWEN 3B

> **Chỉ làm phần này nếu bắt buộc phải có `slm_enabled=true`.** Đường mặc định
> (`false`) là hình dạng ADR-006/ADR-010 mô tả, và không cần gì ở đây.
>
> **Điều kiện chặn:** V4 phải cho thấy **≥ 4 nhân vật lý** và RAM ≥ 5 GB. Dưới mức
> đó thì planner p50 **8 561 ms > trần 8 000 ms** → quá nửa số lời gọi hỏng, người
> dùng đợi tới **16 giây** (hai lần timeout) để nhận đúng câu trả lời mà bản tắt cờ
> đưa ra trong ~100 ms.

## V26. Cài llama.cpp (build `b10358`)

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V4 ≥ 4 nhân vật lý
- **Đúng thì thấy:** `llama-server --version` in ra `b10358`

```bash
mkdir -p /opt/vivi/tools/llama && cd /opt/vivi/tools/llama
```

```bash
curl -fsSLO https://github.com/ggml-org/llama.cpp/releases/download/b10358/llama-b10358-bin-ubuntu-x64.tar.gz
```

```bash
tar -xzf llama-b10358-bin-ubuntu-x64.tar.gz && ls
```

```bash
./llama-server --version
```

> Asset không còn hoặc không chạy trên Ubuntu 24.04 thì build từ nguồn:
> `sudo apt install -y build-essential cmake libcurl4-openssl-dev`, `git clone`,
> `git checkout b10358`, `cmake -B build -DGGML_NATIVE=ON`, `cmake --build build -j`.
> **Ghi lại là đã build từ nguồn** — đó là khác biệt tăng phẩm cần có trong manifest.

## V27. Đưa model 3B lên

- **Máy:** WINDOWS rồi VPS
- **Cần có trước:** file ở `C:\vivi-models\qwen2.5-3b-instruct-q4_k_m.gguf` (2,0 GB);
  đĩa VPS còn ≥ 3 GB
- **Đúng thì thấy:** `sha256sum -c` in ra `OK`

- **Máy:** WINDOWS

```powershell
ssh vivi@<IP> "mkdir -p /opt/vivi/models/slm"
```

```powershell
scp C:\vivi-models\qwen2.5-3b-instruct-q4_k_m.gguf C:\vivi-models\qwen2.5-3b-instruct-q4_k_m.gguf.sha256 vivi@<IP>:/opt/vivi/models/slm/
```

2,0 GB — tính bằng chục phút. **Đừng làm sát giờ demo.**

- **Máy:** VPS (`vivi`)

```bash
cd /opt/vivi/models/slm && sha256sum -c qwen2.5-3b-instruct-q4_k_m.gguf.sha256
```

Phải in `OK`. Giá trị đúng là
`626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d`.

## V28. Chạy llama-server bằng systemd

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V26, V27
- **Đúng thì thấy:** `curl` trả `{"status":"ok"}`

**Sửa `-t 4` thành số nhân *vật lý*** đọc được ở V4 trước khi dán.

```bash
sudo tee /etc/systemd/system/vivi-slm.service > /dev/null <<'EOF'
[Unit]
Description=VIVI SLM (llama-server, Qwen2.5-3B-Instruct q4_k_m, CPU)
After=network.target

[Service]
Type=simple
User=vivi
WorkingDirectory=/opt/vivi/tools/llama
ExecStart=/opt/vivi/tools/llama/llama-server -m /opt/vivi/models/slm/qwen2.5-3b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8093 -c 2048 --cache-reuse 256 -ngl 0 -t 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now vivi-slm
```

```bash
curl -s http://127.0.0.1:8093/health
```

**Hai cờ không được đụng vào:**

- **`-c 2048` là con số ràng buộc RAM.** Toàn bộ số đo 1,9–2,1 GB đo ở đúng giá trị
  này; KV cache tỉ lệ thuận với ngữ cảnh. Nới `-c` là con số RAM trong runbook hết đúng.
- **`--host 127.0.0.1` là chốt chặn duy nhất.** Cổng 8093 **không có xác thực**.
  Đừng publish nó ra ngoài, và Caddyfile ở V21 cũng cố ý không định tuyến tới nó.

## V29. Bật cờ trong `.env`

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V28 trả `ok`

```bash
nano /opt/vivi/.env
```

Thêm **một** dòng (`SLM_MODEL_ID` giữ nguyên mặc định — `config.py:34` đã là
`qwen2.5-3b-instruct-q4_k_m`):

```
SLM_ENABLED=true
```

VPS chỉ có **2 nhân vật lý** thì thêm dòng nữa:

```
SLM_TIMEOUT_S=15.0
```

> Nhớ rằng **mỗi lượt hỏng tốn hai lần timeout** (`graph.py` thử lại đúng một lần),
> nên đặt trần quá cao là tự nhân đôi thời gian chờ của ca xấu nhất.

```bash
cd /opt/vivi && docker compose up -d --force-recreate backend
```

## V30. Kiểm chứng SLM

- **Máy:** VPS (`vivi`)
- **Đúng thì thấy:** `llm` = `ready`

```bash
curl -s https://<domain>/healthz | python3 -m json.tool
```

| Giá trị `llm` | Nghĩa |
|---|---|
| `ready` | Xong |
| `disabled` | Cờ chưa vào — backend chưa đọc `.env` mới, recreate lại |
| `down` | `slm_unreachable` — `vivi-slm` chưa chạy hoặc sai cổng |
| `degraded` | `slm_model_mismatch` — `SLM_MODEL_ID` không khớp model đang load |

Thử một câu **router không khớp luật nào** để ép đi qua planner (câu điều khiển
thông thường đi đường luật và **không** chạm SLM). Mở log ở một tab SSH:

```bash
sudo journalctl -u vivi-slm -f
```

Rồi mở `/driver` ở trình duyệt, nói một câu lạ, xem log có lượt `/completion` không.

## V31. Đo lại trên máy đích — bắt buộc trước khi trích số

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V30 xanh; có token engineer

Mọi con số trong `deploy_vps_fullstack.md` mục 18 đo trên **máy dev**, không phải VPS
này. Kỷ luật evidence của repo đòi mỗi số phải kèm tầng phần cứng:

```bash
curl -s https://<domain>/api/v1/metrics/summary -H "Authorization: Bearer <token-engineer>" | python3 -m json.tool
```

Đọc `stage_latency_ms.planning_or_retrieval` — chặng đó **gộp cả RAG lẫn SLM**, nên
phải so với số của bản tắt cờ mới thấy được phần SLM cộng thêm. **Ghi thành một run
mới, đừng sửa file trong `eval/results/`.**

---

# PHẦN I — VẬN HÀNH

## V32. Cập nhật, sao lưu, dọn dẹp

### Cập nhật mã nguồn

- **Máy:** VPS (`vivi`)
- **Cần có trước:** V9 đi **Đường 1** (`git clone`). Đi Đường 2 thì không có `.git`
  → cập nhật = đóng gói và `scp` lại tarball.

```bash
cd /opt/vivi && git pull
```

```bash
cd /opt/vivi && docker compose build && docker compose up -d --wait
```

```bash
cd /opt/vivi/frontend && npm ci && npm run build
```

```bash
sudo systemctl restart vivi-frontend
```

> `git pull` **không** kéo về `models/voice/` và `data/rag/` — chúng nằm ngoài git.
> Khi chúng đổi thì `scp` lại như W6.
>
> **Sửa bất kỳ biến `NEXT_PUBLIC_*` nào là bắt buộc `npm run build` lại.**
> `systemctl restart` một mình không đổi được gì.

### Sao lưu SQLite (trước mỗi lần đổi cấu hình)

```bash
cp /opt/vivi/data/app.db /opt/vivi/data/app.db.$(date +%F)
```

### Dọn cache build Docker

Thứ **duy nhất** trong hệ lớn dần theo thời gian. Trên máy dev cache đã lên 27,61 GB.

```bash
docker system df
```

```bash
docker builder prune -f
```

> Chỉ xoá cache build, **không** đụng image đang chạy. Lần build kế tiếp sẽ lâu hơn
> vì mất cache — **đừng chạy ngay trước ngày demo.**

### Xem log khi có sự cố

```bash
cd /opt/vivi && docker compose logs backend --tail 100
```

```bash
sudo journalctl -u vivi-frontend -n 100 --no-pager
```

```bash
sudo journalctl -u caddy -n 100 --no-pager
```

---

# BẢNG TRA LỖI — 9 chỗ dễ vấp

| # | Lỗi | Triệu chứng | Sửa ở bước |
|---|---|---|---|
| 1 | Build từ `develop` trần (Dockerfile boilerplate) | Build xanh, `healthy`, nhưng `stt`/`tts`/`rag_index` = `down`, micro câm | **W3** |
| 2 | Quên `scp models/voice/` | `docker compose build` chết ở `THIEU ARTIFACT VOICE` | **W6** |
| 3 | Quên `scp data/rag/` | Mọi câu sổ tay trả *"Tôi không tìm thấy thông tin này trong sổ tay xe."*, container vẫn xanh | **W6** |
| 4 | `MQTT_URL=mqtt://localhost:1883` | `/healthz` báo `mqtt: down`, lệnh điều khiển hỏng | **V10** |
| 5 | `CORS_ORIGINS` thiếu/sai một ký tự | **WS đóng `4403`, REST vẫn xanh** — giống hệt "backend chết" | **V10** |
| 6 | Quên `chown 1883:1883` trên `passwd` | Container `mqtt` restart vô hạn, "Unable to open pwfile" | **V11** |
| 7 | Quên `!override` ở file override | Cổng 8000 **vẫn mở ra Internet** dù tưởng đã đóng | **V12** |
| 8 | `handle /api/*` thay vì `/api/v1/*` | Nút đăng nhập 1 chạm chết, mọi thứ khác xanh | **V21** |
| 9 | Quên một cờ `USE_MOCK_*` | Giao diện chạy **mock**, trông y như thật | **V15** |

Thêm hai cái ít gặp nhưng khó đoán: rút `NEXT_PUBLIC_API_URL` thành đường dẫn tương
đối (Route Handler ném `Failed to parse URL`), và `next build` khi cả backend lẫn
`vivi-slm` đang chạy trên máy 5 GB (OOM giữa chừng, chỉ in `Killed`).

---

# GIỚI HẠN — deploy xong ≠ mở cho công chúng

Ghi ra để không ai đọc nhầm. **Cả sáu đều là việc code, không phải việc deploy:**

- **Một chiếc xe ảo dùng chung.** `vehicle_id` là hằng số — mọi người điều khiển
  cùng một chiếc xe.
- **Hai tài khoản demo hard-code** (`src/db.py:267`). Ai đọc source cũng đăng nhập
  được, và `/engineer` lộ trace của mọi lượt.
- **Khoá `threading.Lock` toàn cục trên STT/TTS** (`voice.py:97`, `:192`). Mỗi lúc
  **một người** nói được. Máy to hơn không gỡ được — khoá nằm trong tiến trình.
- **Không có rate limit** ở bất kỳ tầng nào.
- **Không mở rộng ngang được.** SQLite một kết nối; `InMemorySaver` mất lượt đang
  chờ duyệt khi restart.
- **License CC-BY-NC-ND của model STT.** Image có nướng model vào → **đừng push lên
  registry công khai**. Build tại chỗ trên VPS như V13 là đúng.

---

# PHẦN J — KIỂM CHỨNG KHI **CHƯA CÓ TÊN MIỀN**

Câu hỏi thật: *"deploy tới đâu rồi, và phần đã deploy có chạy không?"* — trả lời được
mà không cần tên miền, cho **31 trong 32 bước**.

## J.1. Cái gì cần tên miền, cái gì không

| Bước | Cần tên miền? | Kiểm bằng gì khi chưa có |
|---|---|---|
| W1–W6, V1–V14 (backend) | **Không** | `curl http://127.0.0.1:8000/healthz` qua SSH — J.2 |
| Lượt hội thoại đầy đủ (agent, MQTT, RAG, HITL) | **Không** | 3 lệnh `curl` — J.3 |
| V15–V18 (frontend) | **Không** | `curl http://127.0.0.1:3000/` = 200 |
| Giao diện thật + **micro** trong trình duyệt | **Không** | SSH tunnel — J.4 |
| V26–V31 (SLM) | **Không** | `llama-server` vốn chỉ nghe loopback |
| **V19–V21 (Caddy + Let's Encrypt)** | **Có** | Không kiểm được. Đây là **thứ duy nhất** |
| Người khác mở link được | **Có** | — |

Nói cách khác: tên miền chỉ mua **một** thứ — HTTPS công khai. Toàn bộ phần còn lại
của hệ chạy trên loopback và kiểm được ngay hôm nay.

## J.2. `/healthz` — bằng chứng mạnh nhất, một lệnh

- **Máy:** VPS (`vivi`), sau V14

```bash
curl -s http://127.0.0.1:8000/healthz | python3 -m json.tool
```

Sáu thành phần trong `components` là **sáu bước deploy khác nhau tự báo cáo**:

| Thành phần | `ready` chứng minh |
|---|---|
| `mqtt` | V11 (mật khẩu) + V10 (`MQTT_URL=mqtt://mqtt:1883`) đúng |
| `vehicle_simulator` | Xe ảo nối được broker, heartbeat đang chạy |
| `stt` | `models/voice/zipformer-*` đã vào image (W6 + W3) |
| `tts` | `models/voice/vi_VN-piper.onnx` đã vào image |
| `rag_index` | `data/rag/` có trên host và đọc được (W6) |
| `llm` = `disabled` | Đúng khi `.env` ghi rõ `SLM_ENABLED=false` (bắt buộc từ ADR-027); `down` nếu bỏ trống; `ready` sau V29 |

Đây là chỗ **duy nhất** phân biệt được "container xanh" với "hệ chạy được" — cả sáu
lỗi trong bảng tra lỗi đều lộ ra ở đây trừ lỗi số 8 và 9.

## J.3. Chạy một lượt hội thoại đầy đủ bằng `curl` — không cần frontend

- **Máy:** VPS (`vivi`)
- **Cần có trước:** J.2 cho thấy `mqtt`, `vehicle_simulator`, `rag_index` = `ready`
- **Đúng thì thấy:** JSON có `action_plan` (lượt điều khiển) hoặc `citations` (lượt sổ tay)

Chứng minh **cả LangGraph, router, policy, tool registry, MQTT và RAG** mà không cần
trình duyệt, không cần tên miền, không cần frontend build xong.

Lấy token (mật khẩu từ `src/db.py:267`):

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login -H "Content-Type: application/json" -H "X-Schema-Version: 1.0" -d '{"email":"driver.demo@example.com","password":"DemoDriver123!"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])")
```

```bash
echo "${TOKEN:0:16}..."
```

In ra rỗng → login hỏng, xem `docker compose logs backend --tail 30`.

Mở phiên (`vehicle_id` lấy đúng giá trị `VEHICLE_ID` trong `.env`):

```bash
SID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/sessions -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H "X-Schema-Version: 1.0" -H "Idempotency-Key: smoke-$(date +%s)" -d '{"vehicle_id":"vehicle-demo-01","input_mode":"text"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['session_id'])")
```

```bash
echo "$SID"
```

**Lượt điều khiển** — chứng minh router + policy + MQTT + xe ảo:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/turns/text -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H "X-Schema-Version: 1.0" -H "Idempotency-Key: turn-$(date +%s)" -d "{\"session_id\":\"$SID\",\"text\":\"bật điều hoà\"}" | python3 -m json.tool
```

**Lượt tra sổ tay** — chứng minh FAISS + embedder E5 + composer:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/turns/text -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H "X-Schema-Version: 1.0" -H "Idempotency-Key: turn-$(date +%s)-rag" -d "{\"session_id\":\"$SID\",\"text\":\"áp suất lốp tiêu chuẩn là bao nhiêu\"}" | python3 -m json.tool
```

Trả về *"Tôi không tìm thấy thông tin này trong sổ tay xe."* → **`data/rag/` chưa lên
đúng** (W6), dù `/healthz` có thể vẫn xanh nếu thư mục tồn tại mà rỗng.

**Trạng thái xe** — chứng minh vòng MQTT khép kín:

```bash
curl -s http://127.0.0.1:8000/api/v1/vehicle/state -H "Authorization: Bearer $TOKEN" -H "X-Schema-Version: 1.0" | python3 -m json.tool
```

Ba header đó **bắt buộc cả ba**: thiếu `X-Schema-Version: 1.0` hay `Idempotency-Key`
là `400 REQUEST_CONTEXT_INVALID`, không phải lỗi deploy.

## J.4. Mở giao diện thật trên máy Windows — **kể cả micro** — bằng SSH tunnel

Đây là phần bất ngờ nhất: **`http://localhost` là secure context** theo chuẩn W3C, y
như HTTPS. Nên `getUserMedia` chạy bình thường qua tunnel — **micro kiểm được trước
khi có tên miền**.

### Bước 1 — build frontend trỏ về localhost

- **Máy:** VPS (`vivi`), thay cho V15 trong giai đoạn này

```bash
cat > /opt/vivi/frontend/.env.production <<'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_IVI_URL=ws://localhost:8000/ws/ivi
NEXT_PUBLIC_WS_ENGINEER_URL=ws://localhost:8000/ws/engineer
NEXT_PUBLIC_USE_MOCK_TURN=false
NEXT_PUBLIC_USE_MOCK_SESSION=false
NEXT_PUBLIC_USE_MOCK_ENGINEER=false
EOF
```

> Ba cờ `USE_MOCK_*` **vẫn phải khai** dù hai URL trên trùng giá trị mặc định trong
> code — không khai là frontend chạy mock và nhìn y hệt như thật.

### Bước 2 — cho backend chấp nhận Origin đó

- **Máy:** VPS (`vivi`)

`CORS_ORIGINS` nhận danh sách phân tách bằng dấu phẩy (`main.py:160` và
`ws.py:176` cùng `split(",")`), nên khai **cả hai** ngay từ bây giờ là hết phải sửa
lại sau:

```bash
nano /opt/vivi/.env
```

```
CORS_ORIGINS=http://localhost:3000,https://<domain>
```

```bash
cd /opt/vivi && docker compose up -d --force-recreate backend
```

### Bước 3 — build lại và mở tunnel

- **Máy:** VPS (`vivi`)

```bash
cd /opt/vivi/frontend && npm run build && sudo systemctl restart vivi-frontend
```

- **Máy:** WINDOWS — mở **một cửa sổ PowerShell mới** và để nguyên đó:

```powershell
ssh -L 3000:127.0.0.1:3000 -L 8000:127.0.0.1:8000 vivi@<IP>
```

Rồi mở trình duyệt tại **`http://localhost:3000`** và chạy đủ 4 phép thử của V24 —
đăng nhập 1 chạm, lệnh văn bản, WS `/ws/ivi` mở, **bấm micro và nói**.

Cửa sổ SSH đó là cái tunnel; đóng nó là mất kết nối.

### Bước 4 — khi tên miền về, **bắt buộc build lại**

`NEXT_PUBLIC_*` là **build-time**. Đổi file rồi `systemctl restart` là **không có gì
thay đổi** — bundle JS vẫn trỏ `localhost:8000`, và trên máy người xem thì
`localhost:8000` không có gì cả.

```bash
sed -i 's|http://localhost:8000/api/v1|https://<domain>/api/v1|; s|ws://localhost:8000|wss://<domain>|g' /opt/vivi/frontend/.env.production
```

```bash
cat /opt/vivi/frontend/.env.production
```

```bash
cd /opt/vivi/frontend && npm run build && sudo systemctl restart vivi-frontend
```

## J.5. Bảng "đã xong tới đâu" — tự chấm

Chạy lần lượt, dừng ở dòng đầu tiên sai:

| # | Lệnh | Xong nghĩa là |
|---|---|---|
| 1 | `docker compose ps` | V14 — 3 container `running` |
| 2 | `curl -s http://127.0.0.1:8000/healthz \| python3 -m json.tool` | V10–V14 — 5 thành phần `ready` |
| 3 | Ba lệnh `curl` ở J.3 | Cả pipeline agent + MQTT + RAG |
| 4 | `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/` | V17–V18 — frontend `200` |
| 5 | Tunnel J.4 + 4 phép thử V24 | Giao diện, WS, **micro** |
| 6 | `curl -s http://127.0.0.1:8093/health` | V26–V28 — SLM (nếu bật) |
| 7 | `curl -sI https://<domain>/ \| head -1` | **Chỉ bước này cần tên miền** |

Sáu dòng đầu xanh mà chưa có tên miền = **hệ đã chạy đủ**, chỉ còn thiếu đúng lớp
HTTPS công khai. Đó không phải trạng thái "chưa deploy được gì".
