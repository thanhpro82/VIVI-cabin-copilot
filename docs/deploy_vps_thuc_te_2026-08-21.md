# Nhật ký deploy VIVI lên VPS thật — máy LANIT, 2026-08-21

## Trạng thái: **đang chạy dở.** Đã xong V1–V9 + artifact; còn `.env` trở đi

**Mốc đã xác nhận trên máy thật (2026-08-21 → 22):** backend chạy đầy đủ —
`/healthz` báo 7 thành phần `ready` và `llm: disabled`; `llama-bench` đo được
**7,17 tok/s** ở `-t 4` (mục 8.3b). Còn frontend (V15–V18).

**Chi tiết:** hệ đã cập nhật và reboot sang kernel
`6.8.0-138`; user `vivi` vào được bằng khoá; `ufw` bật; Docker + Node 22 cài xong;
`git clone -b develop` về `11ef08f`; `grep -c requirements-voice Dockerfile` = **3**;
`data/rag/vf9_2026_vi/index.faiss` (823 KB) và `/tmp/vps` (9 file) đã có mặt.

File này **khác** `deploy_ubuntu24_tung_buoc.md` ở chỗ: file kia là runbook tổng
quát cho mọi máy Ubuntu 24.04; file này là **máy cụ thể** — số đo thật của nó, các
bước đã đổi vì nó, và ba lỗi đã vấp cùng cách chữa.

| File | Vai trò |
|---|---|
| `docs/deploy_ubuntu24_tung_buoc.md` | Runbook tổng quát 32 bước + Phần J (kiểm khi chưa có tên miền) |
| **file này** | **Máy 103.146.23.41 — đo được gì, làm tới đâu, còn gì** |
| `docs/chon_goi_vps.md` | Vì sao chọn cấu hình này |
| `docs/deploy_vps_fullstack.md` | Nguồn của mọi con số đo |

---

# 1. Máy này là gì — đo 2026-08-21

| Hạng mục | Giá trị đo được | Đánh giá |
|---|---|---|
| Nhà cung cấp | LANIT (`cloud2026082116.lanit.com.vn`) | |
| IP | **103.146.23.41**, cổng 22 | |
| OS | Ubuntu 24.04, kernel **6.8.0-138-generic** (sau `apt upgrade` + reboot) | ✅ đúng bản runbook viết cho |
| Ảo hoá | **`kvm`** (`BIOS Model name: RHEL 7.6.0 PC (i440FX + PIIX)` → QEMU) | ✅ Docker chạy bình thường |
| CPU | **`Intel Xeon E5-2696 v4 @ 2.20GHz`**, 4 vCPU | ⚠️ **xem mục 2** |
| `Thread(s) per core` | 1 | ⚠️ hypervisor tự khai, **không chứng minh 4 nhân vật lý** |
| `Core(s) per socket` × `Socket(s)` | 4 × 1 = **4** | ⚠️ như trên |
| Steal time lúc rảnh | **0–1%** | ⚠️ có hàng xóm, nhưng nhẹ. Kiểm lại lúc demo thử |
| **GPU** | **không có** — `lspci` ra `Cirrus Logic GD 5446` | ✅ đúng dự tính. Xem 1.1 |
| RAM | **4,8 GiB** total, **4,3 GiB** available | ✅ đúng bậc "5 GB" |
| **Swap** | **4,0 GiB — CÓ SẴN** | ✅ **bỏ hẳn bước V5** |
| Đĩa | **75 GB**, trống **69 GB** | ✅ cả hệ chỉ cần 17–19 GB |

## 1.1. Không có GPU — và đó là kết luận, không phải thiếu sót

```bash
lspci | grep -Ei 'vga|3d|display'
```

```
00:02.0 VGA compatible controller: Cirrus Logic GD 5446
```

`Cirrus Logic GD 5446` là **VGA giả lập mặc định của QEMU** — chip 2D đời 199x, tồn
tại để in màn hình console. **Không có năng lực tính toán nào**: không CUDA, không
Vulkan compute, không OpenCL. Cờ `-ngl 99` trên máy này là vô nghĩa.

Nên đường GPU (`deploy_vps_fullstack.md` mục 2.1, cột "GPU VPS") **đóng lại với máy
này**. Đó cũng là điều đã chốt từ đầu ở `chon_goi_vps.md` mục 1.4: GPU chỉ chạm
`llama-server`, còn STT/TTS/RAG bị đóng đinh vào CPU ngay trong `Dockerfile`.

### `lscpu` đầy đủ, và vì sao vẫn phải chạy bench

```
CPU(s):                4        Thread(s) per core:  1
Core(s) per socket:    4        Socket(s):           1
Model name:            Intel(R) Xeon(R) CPU E5-2696 v4 @ 2.20GHz
NUMA node0 CPU(s):     0-3
```

Hypervisor khai **4 nhân, 1 luồng mỗi nhân**, và lần này **nó nói đúng** —
`llama-bench` xác nhận độc lập bằng tỉ lệ `7,17 / 4,40 = 1,63×` (mục 8.3b).

Nhưng đừng rút ra bài học sai: đây là **kiểm chứng sau**, không phải lý do tin
`lscpu`. Trên máy ảo, hypervisor hoàn toàn có thể khai 4 nhân trong khi thực tế là
2 nhân + SMT — `lscpu` không có cách nào biết. **Bench vẫn là phép đo quyết định.**

## Ngân sách RAM trên đúng máy này

| | Cần | Còn trống trên 4,8 GiB |
|---|---:|---:|
| SLM **tắt** | ~1,74 GiB | **~3,1 GiB** — rất thoải mái |
| SLM **bật** (Qwen 3B) | **3,79 GiB** | **~1,0 GB** — chạy được, nhưng phải nhường chỗ lúc build |
| `next build` (đỉnh) | +1 173 MB | Với SLM bật thì **thiếu** → phải dừng một dịch vụ |

---

# 2. Cảnh báo lớn nhất của máy này: CPU là Xeon E5-2696 v4

`deploy_vps_fullstack.md` mục 1.1 nêu **đích danh** con CPU này trong một tiểu mục
riêng. Broadwell-EP, ra **2016**, base 2,2 GHz, host là máy 22 nhân / 44 luồng.

Hai hệ quả:

1. **Single-thread yếu** — *ước lượng* chậm hơn nhân đã đo (i7-14650HX, 2024) khoảng
   **2–3 lần**. Đây là suy luận từ đời nhân, **không phải số đo**.
2. **"4 vCPU" trên host 22 nhân / 44 luồng gần như chắc chắn là 4 *luồng* ≈ 2 nhân
   vật lý.** Nhà cung cấp bán luồng, không bán nhân. `lscpu` khai
   `Thread(s) per core: 1` là **cách hypervisor trình bày**, không phải sự thật vật lý.

Số đo liên quan (trên nhân **2024**, trần `SLM_TIMEOUT_S = 8 000 ms`):

| | Planner p50 | Planner max | Quá trần |
|---|---:|---:|---:|
| `-t 4` | 5 329 ms | 6 540 ms | 0 / 12 |
| **`-t 2`** | **7 326 ms** | 11 851 ms | **2 / 12** |
| `-t 2` (lần đo khác) | **8 561 ms** | 10 943 ms | quá nửa |

**Một điểm giảm nhẹ, ghi cho công bằng:** giải mã llama.cpp bị chặn ở **băng thông bộ
nhớ** chứ không ở IPC, nên khoảng cách giữa hai đời CPU **không** nhân lên tuyến tính
— RK3588 (ARM, 4× A76 @ 2,4 GHz) cũng cho 12–18 tok/s, cùng khoảng với i7 `-t 4`
(14,0). E5 v4 có 4 kênh DDR4 ở mức host. Nên "không tệ hơn nhiều lần" là có cơ sở;
"lọt dưới 8 giây" thì không ai hứa được.

## Quyết định: dựng với SLM **TẮT** trước, đo `llama-bench` sau

Đừng để câu hỏi SLM chặn cả buổi. Bản không SLM là hệ chạy được đầy đủ — định tuyến
100% bằng luật theo ADR-006/ADR-010. SLM là phần **cộng thêm**.

Nếu đo ra tệ, cái mất **chỉ là câu dẫn tự nhiên** trước câu trả lời sổ tay. Không mất
chức năng nào.

Thủ tục đo ở **mục 6** của file này.

> **Đính chính 2026-08-22 — điểm 2 ở trên đã SAI.** `llama-bench` cho `-t 2` = 4,40 và
> `-t 4` = 7,17 tok/s, tỉ lệ **1,63×**. Đó là tỉ lệ của **bốn nhân riêng**, không phải
> 2 nhân + SMT (SMT chỉ cho ~1,1–1,25×). Nghi ngờ "4 vCPU = 2 nhân vật lý" không đúng
> với máy này. Điểm 1 (single-thread yếu) thì đúng, nhưng biên độ nhỏ hơn ước lượng:
> chậm hơn máy dev **1,95×** ở mức đo tổng hợp, chứ không phải 2–3× — và ngay cả con
> số 1,95× cũng là ước lượng, xem cảnh báo cuối mục 8.3d.
>
> Xem **mục 8.3b** (số đo), **8.3c** (lỗi lượt nguội), **8.3d** (có nên đổi sang chip
> Xeon Platinum 8163 không).

---

# 3. Ba lỗi đã vấp — ghi lại để không lặp

## 3.1. Dán lệnh dài bị ngắt dòng

**Triệu chứng:** `-bash: syntax error near unexpected token 'newline'`

**Nguyên nhân:** khối lệnh một dòng quá dài, terminal tự xuống dòng lúc dán và shell
đọc thành nhiều lệnh rời. Lần đầu còn dính thêm chuỗi `</parameter>` chép nhầm.

**Cách tránh:** chia thành nhiều lệnh ngắn, mỗi lệnh một dòng. Việc gì cần dán chuỗi
dài (như khoá SSH) thì dùng `nano` chứ đừng nhét vào lệnh.

## 3.2. `authorized_keys` của `vivi` rỗng

**Triệu chứng:** `cat /home/vivi/.ssh/authorized_keys` không in gì; `ssh vivi@...`
vẫn hỏi mật khẩu.

**Nguyên nhân:** đăng nhập `root` bằng **mật khẩu** nên `root` chưa bao giờ có
`~/.ssh/authorized_keys`. Bước `rsync --archive --chown=vivi:vivi ~/.ssh /home/vivi/`
của V2 chép sang một thư mục rỗng — **nó không tự sinh khoá**.

**Cách chữa (đã dùng):** in khoá công khai trên Windows, chép, dán vào `nano` trên VPS.

## 3.3. `chown -R 700` thay vì `chown -R vivi:vivi` ← **lỗi mất nhiều thời gian nhất**

**Triệu chứng:** khoá đã đúng nội dung, quyền đã `600`/`700`, mà `ssh vivi@...` vẫn
hỏi mật khẩu, **không báo lý do gì**.

**Nguyên nhân:** `700` là tham số của **`chmod`**, không phải `chown`. `chown` đọc
`700` thành **UID 700** — một user không tồn tại. `authorized_keys` thành ra không
thuộc `vivi`, và **SSH từ chối im lặng** mọi khoá nằm trong file không thuộc chính
user đó (hoặc `root`).

**Cách chữa:**

```bash
chown -R vivi:vivi /home/vivi/.ssh
```

**Cách chẩn đoán khi gặp lại** — SSH luôn ghi lý do thật vào đây:

```bash
sudo tail -20 /var/log/auth.log
```

---

# 4. Đã làm xong — V1 tới V7

> Mọi lệnh dưới đây chạy trên **cửa sổ SSH tới VPS**, không phải PowerShell, trừ chỗ
> ghi rõ.

## V1 — cập nhật hệ (là `root`)

```bash
apt update && apt upgrade -y
```

```bash
timedatectl set-timezone Asia/Ho_Chi_Minh
```

Lần chạy này nâng cấp cả **kernel** (`6.8.0-31` → `6.8.0-138`) và **openssh-server**.
Hai hệ quả:

- Phải **reboot** để nạp kernel mới:

  ```bash
  reboot
  ```

- `openssh-server` sinh lại **host key**, nên lần `ssh` sau máy Windows báo đỏ
  `REMOTE HOST IDENTIFICATION HAS CHANGED`. Đó **không phải bị tấn công**. Chữa trên
  **PowerShell**:

  ```powershell
  ssh-keygen -R 103.146.23.41
  ```

  Rồi `ssh` lại, gõ `yes` để nhận vân tay mới.

Kiểm kernel sau reboot — phải in `6.8.0-138-generic`:

```bash
uname -r
```

## V2 — tạo user `vivi`

```bash
adduser --disabled-password --gecos "" vivi
```

```bash
usermod -aG sudo vivi
```

```bash
echo 'vivi ALL=(ALL) NOPASSWD:ALL' | tee /etc/sudoers.d/90-vivi && chmod 0440 /etc/sudoers.d/90-vivi
```

> Dòng `sudoers` bắt buộc: `vivi` tạo bằng `--disabled-password` nên **không có mật
> khẩu**, thiếu dòng này thì mọi lệnh `sudo` treo ở ô nhập mật khẩu không bao giờ đúng.

### V2b — đưa khoá SSH sang `vivi` (bước runbook viết chưa đủ, xem 3.2)

**Trên PowerShell (máy Windows), cửa sổ riêng.** Kiểm khoá:

```powershell
Get-ChildItem $env:USERPROFILE\.ssh\id_ed25519.pub
```

Chưa có thì tạo, Enter 3 lần:

```powershell
ssh-keygen -t ed25519 -C "vivi-deploy"
```

In ra rồi bôi đen chép cả dòng:

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

**Quay lại cửa sổ VPS:**

```bash
mkdir -p /home/vivi/.ssh ~/.ssh
```

```bash
nano /home/vivi/.ssh/authorized_keys
```

Chuột phải để dán, rồi `Ctrl+O` → `Enter` → `Ctrl+X`. Kiểm phải in ra `1`:

```bash
wc -l < /home/vivi/.ssh/authorized_keys
```

```bash
cp /home/vivi/.ssh/authorized_keys ~/.ssh/authorized_keys
```

```bash
chown -R vivi:vivi /home/vivi/.ssh
```

```bash
chmod 700 /home/vivi/.ssh ~/.ssh
```

```bash
chmod 600 /home/vivi/.ssh/authorized_keys ~/.ssh/authorized_keys
```

Kiểm trên **PowerShell** — phải in `vivi`, không hỏi mật khẩu:

```powershell
ssh vivi@103.146.23.41 "whoami"
```

```powershell
ssh vivi@103.146.23.41 "sudo -n true && echo SUDO_OK"
```

## V3 — tường lửa

```bash
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

```bash
ufw status
```

## V5 — **BỎ QUA**

Máy này đã có sẵn **swap 4,0 GiB**. Không phải tạo.

## V6 — Docker

```bash
curl -fsSL https://get.docker.com | sh
```

```bash
usermod -aG docker vivi
```

```bash
echo '{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"3"},"no-new-privileges":true}' > /etc/docker/daemon.json
```

Kiem JSON hop le truoc khi restart — sai cu phap thi **Docker khong khoi dong noi**,
va loi nam tan trong `journalctl` chu khong hien ra luc `systemctl restart`:

```bash
python3 -c "import json;print(json.load(open('/etc/docker/daemon.json')))"
```

```bash
systemctl restart docker
```

```bash
docker --version && docker compose version
```

**Rồi đăng xuất và vào lại bằng `vivi`** — nhóm `docker` chỉ có hiệu lực ở phiên mới:

```bash
exit
```

```powershell
ssh vivi@103.146.23.41
```

```bash
docker ps
```

Không báo `permission denied` là xong. **Từ đây mọi lệnh chạy dưới `vivi`.**

## V7 — Node 22

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

# 5. Còn phải làm — V8 trở đi

## V8 — thư mục đích

```bash
sudo mkdir -p /opt/vivi && sudo chown vivi:vivi /opt/vivi
```

## V9 — mã nguồn bằng `git clone` (đường chính)

### V9.0. Chọn nhánh nào — thủ tục, không phải ghi nhớ

Câu hỏi đúng **không** phải "nhánh nào mới nhất" mà là hai câu này, và cả hai đều
kiểm được bằng lệnh.

**(a) Nhánh đó có `Dockerfile` đúng không?** Nhánh `develop` đang dùng `Dockerfile`
boilerplate của môn học — nó chỉ cài `requirements.txt`, **không** cài RAG và voice,
**không** nướng sẵn embedder E5. Build từ đó ra image lên xanh, container `healthy`,
nhưng `/healthz` báo `stt`/`tts`/`rag_index` = `down`, micro câm và mọi câu hỏi sổ
tay trả về "không tìm thấy".

Trên **PowerShell**, tại thư mục gốc repo — **in ra một dòng là đạt**:

```powershell
git show origin/NHANH:Dockerfile | Select-String requirements-voice
```

**(b) Nhánh đó có bị bỏ lại sau `develop` không?** — **phải in ra `0`**:

```powershell
git rev-list --count origin/NHANH..origin/develop
```

`0` = nhánh đã có mọi thứ `develop` có. Số lớn = nó cũ, deploy nó là demo một bản
frontend cũ hàng chục commit.

**Nhánh nào thoả cả (a) và (b) thì deploy nhánh đó.** Thứ tự thử:

1. **`develop` — đáp án tính tới 2026-08-21 21:30.** Đo được: `Dockerfile` có
   `requirements-voice` (3 lần), `origin/develop` ở `11ef08f`, và
   `git rev-list --count origin/develop..origin/feat/issue-184-deploy-image` = **0**
   (develop là siêu tập).
2. `feat/issue-184-deploy-image` — đáp án cũ, **đã hết hạn**. PR #214 merge vào
   `develop` lúc `f82ad46`, và nhánh này giờ **thiếu 28 commit** của `develop`.
3. Không nhánh nào thoả → gộp cục bộ rồi đẩy nhánh mới lên GitHub:

```powershell
git checkout -b deploy-20260821 origin/develop
```

```powershell
git merge origin/feat/issue-184-deploy-image
```

```powershell
git push -u origin HEAD
```

Luôn `git fetch origin` trước khi kiểm — hai lệnh trên đọc ref cục bộ:

```powershell
git fetch origin
```

### V9.1. Xác thực GitHub bằng khoá SSH sinh **trên VPS**

Repo `P-192` là **private** và Sơn **không phải admin repo** — *Settings → Deploy
keys* sẽ không mở được. Nhưng khoá SSH gắn với **tài khoản cá nhân** thì tự thêm
được, không cần ai duyệt.

Trên **VPS**, user `vivi`:

```bash
ssh-keygen -t ed25519 -C "vivi-vps-github" -f ~/.ssh/id_ed25519 -N ""
```

```bash
cat ~/.ssh/id_ed25519.pub
```

Chép dòng đó. Trên GitHub: ảnh đại diện → **Settings** → **SSH and GPG keys** →
**New SSH key** → Title `vps-vivi`, Key type **Authentication key**, dán vào →
**Add SSH key**.

Kiểm — lệnh này **luôn thoát mã 1 kể cả khi thành công**, cứ đọc chữ:

```bash
ssh -T git@github.com
```

Phải thấy `Hi <ten>! You've successfully authenticated`.

> **Hơn PAT ở hai điểm:** không có chuỗi bí mật nằm nguyên văn trong
> `/opt/vivi/.git/config`, và xoá bằng một cú bấm trên GitHub sau buổi demo. Vẫn
> nhớ: khoá này mở **mọi** repo tài khoản bạn truy cập được — xoá khi xong.

### V9.2. Clone

`/opt/vivi` phải **rỗng**:

```bash
ls -A /opt/vivi
```

Có nội dung thì dọn:

```bash
sudo rm -rf /opt/vivi && sudo mkdir -p /opt/vivi && sudo chown vivi:vivi /opt/vivi
```

```bash
git clone -b develop git@github.com:AI20K-Build-Phase-Cohort-3/P-192.git /opt/vivi
```

```bash
cd /opt/vivi && git log --oneline -1
```

Kiểm `Dockerfile` đúng bản — phải in ra số **lớn hơn 0**:

```bash
grep -c requirements-voice /opt/vivi/Dockerfile
```

```bash
mkdir -p /opt/vivi/data
```

### V9.3. Vì sao `git pull` về sau không phá cấu hình

Bốn thứ tạo trên VPS đều bị gitignore, nên `git pull` không đụng tới:

| File trên VPS | Bỏ qua ở |
|---|---|
| `.env` (có mật khẩu MQTT) | `.gitignore:19` |
| `docker-compose.override.yml` | `.gitignore:65` |
| `frontend/.env.production`, `.env.runtime` | `frontend/.gitignore` (`.env*`) |
| `data/` (chỉ mục RAG) | `.gitignore:39` |
| `models/voice/*` | `.gitignore:83` |

> **Chỉ `pull`, đừng bao giờ `push` từ VPS.** Hook `pre-push` chạy mỗi lần push, mà
> `.env` trên VPS có `AI_LOG_API_KEY`. Máy chủ là nơi chạy, không phải nơi làm việc.

### V9.4. Đường dự phòng — `git archive` + `scp`, khi GitHub không vào được

Dùng khi `ssh -T git@github.com` treo hoặc mạng chặn `github.com`. Đánh đổi: VPS
không có `.git` nên **không `git pull` được**, và **không lùi phiên bản được**.

**PowerShell:**

```powershell
git checkout develop
```

```powershell
git archive --format=tar.gz -o ..\vivi-src.tar.gz HEAD
```

```powershell
scp ..\vivi-src.tar.gz vivi@103.146.23.41:/tmp/
```

**VPS:**

```bash
tar -xzf /tmp/vivi-src.tar.gz -C /opt/vivi
```

> `git archive` chỉ đóng file **đã commit** — sửa dở chưa commit thì không đi theo,
> triệu chứng là "sửa rồi mà VPS không đổi".

## W6 — artifact ngoài git, **không bỏ được**

**Trên PowerShell, tại thư mục gốc repo:**

```powershell
scp -r models vivi@103.146.23.41:/opt/vivi/
```

```powershell
scp -r data\rag vivi@103.146.23.41:/opt/vivi/data/
```

**Trên VPS** — phải thấy 6 file voice và 5 file trong `data/rag/vf9_2026_vi/`:

```bash
find /opt/vivi/models/voice /opt/vivi/data/rag -type f | sort
```

```bash
ls -la /opt/vivi/data/rag/vf9_2026_vi/index.faiss
```

## V10 — `.env`, viết bằng `sed` chứ không mở `nano`

**Đã chạy thật 2026-08-21.** Dùng `sed` thay `nano` vì hai lý do: không gõ nhầm, và
bản dán từ khung chat bị thêm thụt lề nên mọi thứ nhiều dòng đều rủi ro.

```bash
cd /opt/vivi && cp .env.example .env
```

```bash
sed -i 's|^APP_ENV=.*|APP_ENV=production|' /opt/vivi/.env
```

```bash
sed -i 's|^MQTT_URL=.*|MQTT_URL=mqtt://mqtt:1883|' /opt/vivi/.env
```

```bash
sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=http://localhost:3000|' /opt/vivi/.env
```

> **Vì sao là `localhost` chứ không phải tên miền, và khi có tên miền thì sao.**
> `CORS_ORIGINS` nhận **danh sách phân tách bằng dấu phẩy** (`main.py:160` và
> `ws.py:176` cùng `split(",")`), nên nó không phải chọn một.
>
> Giai đoạn chưa có tên miền, đường kiểm duy nhất là **SSH tunnel** (mục 6.2), mà
> Origin của tunnel là `http://localhost:3000`. Khai sẵn tên miền chưa tồn tại thì
> WebSocket đóng `4403` và không kiểm được gì.
>
> Khi có tên miền, **thêm vào chứ đừng thay** — giữ `localhost` để đường tunnel còn
> dùng được cho lần gỡ lỗi sau:
>
> ```bash
> sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=http://localhost:3000,https://vivi.id.vn|' /opt/vivi/.env
> ```
>
> ```bash
> cd /opt/vivi && docker compose up -d --force-recreate backend
> ```
>
> Backend đọc `.env` lúc khởi động nên **bắt buộc `--force-recreate`**; `restart`
> thường không nạp lại `env_file`. Và nhớ rằng đổi tên miền còn kéo theo **build lại
> frontend** (mục 7.4) — `NEXT_PUBLIC_*` là build-time.

`OMP_NUM_THREADS` **không có sẵn** trong `.env.example` nên phải nối thêm, không
`sed` được:

```bash
echo 'OMP_NUM_THREADS=4' >> /opt/vivi/.env
```

Vô hiệu hoá key log dùng chung — VPS không bao giờ `git push` nên nó không có việc
gì ở đây:

```bash
sed -i 's|^AI_LOG_API_KEY=.*|AI_LOG_API_KEY=|' /opt/vivi/.env
```

`MQTT_ENABLED` đã là `true` sẵn trong `.env.example`, không phải sửa.

### Bốn cái bẫy trong năm dòng này

1. **`MQTT_URL` là `mqtt://mqtt:1883`, KHÔNG phải `localhost`** — backend chạy trong
   container và gọi broker qua **tên service** trong mạng Docker. Để `localhost` thì
   backend tự gọi chính nó → `/healthz` báo `mqtt: down`, mọi lệnh điều khiển hỏng.
2. **`CORS_ORIGINS` khớp chính xác từng ký tự.** `ws.py:176` **không làm CORS** mà tự
   đối chiếu header `Origin` của WebSocket với biến này. Không dấu `/` cuối, không kèm
   cổng. Sai một ký tự → **WS đóng `4403` trong khi REST vẫn xanh**, trông y hệt
   "backend chết".
3. **`OMP_NUM_THREADS=4`** là **cái phanh**, không phải tinh chỉnh. Không đặt thì ONNX
   Runtime lấy hết nhân thấy được, và một lượt TTS chiếm trọn máy trong nửa giây mà
   **không nhanh hơn** — cả bốn thành phần đều bão hoà ở 4 luồng.
4. **`AI_LOG_API_KEY`** mặc định là key dùng chung của nhóm, và `.env` này nằm trên
   một máy đi thuê.

## V11 — mật khẩu Mosquitto, ghi thẳng vào `.env`

**Đã chạy thật 2026-08-21.** Bản gốc là `scripts/bootstrap_mqtt_secrets.ps1`
(PowerShell); đây là bản bash tương đương, giữ nguyên hai điều quan trọng: `-c`
**chỉ dùng cho user đầu tiên**, và file phải thuộc uid 1883.

> **Chạy liền mạch trong cùng một phiên SSH** — hai biến `$BACKEND_PW` / `$SIM_PW`
> chỉ sống trong phiên đó. Đứt kết nối giữa chừng thì làm lại từ đầu khối.

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

Ghi hai mật khẩu vào `.env` **bằng `sed`, không chép tay** — dùng nháy kép để shell
thay biến:

```bash
sed -i "s|^MQTT_BACKEND_PASSWORD=.*|MQTT_BACKEND_PASSWORD=$BACKEND_PW|" /opt/vivi/.env
```

```bash
sed -i "s|^MQTT_SIMULATOR_PASSWORD=.*|MQTT_SIMULATOR_PASSWORD=$SIM_PW|" /opt/vivi/.env
```

> `sed` an toàn ở đây vì `tr '+/=' 'xxx'` đã bỏ hết ký tự đặc biệt của base64 — mật
> khẩu còn lại chỉ gồm chữ và số, không có `|` hay `&` để phá biểu thức.

Hai dòng username đã đúng sẵn trong `.env.example`
(`MQTT_BACKEND_USERNAME=vivi-backend`, `MQTT_SIMULATOR_USERNAME=vehicle-simulator`).

### Kiểm `.env` — 11 dòng

```bash
grep -E "^(APP_ENV|MQTT_ENABLED|MQTT_URL|CORS_ORIGINS|OMP_NUM_THREADS|MQTT_BACKEND_USERNAME|MQTT_BACKEND_PASSWORD|MQTT_SIMULATOR_USERNAME|MQTT_SIMULATOR_PASSWORD|DATABASE_URL|RAG_INDEX_DIR)=" /opt/vivi/.env
```

Hai dòng `*_PASSWORD` phải **có giá trị**, không rỗng.

> **Không commit `config/mosquitto/passwd`.**


## V12 — ép backend chỉ nghe loopback

```bash
cp /tmp/vps/docker-compose.override.yml /opt/vivi/docker-compose.override.yml
```

```bash
cat /opt/vivi/docker-compose.override.yml
```

### Xác nhận `!override` thật sự có hiệu lực — làm TRƯỚC khi build

`cat` chỉ chứng minh file tồn tại, không chứng minh Compose đã gộp đúng.
`docker compose config` in ra cấu hình **sau khi gộp**, nên đây là chỗ duy nhất biết
chắc trước khi tốn 20–40 phút:

```bash
cd /opt/vivi && docker compose config | grep -E "host_ip|published|target"
```

Phải thấy `host_ip: 127.0.0.1` cho cổng **8000**, và **chỉ một** mục 8000. Thấy
`0.0.0.0` hoặc hai mục 8000 nghĩa là override chưa ăn — đúng cái lỗi mà thẻ
`!override` sinh ra để chặn.

Lệnh này còn kiêm việc **kiểm `.env` đọc được**: sai cú pháp `.env` thì nó báo ngay ở
đây thay vì giữa lúc build.

> **`!override` bắt buộc** — Compose **gộp** danh sách `ports` chứ không thay thế, nên
> viết `ports:` thường thì `"8000:8000"` vẫn còn nguyên và cổng 8000 vẫn mở ra
> Internet. `ufw` **không** chặn được cổng do Docker publish.

## V13 — build image

Kiểm hai mạng trước, cả hai phải ra `200`/`301`:

```bash
curl -sS -m 10 -o /dev/null -w 'pypi=%{http_code}\n' https://pypi.org/simple/
```

```bash
curl -sS -m 10 -o /dev/null -w 'hf=%{http_code}\n' https://huggingface.co
```

Đĩa còn ít nhất 10 GB trống cho image (~2,6 GB) cộng cache build:

```bash
df -h /
```

### Chạy build trong `tmux` — bắt buộc, không phải tuỳ chọn

Build mất **20–40 phút**. Chạy thẳng trong phiên SSH thì mạng chớp một cái là build
chết giữa chừng, và lần sau phải làm lại từ layer dở dang.

```bash
sudo apt install -y tmux
```

```bash
tmux new -s build
```

Màn hình đổi, có thanh xanh ở dưới cùng — đang ở trong tmux.

```bash
cd /opt/vivi && docker compose build
```

Thoát ra mà **để build chạy tiếp**: bấm `Ctrl+B`, nhả tay, rồi bấm `D`. Quay lại xem
tiến độ: `tmux attach -t build`.

Theo dõi từ **một phiên SSH thứ hai** (đừng dùng phiên đang build) — `load average`
vượt 4 lúc build là bình thường, xong phải tụt về gần 0:

```bash
uptime
```

**Đo thật trên máy này 2026-08-21: 513,9 s ≈ 8,6 phút** (cache lạnh, cả hai image).
Nhanh hơn hẳn ước lượng 20–40 phút — nhưng vẫn đủ dài để cần `tmux`.
Build tải torch CPU-only (528 MB), sherpa-onnx, piper, rồi nạp sẵn embedder E5
(471 MB) vào image. Ra hai tag: `vivi-backend:latest` và
`vivi-vehicle-simulator:latest` — **dùng chung layer**, không phải 2× dung lượng.

Dấu hiệu build sạch: dòng `✔ Image vivi-backend Built` và **không có** dòng
`THIEU ARTIFACT VOICE` ở giữa log.

Chết ở `THIEU ARTIFACT VOICE` → quay lại **W6**.

## V14 — khởi động backend

```bash
cd /opt/vivi && docker compose up -d --wait mqtt vehicle-simulator backend
```

```bash
docker compose ps
```

```bash
curl -s http://127.0.0.1:8000/healthz | python3 -m json.tool
```

| Thành phần | Phải là | `down` nghĩa là |
|---|---|---|
| `mqtt` | `ready` | Sai `MQTT_URL` hoặc sai mật khẩu |
| `vehicle_simulator` | `ready` | Xe ảo chưa nối được broker |
| `stt`, `tts` | `ready` | Image thiếu model → sai nhánh ở V9 |
| `rag_index` | `ready` | Thiếu `data/rag/` trên host → W6 |
| `llm` | `disabled` | **Đúng** — chưa bật SLM |

`mqtt` restart vô hạn → quên `chown 1883` ở V11:

```bash
docker compose logs mqtt --tail 30
```

## V15–V16 — biến môi trường frontend (bản **chưa có tên miền**)

```bash
cp /tmp/vps/env.production.tunnel /opt/vivi/frontend/.env.production
```

```bash
cat /opt/vivi/frontend/.env.production
```

> **Ba cờ `USE_MOCK_*` vẫn phải khai** dù hai URL trên trùng giá trị mặc định trong
> code — `turn/index.ts:7` so sánh `!== "false"`, không khai cũng là mock, và giao
> diện mock **nhìn y hệt** như thật.

```bash
cp /tmp/vps/env.runtime /opt/vivi/frontend/.env.runtime
```

```bash
chmod 600 /opt/vivi/frontend/.env.runtime
```

## V16b — **BẮT BUỘC: `git pull` trước khi build frontend**

**Vấp thật 2026-08-22.** Bản clone `11ef08f` **không build được frontend**:

```
src/components/ivi/LeafletMap.tsx(129,15): error TS2322:
  Type 'readonly [number, number]' is not assignable to type 'LatLngExpression'.
  The type 'readonly [number, number]' is 'readonly' and cannot be assigned
  to the mutable type 'LatLngTuple'.
```

**Không phải lỗi của người deploy.** Ở `11ef08f`, dòng 129 là
`<Marker position={current} .../>`, mà `current` khai `readonly [number, number]`
(`LeafletMapProps` dòng 88/96) còn `LatLngTuple` của leaflet là mảng **ghi được**.
TypeScript từ chối đúng luật.

Đã sửa ở **`d771b79`** (vào `develop` qua PR #238) thành `position={[...current]}` —
trải ra thành bản sao khả biến, chỉ nới `readonly` đúng ở ranh giới sang thư viện.
Kiểm chứng: `npx tsc --noEmit` trên `origin/develop` → **exit 0, sạch**.

> **Bài học chung, không riêng lỗi này:** giữa lúc clone và lúc build frontend, nhánh
> `develop` vẫn chạy tiếp. Luôn `git pull` trước `npm ci`.

### Trước khi pull — kiểm cây làm việc

```bash
cd /opt/vivi && git status --short
```

Ở máy này ra:

```
 M models/voice/vi_VN-piper.onnx.json.metadata.json
 M models/voice/vi_VN-piper.onnx.json.sha256
 M models/voice/vi_VN-piper.onnx.metadata.json
 M models/voice/vi_VN-piper.onnx.sha256
?? models/slm/
?? tools/llama/
```

**Cả sáu dòng đều bình thường**, nhưng phải hiểu vì sao:

- Bốn dòng `M` là do `scp` chép bản sinh trên Windows (**CRLF**) đè lên bản LF của
  repo. `git diff` in ra **rỗng** kèm `warning: CRLF will be replaced by LF` — tức
  **nội dung giống hệt**, chỉ khác kiểu xuống dòng.
- `??` là model 3B và llama.cpp, nằm ngoài git theo thiết kế.

**Đừng `git checkout` để "dọn cho sạch":** bản đang nằm đây mô tả đúng file `.onnx`
thật trên máy này. Kiểm một lần cho chắc, và đây mới là điều đáng kiểm:

```bash
cd /opt/vivi && git diff models/voice/vi_VN-piper.onnx.metadata.json
```

- Rỗng, hoặc chỉ khác `DownloadedAtUtc` → **bình thường**.
- Khác **`Sha256`** hoặc **`SizeBytes`** → **DỪNG.** File `.onnx` trên máy này không
  phải file nhóm đã kiểm.

`origin/develop` **không đụng vào `models/`**, nên `git pull` chạy trót lọt và giữ
nguyên bốn file đó.

```bash
cd /opt/vivi && git pull
```

```bash
cd /opt/vivi && git log --oneline -1
```

### Sau khi pull: **phải chạy lại `npm ci`**

`package.json` và `package-lock.json` **đều đổi** giữa hai mốc (+127 dòng lockfile) —
PR #238 thêm `onnxruntime-web` cho wake word.

### Sau khi pull: backend **KHÔNG** cần khởi động lại — và khởi động lại cũng vô ích

`docker-compose.yml` khai backend là `build: context: .`, code **nướng vào image**, và
container chỉ mount đúng một thư mục: `- ./data:/app/data`. **Không có bind mount cho
`src/`.**

Nên `git pull` sửa file trên đĩa host mà container không hề hay biết, và
`docker compose restart backend` sẽ khởi động lại **đúng image cũ với đúng code cũ** —
lệnh không làm gì ngoài việc cắt WebSocket đang mở.

Muốn backend chạy code mới thì chỉ có một đường, và **làm SAU khi xong frontend**:

```bash
cd /opt/vivi && docker compose build backend
```

```bash
cd /opt/vivi && docker compose up -d backend
```

Chưa cần gấp: giữa `11ef08f` và `origin/develop`, `src/api/` chỉ đổi
`session_state.py` (nội bộ), **không có route API mới**, nên frontend mới nói chuyện
được với image backend cũ.

> **Bẫy nhẹ nhưng có thật:** sau khi pull, `/opt/vivi/src/` **mới hơn** code đang chạy
> trong container. Không hỏng, nhưng dễ làm bạn nhầm khi đọc log — mở `graph.py` thấy
> code mới rồi thắc mắc sao hành vi không khớp. Nhớ là còn 8,6 phút rebuild ở giữa.

## V17 — cài và build frontend

```bash
cd /opt/vivi/frontend && npm ci
```

**Đo thật 2026-08-22: 34 giây**, 485 gói. Nhanh hơn ước tính nhiều vì bước này chủ yếu
là I/O mạng, không phải CPU — 4 vCPU E5 không phải cái nghẽn ở đây.

Hai cảnh báo `npm` in ra, **bỏ qua cả hai**:

| Cảnh báo | Vì sao bỏ qua |
|---|---|
| `1 high severity vulnerability` | **Đừng chạy `npm audit fix`.** Nó sửa `package-lock.json`, mà `npm ci` tồn tại chính là để lockfile **không** đổi. Chạy xong bạn có cây phụ thuộc khác cây nhóm đã test, ngay trước demo. Máy này chỉ nghe loopback — ghi lại xử sau |
| `New major version of npm 10.9.8 -> 12.0.2` | Nâng major version của npm giữa lúc deploy là tự chuốc rủi ro |

Kiểm `.env.production` còn nguyên (nó nằm ngoài git nên `git pull` không đụng tới),
**trước** khi build — vì `NEXT_PUBLIC_*` bị nướng vào JS lúc build:

```bash
cat /opt/vivi/frontend/.env.production
```

```bash
cd /opt/vivi/frontend && npm run build
```

> Với SLM **tắt**, máy 4,8 GiB còn trống ~3,1 GiB — `next build` (đỉnh 1 173 MB) vừa
> thoải mái, **không cần dừng gì**. Chỉ khi đã bật SLM mới phải dừng một dịch vụ.

### Output đúng — đo thật 2026-08-22

```
> npm run prepare:ort && next build
> node scripts/copy-ort-wasm.mjs
▲ Next.js 16.3.0 (Turbopack)
- Environments: .env.production
✓ Compiled successfully in 2.1s
✓ Finished TypeScript in 13.6s
✓ Collecting page data using 3 workers in 1053ms
✓ Generating static pages using 3 workers (8/8) in 643ms

Route (app)
┌ ○ /            ├ ○ /_not-found   ├ ƒ /api/auth/demo-driver
├ ○ /driver      ├ ○ /engineer     └ ○ /login
```

Ba dòng đáng đọc:

1. **`prepare:ort`** — bước tiền xử lý mới, chép ONNX Runtime WASM vào
   `public/ort-wasm/` (thư mục này **gitignore**, sinh ra lúc build). Đây là hạ tầng
   cho wake word "Hey Vi Vi" chạy **trong trình duyệt**. Model wake-word thì **có
   trong git** (`frontend/public/models/wake-word/`, 3 file `.onnx` + `.sha256`), nên
   **không phải `scp` gì thêm** — khác hẳn STT/TTS.
2. **`- Environments: .env.production`** — bằng chứng Next đã đọc đúng file. Không
   thấy dòng này nghĩa là ba cờ `USE_MOCK_*` chưa vào, và **giao diện mock nhìn y hệt
   bản thật**.
3. **`ƒ /api/auth/demo-driver`** — `ƒ` là route **động**, đọc `DEMO_DRIVER_EMAIL` /
   `DEMO_DRIVER_PASSWORD` lúc chạy. Đó là lý do `vivi-frontend.service` phải khai
   `EnvironmentFile=/opt/vivi/frontend/.env.runtime`. Thiếu file đó thì build vẫn
   xanh, service vẫn lên, nhưng **nút đăng nhập demo hỏng**.

Build in ra `Killed` = OOM. Khi đó:

```bash
cd /opt/vivi && docker compose stop backend
```

```bash
cd /opt/vivi/frontend && npm run build
```

```bash
cd /opt/vivi && docker compose start backend
```

## V18 — systemd cho frontend

```bash
sudo cp ~/vps/vivi-frontend.service /etc/systemd/system/vivi-frontend.service
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now vivi-frontend
```

### Kiểm — **`/` trả `307`, KHÔNG phải `200`**

**Vấp thật 2026-08-22.** Bản đầu của mục này ghi "phải ra `200`" cho `/` — **sai**.
`frontend/src/app/page.tsx` chỉ có bốn dòng:

```tsx
import { redirect } from "next/navigation";
export default function Home() { redirect("/login"); }
```

Trang gốc không render gì, nó đá thẳng sang `/login`, nên server trả **`307 Temporary
Redirect`** và `curl` mặc định **không đi theo redirect**. `307` ở đây là **đúng**.

Dùng một trong hai lệnh này, cả hai phải ra **`200`**:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/login
```

```bash
curl -sL -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
```

*(`-L` bảo curl đi theo redirect.)*

Log đúng — đo thật 2026-08-22:

```
Started vivi-frontend.service - VIVI frontend (Next.js).
> next start -H 127.0.0.1 -p 3000
▲ Next.js 16.3.0
- Local:   http://127.0.0.1:3000
✓ Ready in 348ms
```

Dòng `-H 127.0.0.1` là thứ đáng kiểm: frontend **không** được nghe `0.0.0.0`, vì ufw
không chặn nổi cổng do tiến trình tự mở ra ngoài (với Docker thì còn tệ hơn — mục 3).

Chưa ra `200` thì:

```bash
sudo journalctl -u vivi-frontend -n 50 --no-pager
```

---

# 5b. Không làm quá tải máy trong lúc setup

Máy này có **4 vCPU E5 v4** và **4,8 GiB RAM**. Hai bước duy nhất thật sự nặng là
`docker compose build` (V13) và `npm run build` (V17). Năm quy tắc dưới đây đủ để
không có bước nào giết bước nào.

## 5b.1. Chạy build dài trong `tmux` — quy tắc quan trọng nhất

`docker compose build` mất **20–40 phút** trên máy này. Nếu chạy thẳng trong phiên
SSH thì **mạng nhà bạn chớp một cái là build chết giữa chừng**, và lần sau phải làm
lại từ layer dở dang.

```bash
sudo apt install -y tmux
```

```bash
tmux new -s build
```

Trong cửa sổ tmux, chạy lệnh build như bình thường. Muốn thoát ra mà **để build chạy
tiếp**: bấm `Ctrl+B`, nhả ra, rồi bấm `D`.

Quay lại xem:

```bash
tmux attach -t build
```

Xem còn phiên nào đang chạy:

```bash
tmux ls
```

## 5b.2. Không bao giờ chạy hai build cùng lúc

`docker compose build` chiếm cả 4 nhân; `next build` đỉnh **1 173 MB** RAM. Chạy song
song là vừa chậm hơn tổng hai lần chạy nối tiếp, vừa dễ OOM.

**Thứ tự đúng:** V13 (docker build) → V14 (khởi động, kiểm `/healthz`) → V17 (npm
build). Xong hẳn một cái mới sang cái sau.

## 5b.3. `nice` chỉ có tác dụng ở một trong hai chỗ

| Lệnh | `nice` giúp không | Vì sao |
|---|---|---|
| `nice -n 10 npm run build` | **Có** | `next build` là tiến trình con của shell, thừa hưởng độ ưu tiên |
| `nice -n 10 docker compose build` | **Không** | Việc thật chạy trong **daemon `dockerd`**, không phải trong tiến trình CLI. `nice` chỉ hạ ưu tiên của cái vỏ |

Nên nếu muốn SSH còn mượt lúc build frontend:

```bash
cd /opt/vivi/frontend && nice -n 10 npm run build
```

Còn lúc `docker compose build` thì chấp nhận máy chậm — đó là lý do có `tmux`.

## 5b.4. Kiểm trước khi build

Đĩa còn đủ chỗ chưa (cần ~10 GB trống cho image + cache):

```bash
df -h /
```

RAM và swap:

```bash
free -h
```

Không có gì nặng đang chạy:

```bash
docker stats --no-stream
```

## 5b.5. Theo dõi trong lúc build, và đọc đúng con số

Mở **một phiên SSH thứ hai** (đừng dùng phiên đang build):

```bash
uptime
```

Cột `load average` trên máy 4 nhân: **> 4 là đã bão hoà**. Lúc build thì như vậy là
**bình thường và đúng ý** — build xong nó phải tụt về gần 0.

```bash
vmstat 5 6
```

Đọc hai cột: `si`/`so` (swap in/out) mà **liên tục khác 0** nghĩa là đang thật sự
thiếu RAM, không phải chỉ bận. Cột `st` cao nghĩa là hàng xóm đang giành CPU.

Nếu có gì đó bị OOM kill, dấu vết nằm ở đây:

```bash
dmesg -T | grep -i "killed process"
```

Không in gì là chưa có ai bị giết.

## 5b.6. Đừng build trong ngày demo

`docker builder prune` và mọi lần build lại đều làm máy bận hàng chục phút. Lịch an
toàn: build và kiểm xong **trước** ngày demo ít nhất một hôm, hôm demo chỉ khởi động
và hâm nóng (mục 6.3).

---

# 6. Kiểm chứng khi **chưa có tên miền**

Tên miền chỉ mua **một** thứ: HTTPS công khai. Mọi thứ khác kiểm được ngay.

## 6.1. Lượt hội thoại đầy đủ bằng `curl` — không cần trình duyệt

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login -H "Content-Type: application/json" -H "X-Schema-Version: 1.0" -d '{"email":"driver.demo@example.com","password":"DemoDriver123!"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])")
```

```bash
echo "${TOKEN:0:16}..."
```

```bash
SID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/sessions -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H "X-Schema-Version: 1.0" -H "Idempotency-Key: smoke-$(date +%s)" -d '{"vehicle_id":"vehicle-demo-01","input_mode":"text"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['session_id'])")
```

```bash
echo "$SID"
```

Lượt điều khiển — chứng minh router + policy + MQTT + xe ảo:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/turns/text -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H "X-Schema-Version: 1.0" -H "Idempotency-Key: turn-$(date +%s)" -d "{\"session_id\":\"$SID\",\"text\":\"bật điều hoà\"}" | python3 -m json.tool
```

Lượt tra sổ tay — chứng minh FAISS + E5 + composer:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/turns/text -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H "X-Schema-Version: 1.0" -H "Idempotency-Key: turn-$(date +%s)-rag" -d "{\"session_id\":\"$SID\",\"text\":\"áp suất lốp tiêu chuẩn là bao nhiêu\"}" | python3 -m json.tool
```

Trả về *"Tôi không tìm thấy thông tin này trong sổ tay xe."* → `data/rag/` chưa lên
đúng (W6).

## 6.2. Giao diện thật + **micro**, qua SSH tunnel

`http://localhost` là **secure context** theo chuẩn W3C, y như HTTPS — nên
`getUserMedia` chạy bình thường và **micro kiểm được trước khi có tên miền**.

**Trên PowerShell**, mở một cửa sổ mới và **để nguyên đó**:

```powershell
ssh -L 3000:127.0.0.1:3000 -L 8000:127.0.0.1:8000 vivi@103.146.23.41
```

Rồi mở trình duyệt tại **`http://localhost:3000`**.

Trước khi thử, mở Console (F12) và xoá service worker lạ — một service worker của
**dự án khác** từng chạy trên `localhost:3000` sẽ chặn mọi navigation, trang render
nhưng React không hydrate, click không ăn, **không báo lỗi gì**:

```js
(await navigator.serviceWorker.getRegistrations()).forEach(r => r.unregister());
(await caches.keys()).forEach(k => caches.delete(k));
```

Rồi kiểm **bốn** thứ:

| # | Việc | Hỏng thì lỗi ở đâu |
|---|---|---|
| 1 | `/login` → nút đăng nhập 1 chạm | V15 (URL tuyệt đối) hoặc V16 |
| 2 | `/driver` → gõ *"bật điều hoà"* | REST |
| 3 | Network → WS: `/ws/ivi` phải **mở**, không đóng `4403` | `CORS_ORIGINS` ở V10 |
| 4 | **Bấm micro và nói** | Chứng chỉ + STT/TTS |

> Cửa sổ trình duyệt phải ở **tiền cảnh** — tab ẩn bị bóp timer và hoãn media loading,
> `Audio` nằm ở `readyState 0` mãi mãi.

## 6.3. Hâm nóng trước khi demo

`src/main.py` warm sẵn E5 nhưng **không warm STT/TTS**. Lượt thoại **đầu tiên** đo
được `stt` **1 144 ms** so với **106 ms** khi đã ấm — chênh 10 lần.

**Tự bấm micro nói một câu trước buổi demo.**

## 6.4. Bảng tự chấm

| # | Lệnh | Xong nghĩa là |
|---|---|---|
| 1 | `docker compose ps` | V14 — 3 container `running` |
| 2 | `curl -s http://127.0.0.1:8000/healthz \| python3 -m json.tool` | V10–V14 |
| 3 | Ba lệnh `curl` ở 6.1 | Cả pipeline agent + MQTT + RAG |
| 4 | `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/` | V17–V18 |
| 5 | Tunnel 6.2 + 4 phép thử | Giao diện, WS, **micro** |
| 6 | `curl -s http://127.0.0.1:8093/health` | SLM (mục 7) |
| 7 | `curl -sI https://<domain>/ \| head -1` | **Chỉ bước này cần tên miền** |

Sáu dòng đầu xanh mà chưa có tên miền = **hệ đã chạy đủ**, chỉ thiếu lớp HTTPS công
khai.

---

# 7. Nối tên miền — V19 tới V21

## 7.0. Năm thứ phải biết về tên miền trước khi làm gì

Trả lời xong năm câu này thì phần còn lại chỉ là chép lệnh:

| # | Câu hỏi | Vì sao nó đổi cách làm |
|---|---|---|
| 1 | **Tên chính xác** — apex (`vivi.id.vn`) hay subdomain (`demo.vivi.id.vn`)? | Quyết định trường `Name` của bản ghi A: apex là `@`, subdomain là `demo`. Và chuỗi này phải **khớp từng ký tự** ở `CORS_ORIGINS`, `Caddyfile`, `.env.production` |
| 2 | **DNS quản lý ở đâu** — trang nhà đăng ký, hay đã trỏ nameserver sang chỗ khác? | Phải sửa A record **ở nơi đang giữ nameserver**. Sửa ở nhà đăng ký trong khi NS đã trỏ sang Cloudflare thì **không có tác dụng gì** |
| 3 | **Có dùng Cloudflare không?** Nếu có, đám mây **cam** hay **xám**? | Xem 7.0.1 — câu quan trọng nhất |
| 4 | **Có bản ghi `AAAA` (IPv6) nào không?** | Trình duyệt **ưu tiên IPv6**. Còn một AAAA trỏ đi đâu đó (thường là trang parking của nhà đăng ký) thì trang mở ra là trang kia, và Let's Encrypt cũng xác thực nhầm chỗ. **Xoá nó** |
| 5 | **Có chuyển hướng / parking đang bật không?** | Nhiều nhà đăng ký bật sẵn "URL forwarding" tới trang quảng cáo. Phải tắt, nếu không nó đè lên A record |

### 7.0.1. Cloudflare — nếu dùng thì để đám mây **XÁM**

Đám mây **cam** (proxy bật) gây hai hỏng, và cái thứ hai chỉ lộ ra giữa buổi demo:

1. **Let's Encrypt HTTP-01 thất bại.** Caddy cần cổng 80 tới thẳng máy chủ để xác
   thực; proxy chặn giữa đường.
2. **WebSocket bị cắt.** Proxy free của Cloudflare thường được nhắc là cắt kết nối
   sống lâu ở mốc **~100 giây**. `/ws/ivi` sống suốt phiên tài xế — đứt là giao diện
   ngừng nhận sự kiện. **Chưa đo trên hệ này**, nhưng đây đúng loại rủi ro không nên
   thử lần đầu vào hôm demo.

Cách đặt: trong bảng DNS của Cloudflare, bấm biểu tượng đám mây ở dòng A record cho
tới khi nó chuyển **xám** (`DNS only`). Cloudflare vẫn làm DNS, chỉ không đứng giữa.

## 7.1. Tạo bản ghi A

Ở nơi đang giữ nameserver (câu 2 ở trên):

| Trường | Giá trị |
|---|---|
| Type | **A** |
| Name | `@` nếu là apex, hoặc `demo` nếu dùng `demo.<tên miền>` |
| Value | **103.146.23.41** |
| TTL | 300 (5 phút) — để sửa sai nhanh |
| Proxy (nếu Cloudflare) | **DNS only — đám mây xám** |

Chưa có tên miền? `.id.vn` của VNNIC **miễn phí 2 năm** cho công dân VN 18–23 tuổi,
đăng ký qua iNET/PA/Nhân Hoà/Tenten. **Đừng dùng `nip.io`/`sslip.io`** — hạn mức
Let's Encrypt của chúng đã cạn từ 02/2026.

## 7.2. Đợi DNS lan, và kiểm **cả hai** loại bản ghi

```bash
sudo apt install -y dnsutils
```

Phải in ra đúng `103.146.23.41`:

```bash
dig +short A vivi.id.vn
```

Và phải **không in gì** — có dòng nào là còn AAAA cũ, phải xoá ở trang DNS:

```bash
dig +short AAAA vivi.id.vn
```

Kiểm từ một DNS công cộng để chắc là đã lan ra ngoài, không chỉ trong cache máy chủ:

```bash
dig +short A vivi.id.vn @8.8.8.8
```

**Chưa ra IP thì đừng cài Caddy** — Let's Encrypt sẽ từ chối, và có hạn mức số lần
thất bại cho mỗi tên miền.

## 7.3. Cập nhật `CORS_ORIGINS` — khai **cả hai**

```bash
nano /opt/vivi/.env
```

```
CORS_ORIGINS=http://localhost:3000,https://vivi.id.vn
```

Giữ `http://localhost:3000` để đường SSH tunnel (mục 6.2) vẫn dùng được sau này.

```bash
cd /opt/vivi && docker compose up -d --force-recreate backend
```

> **Khớp chính xác từng ký tự.** `ws.py:176` không làm CORS mà tự đối chiếu header
> `Origin` với biến này. Không dấu `/` cuối, không kèm cổng, đúng scheme `https`.
> Sai một ký tự → **WS đóng `4403` trong khi REST vẫn xanh**.

## 7.4. Build lại frontend — **bắt buộc**

`NEXT_PUBLIC_*` là **build-time**. Đổi file rồi `systemctl restart` là **không có gì
thay đổi** — bundle JS vẫn trỏ `localhost:8000`, mà trên máy người xem thì ở đó không
có gì cả.

```bash
cp /tmp/vps/env.production.domain /opt/vivi/frontend/.env.production
```

```bash
sed -i 's|DOMAIN_PLACEHOLDER|vivi.id.vn|g' /opt/vivi/frontend/.env.production
```

```bash
cat /opt/vivi/frontend/.env.production
```

Không được còn chuỗi `DOMAIN_PLACEHOLDER` nào.

```bash
cd /opt/vivi/frontend && npm run build
```

```bash
sudo systemctl restart vivi-frontend
```

## 7.5. Caddy

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
sudo cp /tmp/vps/Caddyfile /etc/caddy/Caddyfile
```

```bash
sudo sed -i 's|DOMAIN_PLACEHOLDER|vivi.id.vn|g' /etc/caddy/Caddyfile
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

```bash
sudo systemctl reload caddy
```

Theo dõi lúc xin chứng chỉ (10–30 giây, `Ctrl+C` để thoát):

```bash
sudo journalctl -u caddy -f
```

> **Đừng viết `handle /api/*`.** `/api/auth/demo-driver` là route của **Next.js**,
> không phải backend (backend chỉ đăng ký prefix `/api/v1`). Gom cả `/api/*` về cổng
> 8000 là **nút đăng nhập 1 chạm chết trong khi mọi thứ khác xanh** — lỗi hay gặp
> nhất của cả runbook.

## 7.6. Kiểm chứng qua HTTPS

```bash
curl -s https://vivi.id.vn/healthz | python3 -m json.tool
```

```bash
curl -sI https://vivi.id.vn/ | head -1
```

Phải là `200` **từ Next**. Ra `404` → khối `handle` cuối trong Caddyfile sai.

Rồi mở trình duyệt tại `https://vivi.id.vn` và chạy lại **bốn** phép thử ở mục 6.2 —
lần này không cần tunnel.

## 7.7. Xin chứng chỉ thất bại — ba nguyên nhân theo thứ tự hay gặp

| Trong `journalctl -u caddy` | Nguyên nhân | Chữa |
|---|---|---|
| `no valid A/AAAA records`, hoặc timeout | DNS chưa lan | Đợi, kiểm lại 7.2 |
| `connection refused` / `timeout` khi xác thực | Cổng 80 chưa mở, hoặc Cloudflare proxy **cam** | `sudo ufw status`; đổi đám mây sang **xám** |
| Xác thực đi tới **máy khác** | Còn bản ghi **AAAA** trỏ chỗ cũ | Xoá AAAA (7.2) |

# 7b. Khi đổi sang tên miền thật — ba chỗ, và một chế độ hỏng im lặng

**Ghi trước khi cần, theo yêu cầu của Sơn 2026-08-22.** Đổi tên miền chạm đúng ba
chỗ. Hai chỗ đầu sửa lúc chạy, chỗ thứ ba **phải build lại**.

| Chỗ | File | Đổi lúc nào |
|---|---|---|
| CORS + Origin của WebSocket | `/opt/vivi/.env` → `CORS_ORIGINS` | lúc chạy — `docker compose up -d backend` |
| Reverse proxy | `/etc/caddy/Caddyfile` | lúc chạy — `systemctl reload caddy` |
| **URL trong bundle JS** | `frontend/.env.production` | **lúc build — phải `npm run build` lại** |

## 7b.1. Chế độ hỏng im lặng, và nó nhắm thẳng vào người deploy

`NEXT_PUBLIC_*` là biến **lúc build**, bị nướng vào file JS. Năm file đọc chúng theo
cùng khuôn:

```ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
```

(`app/api/auth/demo-driver/route.ts`, `lib/services/{engineer,session,turn}/real.ts`)

Sửa Caddy, sửa `CORS_ORIGINS`, **quên build lại frontend** → trang tải bình thường,
nhưng mọi lời gọi API đi tới `http://localhost:8000`, tức **máy của người đang xem**.
Với người ngoài thì hỏng sạch.

> **Người deploy là người duy nhất không phát hiện được lỗi này**, vì lúc kiểm bằng
> SSH tunnel thì `localhost:8000` trên máy họ *có thật*.

### Cách bắt nó mà không cần nhờ ai test

```bash
grep -rl "localhost:8000" /opt/vivi/frontend/.next/static/ | head
```

**Trống = build sạch. Ra kết quả = quên build lại.** Chạy lệnh này ngay sau mỗi lần
đổi tên miền, trước khi báo cho ai.

## 7b.2. Quy trình đổi tên miền — đúng thứ tự

```bash
sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=https://TEN-MIEN-CUA-BAN|' /opt/vivi/.env
```

```bash
cd /opt/vivi && docker compose up -d backend
```

```bash
sed -e 's|DOMAIN_PLACEHOLDER|TEN-MIEN-CUA-BAN|g' ~/vps/env.production.domain > /opt/vivi/frontend/.env.production
```

```bash
cd /opt/vivi/frontend && npm run build
```

```bash
sudo systemctl restart vivi-frontend
```

```bash
grep -rl "localhost:8000" /opt/vivi/frontend/.next/static/ | head
```

`CORS_ORIGINS` **không có dấu `/` cuối, không kèm cổng** — `ws.py:176` **không dùng
CORS middleware** mà tự đối chiếu header `Origin`, nên lệch một ký tự là **WS đóng
`4403` trong khi REST vẫn xanh**, trông y hệt "backend chết".

## 7b.3. Đường làm cho nó khỏi phải nhớ — chưa làm, cần quyết

Caddy đã gom tất cả về **một origin** (`/api/v1/*`, `/ws/*`, `/healthz` → `:8000`,
còn lại → `:3000`). Nên phía **trình duyệt** không cần biết tên miền: dùng đường dẫn
**tương đối** và suy WebSocket từ `window.location`. Khi đó một build chạy được ở cả
tunnel lẫn tên miền thật, và tên miền **biến mất khỏi mọi file build**.

Một chi tiết bắt buộc phải xử đúng: **`app/api/auth/demo-driver/route.ts` chạy trên
server Node, không phải trình duyệt.** `fetch("/api/v1/...")` trong Node ném lỗi vì
không có origin. Nên nó cần biến **riêng, không tiền tố `NEXT_PUBLIC_`**, đọc lúc
chạy từ `.env.runtime`:

```
BACKEND_INTERNAL_URL=http://127.0.0.1:8000/api/v1
```

Cách này còn đúng hơn về bản chất — server gọi backend qua loopback, không đi vòng ra
Caddy rồi quay lại.

**Phạm vi:** 5 file + test cho `lib/services/` (bắt buộc theo `CLAUDE.md`). Một PR
nhỏ. **Chưa làm** — quyết sau khi đo xong SLM, đừng trộn hai việc.

---

# 8. SLM — đo trước, bật sau

> **Chỉ làm sau khi mục 6 đã xanh.** Máy này có CPU E5-2696 v4, xem mục 2.

## 8.1. Cài llama.cpp

```bash
mkdir -p /opt/vivi/tools/llama && cd /opt/vivi/tools/llama
```

```bash
curl -fsSLO https://github.com/ggml-org/llama.cpp/releases/download/b10358/llama-b10358-bin-ubuntu-x64.tar.gz
```

```bash
tar -xzf llama-b10358-bin-ubuntu-x64.tar.gz
```

Tarball giải nén ra thư mục con — tìm nhị phân thật thay vì đoán đường dẫn:

```bash
find /opt/vivi/tools/llama -type f -name "llama-bench"
```

Đo 2026-08-21: ra `/opt/vivi/tools/llama/llama-b10358/llama-bench`, tarball 16,5 MB.

### Thiếu `libgomp.so.1` — gặp thật trên máy này

Ảnh cloud Ubuntu 24.04 tối giản **không có** GNU OpenMP runtime (bình thường nó đi
kèm `gcc`/`build-essential`). Triệu chứng:

```
./llama-bench: error while loading shared libraries: libgomp.so.1:
cannot open shared object file: No such file or directory
```

`LD_LIBRARY_PATH=.` **không chữa được** — đây là thư viện *hệ thống*, không nằm trong
tarball, nên trỏ vào thư mục hiện tại là vô ích.

```bash
sudo apt install -y libgomp1
```

Còn thiếu thư viện khác thì lệnh này liệt kê **tất cả** một lượt, đỡ sửa từng cái:

```bash
ldd /opt/vivi/tools/llama/llama-b10358/llama-bench | grep "not found"
```

```bash
cd /opt/vivi/tools/llama/llama-b10358 && ./llama-server --version
```

Phải in `version: 10358` — trùng số repo đã ghim trong
`tools/llama-vulkan/llama-vulkan.metadata.json`.

> **Lưu ý về `curl -fsSLO`:** cờ `-s` là *silent*, nó tắt luôn thanh tiến độ, nên
> lệnh tải 16,5 MB trông như bị treo. Dùng `curl -fLO -#` nếu muốn thấy tiến độ.

## 8.2. Đưa model 3B lên (2,0 GB — tính bằng chục phút)

**Trên PowerShell:**

```powershell
ssh vivi@103.146.23.41 "mkdir -p /opt/vivi/models/slm"
```

```powershell
scp C:\vivi-models\qwen2.5-3b-instruct-q4_k_m.gguf vivi@103.146.23.41:/opt/vivi/models/slm/
```

```powershell
scp C:\vivi-models\qwen2.5-3b-instruct-q4_k_m.gguf.sha256 vivi@103.146.23.41:/opt/vivi/models/slm/
```

**Trên VPS** — phải in `OK`:

```bash
cd /opt/vivi/models/slm && sha256sum -c qwen2.5-3b-instruct-q4_k_m.gguf.sha256
```

Giá trị đúng: `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d`

## 8.3. **Phép đo quyết định** — chạy TRƯỚC khi dựng service

```bash
cd /opt/vivi/tools/llama && ./llama-bench -m /opt/vivi/models/slm/qwen2.5-3b-instruct-q4_k_m.gguf -t 2,4
```

Đọc cột `t/s` ở dòng **`tg`** (sinh token — chặng chiếm gần hết thời gian; dòng `pp`
là nạp prompt, không phải thứ đang hỏi):

| `-t 4` cho ra | Kết luận | Làm gì |
|---|---|---|
| **≥ 12 tok/s** | Ngang máy dev (14,0) | Bật SLM, giữ `SLM_TIMEOUT_S=8.0` |
| 8–12 tok/s | Chậm hơn, dùng được | Bật SLM + `SLM_TIMEOUT_S=12.0` |
| **< 8 tok/s** | Nhân quá chậm | **Để `SLM_ENABLED=false`** |
| `-t 2` ≈ `-t 4` | 4 vCPU là 2 nhân + SMT | Vẫn `-t 4`, nới timeout |

**Ghi lại con số này** — nó là bằng chứng cho quyết định, và là thứ phải trích kèm
tầng phần cứng theo kỷ luật evidence của repo.

## 8.3b. Kết quả đo thật trên máy này — 2026-08-22

```
| model                  |    size |  params | backend | threads |  test |            t/s |
| qwen2 3B Q4_K - Medium | 1.95GiB |  3.40 B | CPU     |       2 | pp512 |  10.65 ± 0.17 |
| qwen2 3B Q4_K - Medium | 1.95GiB |  3.40 B | CPU     |       2 | tg128 |   4.40 ± 0.09 |
| qwen2 3B Q4_K - Medium | 1.95GiB |  3.40 B | CPU     |       4 | pp512 |  19.95 ± 0.41 |
| qwen2 3B Q4_K - Medium | 1.95GiB |  3.40 B | CPU     |       4 | tg128 |   7.17 ± 0.25 |
build: 030ebb558 (10358)
```

*Backend nạp `libggml-cpu-haswell.so` — đúng nhánh AVX2, không rơi về generic.*

### Hai điều đọc được

**1. Bốn nhân vật lý là thật.** `7,17 / 4,40 = 1,63×` — đúng tỉ lệ của bốn nhân
riêng, không phải 2 nhân + SMT. Nghi ngờ ở mục 2 **sai ở điểm này**. Hệ quả: `-t 4`
là giá trị đúng, và **thêm vCPU sẽ không giúp gì** (đã bão hoà ở 4).

**2. Chậm hơn máy dev 1,95×.** 7,17 so với 14,0 tok/s. Quy đổi sang độ trễ planner
(decode chiếm gần hết; `predicted_n` trung vị đo được là 49 token):

| | Máy dev `-t 4` | Máy này |
|---|---:|---:|
| Giải mã 49 token | 3,5 s | **6,8 s** |
| Planner p50 | **5 329 ms** (đo) | **~8,5–10 s** (suy ra, **chưa đo trực tiếp**) |
| Trần `SLM_TIMEOUT_S` | 8 000 ms | 8 000 ms |

Ở mặc định 8,0 thì **quá nửa lời gọi planner sẽ quá hạn**, thử lại một lần, rồi vẫn
lui về câu trả lời sổ tay — tới 16 giây để nhận đúng thứ bản tắt cờ đưa ra trong
~100 ms.

### Điều làm mọi thứ nhẹ đi: câu dẫn SLM **đã tắt sẵn**

`src/config.py:57` khai `cau_dan_dung_slm: bool = False`, và `session_state.py:210`
chỉ dựng `QwenLeadIn` khi cờ đó bật. Ghi chú trong code: *"mẫu ghép từ câu hỏi vừa
nhanh hơn (0 ms so với 2316 ms trên CPU) vừa không bịa được"*.

Nghĩa là `SLM_ENABLED=true` trên máy này **chỉ bật planner**, và planner chỉ chạy khi
router **không khớp luật nào** — không phải mọi lượt.

> **Đừng đặt `CAU_DAN_DUNG_SLM=true` trên máy này.** Quy đổi 1,95× thì câu dẫn sẽ tốn
> ~4,5 s và nó nằm trên **mọi** câu trả lời sổ tay.

### Quyết định

| Đường | Cấu hình | Đánh giá |
|---|---|---|
| **Khuyến nghị cho demo** | `SLM_ENABLED=false` | Mất đúng câu dẫn tự nhiên. **Không mất chức năng nào** — định tuyến vẫn 100% bằng luật |
| Nếu bắt buộc 3B | `SLM_ENABLED=true` + **`SLM_TIMEOUT_S=15.0`** | Ca xấu nhất 30 s (hai lần timeout). Nói rõ khi trình bày đây là CPU 2016 |
| Đáng thử nếu còn thời gian | Đổi sang **0,5B** | Máy dev đo 44,7 tok/s → quy đổi ~23 tok/s, p50 ~2,2 s, RAM 645 MB. **Phải kiểm lại chất lượng** — prompt trong `slm.py` hiệu chỉnh cho 3B |

**Đừng nới `SLM_TIMEOUT_S` quá 15–18 s:** mỗi lượt hỏng tốn **hai** lần timeout, nên
25 s thành 50 s chờ ở ca xấu — không ai đợi.

> **Con số 7,17 tok/s này là phép đo tại chỗ, chưa có run id.** Muốn trích thành bằng
> chứng thì phải chạy lại qua `scripts/spike3_bench.py` để nó ghi
> `eval/results/spike-003/<run-id>/`. Lưu ý script đó có một dòng gọi PowerShell
> (`_server_rss_mb`, `spike3_bench.py:32`) sẽ ném `FileNotFoundError` trên Linux —
> phải vá trước khi chạy.

## 8.3b-2. Đường cong theo số luồng — `-t 2,3,4 -r 3`, đo 2026-08-22

```
| qwen2 3B Q4_K - Medium | 1.95 GiB | 3.40 B | CPU | 2 | pp512 | 10.68 ± 0.10 |
| qwen2 3B Q4_K - Medium | 1.95 GiB | 3.40 B | CPU | 2 | tg128 |  4.35 ± 0.13 |
| qwen2 3B Q4_K - Medium | 1.95 GiB | 3.40 B | CPU | 3 | pp512 | 15.67 ± 0.32 |
| qwen2 3B Q4_K - Medium | 1.95 GiB | 3.40 B | CPU | 3 | tg128 |  5.98 ± 0.14 |
| qwen2 3B Q4_K - Medium | 1.95 GiB | 3.40 B | CPU | 4 | pp512 | 19.99 ± 0.05 |
| qwen2 3B Q4_K - Medium | 1.95 GiB | 3.40 B | CPU | 4 | tg128 |  7.41 ± 0.31 |
```

> **Nhiễu giữa hai lần đo:** `-t 2` là 4,35 (lần này) so với 4,40 (8.3b), `-t 4` là
> 7,41 so với 7,17 — lệch ~3%. **Chênh dưới 5% giữa hai lần chạy là nhiễu**, đừng đọc
> thành cải thiện hay suy giảm.

### Trần băng thông của máy ảo này: **~25 tok/s**

Ba điểm khớp mô hình bão hoà băng thông `T(n) = A·n/(n+k)` với **sai số dưới 0,5%** ở
điểm giữa (n=3: mô hình 6,00 so với đo 5,98):

**`A = 24,99 tok/s`, `k = 9,49`**

`A` là tiệm cận — **trần băng thông bộ nhớ mà 4 vCPU này nhận được**. Dù thêm bao
nhiêu luồng, 3B trên máy này **không bao giờ vượt ~25 tok/s**. Đây là con số quan
trọng nhất rút ra được từ cả phép đo.

| vCPU | tg128 | Giải mã 49 token | So với hiện tại |
|---:|---:|---:|---:|
| 2 | 4,35 *(đo)* | 11,3 s | — |
| 3 | 5,98 *(đo)* | 8,2 s | — |
| **4** | **7,41** *(đo)* | **6,6 s** | *hiện tại* |
| 5 | ~8,6 | ~5,7 s | **+16%** |
| 6 | ~9,7 | ~5,1 s | +31% |
| 8 | ~11,4 | ~4,3 s | +54% |
| 12 | ~14,0 | ~3,5 s | +88% |
| ∞ | **24,99** | 2,0 s | trần tuyệt đối |

### Ba điều cần biết trước khi trả tiền thêm vCPU

**1. Nhà cung cấp thường không bán 5 vCPU** — bậc thực tế là 4 → 6 → 8. Câu hỏi thật
là "+31% hay +54%", không phải "+16%".

**2. Không được đưa hết vCPU cho llama-server.** Backend còn STT/TTS với
`OMP_NUM_THREADS=4`. Trên máy 8 vCPU nên để **`-t 6`** cho llama và chừa 2 cho phần
còn lại → thực nhận ~9,7 chứ không phải 11,4. Đặt `-t 8` thì hai bên giành nhau và
**cả hai cùng chậm đi**.

**3. Ngoại suy ra ngoài vùng đã đo.** Ba điểm nằm ở n=2..4. **n=5 là nội suy, tin
được; n=8 là ngoại suy, đọc như cận trên.** Đường thật có thể phẳng nhanh hơn vì
steal time tăng khi thuê nhiều vCPU trên host chia sẻ (hiện 0–1% ở 4 vCPU) và vì vượt
ranh giới NUMA.

### `pp` scale gần tuyến tính — nhưng không cứu được lượt nguội

10,68 → 15,67 → 19,99: từ 2 lên 4 luồng được **1,87×, hiệu suất 94%**. Đúng lý thuyết:
prompt processing bị chặn bởi **tính toán**, không phải băng thông — ngược hẳn với
`tg`.

Nhưng ngay ở 8 luồng (~35 tok/s ước tính), prefill nguội 650 token vẫn mất **~19
giây**, vẫn quá mọi trần timeout hợp lý. **Warm-up call (8.3c) vẫn bắt buộc**, thêm
vCPU không thay thế được nó.

### Kết luận chung cho mọi phương án phần cứng

| Đường | tg128 | Planner p50 | Chi phí |
|---|---:|---:|---|
| Hiện tại 4 vCPU, 3B | 7,41 *(đo)* | ~7,6 s | — |
| +1 vCPU | ~8,6 | ~6,7 s | tiền/tháng |
| 8 vCPU (thực dùng `-t 6`) | ~9,7 | ~6,1 s | tiền nhiều hơn |
| Platinum 8163, 4 vCPU (mục 8.3d) | ~8,6–11,5 | ~5,7–6,7 s | tiền + di trú |
| **Đổi sang 0,5B** | ~23 | **~2,1 s** | **0 đ** |

**Mọi phương án phần cứng rơi vào cùng một khoảng 5,7–6,7 s, chỉ khác giá.** Không
phương án phần cứng nào đưa hệ ra khỏi vùng sát trần 8 s. Đổi model thì có.

## 8.3c. Lượt planner ĐẦU TIÊN sẽ hỏng — và cách chữa miễn phí

**Phát hiện 2026-08-22, từ chính hai con số ở 8.3b.** Đây là lỗi thật trên máy này,
không phụ thuộc việc đổi chip hay không.

`src/agents/slm.py:155` ghép prompt như sau:

```
"prompt": SLM_UNION_PROMPT + normalized_text + "
JSON:"
```

`SLM_UNION_PROMPT` (`slm.py:84`) là **1 818 ký tự cố định** — khoảng **550–700 token**
few-shot — và câu của tài xế chỉ nối vào **cuối**. Hệ quả:

| Lượt | Phải prefill | Ở `pp512` = 19,95 tok/s |
|---|---:|---:|
| **Đầu tiên sau khi khởi động llama-server** | ~650 token | **≈ 33 giây** |
| Các lượt sau (tiền tố đã nằm trong KV cache) | ~10–30 token | < 1,5 giây |

33 s vượt xa `SLM_TIMEOUT_S` ở mọi giá trị hợp lý. `graph.py` thử lại **một lần**, nên
lượt nguội tốn **hai** lần timeout rồi vẫn lui về câu trả lời sổ tay — **~66 giây** nếu
để `SLM_TIMEOUT_S=33`, hoặc hỏng ngay hai lần nếu để 15 s.

> **Nếu khởi động lại `vivi-slm.service` ngay trước lúc demo, câu SLM đầu tiên chắc
> chắn hỏng.** Không cờ nào chữa được, vì đây là công việc tính toán thật.

### Bằng chứng gián tiếp rằng cache tiền tố có hoạt động

Máy dev đo p50 **5 329 ms** với `predicted_n` trung vị 49 token ở 14,0 tok/s → riêng
giải mã đã 3,5 s, chỉ còn ~1,8 s cho mọi thứ khác. **Không đủ chỗ cho 650 token
prefill.** Và caption của bảng đó ghi *"đã bỏ lượt nguội"*. Hai điều khớp nhau: lượt
nguội trả tiền prefill đầy đủ, lượt ấm thì không.

### Cách chữa: làm nóng sau khi service lên

Bắn một lời gọi `/completion` giả ngay sau khi llama-server sẵn sàng, để nạp tiền tố
vào KV cache trước khi có người dùng thật. Chi phí: 0 đồng, ~35 s một lần lúc khởi
động, và nó nằm ngoài đường đi của người dùng.

Chưa dựng — xem "Việc tiếp theo".

## 8.3d. Có nên đổi sang máy chip Xeon Platinum 8163 không?

**Câu hỏi của Sơn 2026-08-22.** Kết luận: **cải thiện ước chừng 1,2–1,6× ở phần sinh
token, và con số đó không đảm bảo được.** Không đủ để đổi máy nếu chưa làm ba việc
miễn phí ở dưới.

| | E5-2696 v4 (máy này) | Platinum 8163 | Tỉ lệ |
|---|---|---|---|
| Kênh nhớ | 4 × DDR4-2400 (~77 GB/s/socket) | 6 × DDR4-2666 (~128 GB/s/socket) | **1,67×** |
| Xung nền / turbo | 2,2 / 3,6 GHz | 2,5 / **3,5** GHz | 1,14× / **0,97×** |
| Đơn luồng (PassMark) | — | — | **tương đương** |
| Nhân / luồng | 22C / 44T, Broadwell-EP 2016 | 24C / 48T, Skylake-SP 2017 | — |
| SIMD | AVX2 | **AVX-512** | xem dưới |

**Chỉ cột băng thông có ý nghĩa**, vì sinh token bị chặn bởi bộ nhớ chứ không phải
tính toán. Nhưng 1,67× là mức **socket**: thuê 4 trong 24 nhân thì phần băng thông
thật sự tới được 4 vCPU đó phụ thuộc NUMA, cách hypervisor xếp vCPU, và hàng xóm cùng
node — **không suy ra được từ thông số ghi trên giấy**. Chia đều băng thông cho số
nhân (`77 ÷ 22`) là phép tính không đứng vững; đừng dùng nó làm cơ sở quyết định.

Lõi CPU tự nó gần như không cho gì: xung nền nhích 14%, **turbo còn thấp hơn**, và
PassMark cho thấy hiệu năng đơn luồng hai đời này ngang nhau.

### AVX-512: con số 2,8–10× **không áp dụng** cho hệ này

Mức tăng đó là cho **prompt processing**. Nhưng theo 8.3c, tiền tố 650 token là **cố
định** và nằm trong KV cache, nên mỗi lượt ấm chỉ prefill ~10–30 token. **Prefill gần
như miễn phí → AVX-512 không có việc gì làm.** Nó chỉ giúp đúng lượt nguội (33 s →
3–12 s) — mà một lời gọi warm-up cũng giải quyết chuyện đó, miễn phí.

### Bảng so cái mua bằng tiền với cái không tốn tiền

| Đường | tok/s | Planner p50 (49 token) | Chi phí |
|---|---:|---:|---|
| Hiện tại, 3B, `-t 4` | 7,17 *(đo)* | ~6,8 s | — |
| Đổi sang Platinum, 3B | ~8,6–11,5 *(ước)* | ~4,3–5,7 s *(ước)* | tiền + di trú |
| Thêm vCPU (8T) máy cũ | **chưa đo** | **chưa đo** | tiền, ít hơn |
| **Đổi sang 0,5B** | quy đổi ~23 | **~2,1 s** | **0 đ** |
| **Thêm warm-up** | — | bỏ được lượt hỏng ~66 s | **0 đ** |

*(0,5B: p50 1 135 ms, 44,7 tok/s, RAM 645 MB trên máy dev —
`deploy_vps_fullstack.md:1622`.)*

Platinum đưa từ "vượt trần 8 s" sang "vừa lọt dưới trần" — mong manh, không thoải
mái. Đổi model đưa xuống ~2 s. Cái giá của 0,5B là **chất lượng**, vì prompt ở
`slm.py:84` hiệu chỉnh cho 3B — nhưng kiểm được bằng 30 câu kịch bản demo trong một
giờ, không tốn đồng nào.

### Thứ tự việc trước khi quyết đổi chip

1. **Đếm planner thật sự chạy bao nhiêu lần** trong kịch bản demo — nó chỉ chạy khi
   `route_reason == "default_to_manual"` (`graph.py:254`). Nếu là 2/30 câu thì cả câu
   hỏi này gần như vô nghĩa.
2. **Thêm warm-up** (8.3c) — sửa lỗi 66 s, không phụ thuộc chip.
3. **Thử 0,5B**, đo lại bằng đúng 30 câu đó.
4. Chỉ khi cả ba vẫn không đủ, mới hỏi LANIT về máy Platinum.

> **Cảnh báo về so sánh số:** `14,0 tok/s` của máy dev đến từ `spike3_bench.py` gọi
> `/completion` thật có `json_schema`, còn `7,17` đến từ `llama-bench tg128` (tổng
> hợp, không grammar, prompt tối giản). **Hai phép đo khác phương pháp**, nên tỉ lệ
> `1,95×` là ước lượng chứ không phải số đo. Muốn so đúng phải chạy `spike3_bench.py`
> trên VPS — vướng `_server_rss_mb` (`spike3_bench.py:32`) gọi PowerShell, phải vá.

## 8.3e. **Phép đo tầng 2** — `spike3_bench.py`, đường planner thật, 2026-08-22

**Đây là run đầu tiên so trực tiếp được với máy dev**: cùng script, cùng
`json_schema`, cùng cách tính. Mọi tỉ lệ trước đó (`1,95×`) là ghép hai phương pháp
khác nhau và **không còn dùng nữa**.

**Run id: `20260822T053907.241420Z`** — `eval/results/spike-003/`.

```
 "decode_tps_median": 6.8,
 "total_ms_p50": 7802.821,
 "total_ms_p95": 8680.793,
 "truncated": 0,
 "server_peak_rss_mb": 3352.0,
 "model_sha256": "626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d"
```

### So với máy dev — cùng phương pháp

| | Máy dev | Máy này | Tỉ lệ |
|---|---:|---:|---:|
| Planner p50 | 5 329 ms | **7 803 ms** | **1,46×** |
| Decode tok/s | 14,0 | **6,8** | 2,06× |

**1,46× chứ không phải 1,95×.** Chênh lệch tổng nhỏ hơn chênh lệch decode vì
`total_ms` gồm cả prefill (đã cached, rẻ ở cả hai máy) nên phần chậm bị pha loãng.

### Bảng 16 case — nguồn của mọi kết luận dưới đây

```
    case  prompt_n  prompt_ms  pred_n   pred_ms  total_ms
  warm-0       562      28733      46      6904     35637
  warm-1        10        781      51      7482      8263
  warm-2         8       1116      31      4297      5413
  warm-3         8        506      27      3933      4438
  warm-4        12        859      50      7395      8254
  warm-5        10        669      30      4110      4779
  warm-6        11        827      46      7706      8533
  warm-7        10        741      51      7940      8681
  warm-8         8        561      31      4186      4747
  warm-9         8        722      27      3756      4478
 warm-10        12        881      50      7289      8170
 warm-11        10       1033      30      4933      5966
 warm-12        11        864      46      6939      7803
 warm-13        10        758      51      7724      8482
 warm-14         8        596      31      4518      5114
 warm-15         8        547      27      3796      4343
```

### (a) Lượt nguội ở 8.3c — **xác nhận**, gần đúng từng con số

| | Dự đoán ở 8.3c | Đo được |
|---|---:|---:|
| Token tiền tố | ~650 | **562** |
| Prefill nguội | ~33 s | **28 733 ms** |
| Tốc độ prefill | 19,99 tok/s (`pp512`) | **19,6 tok/s** |
| Lượt sau prefill | ~10–30 token | **8–12 token** |

`warm-0` tốn **4,1×** lượt đắt nhì. **Lệnh warm-up không còn là đề xuất — nó là điều
kiện để bật SLM.**

### (b) `total_ms_p95` trong manifest **báo thiếu** — lỗi off-by-one

`spike3_bench.py`:

```python
total_ms_p95 = total_ms[int(len(total_ms) * 0.95) - 1] if len(total_ms) >= 2 else None
```

Với `n=16`: `int(16 × 0.95) − 1 = 14` → lấy phần tử **thứ 15 trong 16**, tức
`8 681`. Giá trị lớn nhất `35 637` ở chỉ số 15 **bị loại khỏi p95**.

> Phép đo dựng ra để tìm lượt nguội lại giấu mất chính nó. **Khi đọc manifest của
> `spike-003`, luôn xem `records.jsonl` chứ đừng tin riêng `total_ms_p95`.** Chưa vá
> — vá thì mọi run cũ hết so được với run mới, nên chỉ ghi lại ở đây.

### (c) Phân bố **lưỡng đỉnh** — phát hiện quan trọng nhất

16 case tách hai nhóm rõ rệt theo số token sinh ra:

| Nhóm | `pred_n` | `total_ms` | Vượt trần 8 000 ms |
|---|---:|---:|---|
| **Sinh kế hoạch** (điều khiển xe) | 46–51 | 7 803 – 8 681 | **7 / 8** |
| Tán gẫu (chào, cảm ơn) | 27–31 | 4 343 – 5 966 | 0 / 8 |

**Không phải "một phần lượt bị chậm" — mà đúng nhóm lượt điều khiển xe gần như luôn
vượt trần**, còn tán gẫu thì luôn lọt. `p50 = 7 803` rơi đúng ranh giới giữa hai cụm
nên nó **che mất** chuyện này. Đây là lý do phải đọc bảng, không đọc mỗi p50.

### (d) RAM cao hơn tài liệu ghi

`server_peak_rss_mb = 3 352 MB`, không phải "~2 GB" như các mục trước ghi.

| | RAM |
|---|---:|
| llama-server (đỉnh) | 3 352 MB |
| 3 container backend | 1 208 MB |
| Next.js | ~150 MB |
| **Tổng** | **~4 710 MB** |

Máy có **4,8 GiB**, và swap đã ở 20% từ trước. **Bật SLM cùng backend và frontend là
chạm trần.** Model rơi vào swap thì 6,8 tok/s sẽ tệ đi nhiều — kiểu hỏng khó chẩn
đoán vì mọi thứ vẫn "chạy".

### (e) Kết luận

**3B trên máy này không phục vụ được lượt điều khiển trong trần 8 giây**, kể cả khi
cache đã ấm. Ba đường, không đường nào phải mua gì:

| Đường | Việc phải làm | Kết quả |
|---|---|---|
| **`SLM_ENABLED=false`** | không gì | Mất câu dẫn tự nhiên. Định tuyến vẫn 100% bằng luật. **An toàn nhất cho demo** |
| Bật 3B | warm-up + `SLM_TIMEOUT_S=12.0` + canh RAM | Lượt điều khiển ~8,5 s. Chậm nhưng chạy |
| **Đổi 0,5B** | thay model + kiểm chất lượng | p50 ~2,5 s, RAM 645 MB — giải luôn cả vấn đề RAM ở (d) |

> **Phép đo miễn phí quyết định tất cả, chưa làm:** đếm xem kịch bản demo có bao
> nhiêu câu **thật sự** chạm planner. Planner chỉ chạy khi
> `route_reason == "default_to_manual"` (`graph.py:254`). Sáu câu mẫu trong bench
> (`"Đặt điều hòa 22 độ"`…) **đều là câu router xử được**, nên trong thực tế chúng
> không bao giờ tới planner. Nếu demo chỉ có 2/30 câu chạm planner thì cả bảng trên
> gần như vô nghĩa.

### Cách chạy lại — dùng file, đừng dán lệnh dài

Lệnh dài bị **ngắt dòng khi dán** (vấp thật: `--prompt-file: command not found`), và
mã Python nhiều dòng bị **thêm 2 dấu cách** nên `IndentationError`. Cách chạy được:

`deploy/vps/run_bench.sh` (chép lên `~/run_bench.sh`), rồi trên VPS:

```bash
bash ~/run_bench.sh
```

Xem chi tiết từng case bằng `deploy/vps/show_records.py` (chép lên `~/show_records.py`):

```bash
~/benchvenv/bin/python ~/show_records.py
```

Dựng venv cho script — chỉ cần `httpx`, **không** cần torch:

```bash
sudo apt install -y python3-venv
```

```bash
python3 -m venv ~/benchvenv
```

```bash
~/benchvenv/bin/pip install httpx
```

llama-server chạy trong tmux, **không** qua container:

```bash
cd /opt/vivi/tools/llama/llama-b10358 && ./llama-server -m /opt/vivi/models/slm/qwen2.5-3b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8093 -c 2048 --cache-reuse 256 -ngl 0 -t 4
```

> `device_name` trong manifest là `"unknown"` — đúng thiết kế: `_device()` đọc
> `device-last.json` do `spike3_server.ps1` (PowerShell) ghi, mà trên Linux không có
> file đó. Docstring ghi rõ *"thiếu file thì ghi unknown chứ không đoán"*. Run vẫn
> hợp lệ; CPU thì đã có `--backend cpu` trong manifest.

## 8.3f. Xác minh prompt: `spike3_prompt.txt` **giống hệt** `SLM_UNION_PROMPT`

**Kiểm 2026-08-22**, vì warm-up chỉ có tác dụng nếu nạp đúng chuỗi backend thật sự gửi
— lệch một ký tự là cache trượt và warm-up thành vô dụng trong im lặng.

```
union chars: 1791    spike chars: 1791
identical  : True
union lines: 28      spike lines: 28
```

**Giống hệt.** Hai hệ quả:

1. Run `20260822T053907` **đo đúng đường planner production**, không phải một prompt
   gần giống. Mọi số ở 8.3e đứng vững.
2. Warm-up dùng thẳng `scripts/spike3_prompt.txt` được.

> **Cách so phải đúng:** lần đầu tôi dùng `unicode_escape` để lấy hằng chuỗi ra khỏi
> `slm.py`, nó phá ký tự tiếng Việt và báo **1 991 ký tự** — kết luận sai là "hai
> chuỗi khác nhau". Dùng `ast.literal_eval` mới ra đúng. Bài học: đừng dùng
> `unicode_escape` cho chuỗi có dấu.

**Chúng vẫn là hai file rời nên có thể trôi khỏi nhau.** Kiểm lại bằng lệnh này mỗi
khi `slm.py` đổi — **trên máy Windows, tại thư mục gốc repo**:

```powershell
python -c "import io,re,ast; u=ast.literal_eval(re.search(r'^SLM_UNION_PROMPT = ('.*?')
', io.open('src/agents/slm.py',encoding='utf-8').read(), re.S|re.M).group(1)); s=io.open('scripts/spike3_prompt.txt',encoding='utf-8').read(); print('KHOP' if u==s else 'DA TROI — phai dong bo lai')"
```

## 8.3g. Bật SLM — 5 việc, và cái gì **không** phải tải

**Không cần tải thêm gì.** Mọi thứ nặng đã nằm trên máy:

| Thứ | Vị trí |
|---|---|
| llama.cpp `b10358` | `/opt/vivi/tools/llama/llama-b10358/` |
| Model 3B (1,95 GiB) | `/opt/vivi/models/slm/qwen2.5-3b-instruct-q4_k_m.gguf` |
| `libgomp1` | đã cài (V-llama, mục 3) |
| `python3` cho warm-up | có sẵn trong Ubuntu 24.04, chỉ dùng stdlib |

Còn lại toàn là cấu hình.

### Thứ tự bắt buộc

| # | Việc | Vì sao không đảo được |
|---|---|---|
| 1 | `docker compose build backend` | Code trên đĩa đã có vai `classify` (PR #232), image thì chưa. Bật SLM trên image cũ là chạy `slm.py` cũ |
| 2 | Sửa mạng Docker | Không sửa thì mọi lượt SLM timeout, **trông hệt như "máy yếu"** |
| 3 | `vivi-slm.service` | Thay cho chạy tay trong tmux |
| 4 | **Warm-up call** | Không có thì lượt đầu tốn 35 637 ms và hỏng, **mỗi lần restart** |
| 5 | `SLM_ENABLED=true` + `SLM_TIMEOUT_S` | Bật cuối cùng, khi 1–4 đã đứng |

### Vì sao bước 2 tồn tại

`src/config.py:33` khai `slm_endpoint = "http://127.0.0.1:8093"`. Nhưng backend chạy
**trong container**, và ở đó `127.0.0.1` là **chính container**, không phải máy chủ.
llama-server thì là tiến trình của host. Backend sẽ không bao giờ chạm tới.

Cần ba thứ đi cùng nhau:

- llama-server nghe `0.0.0.0` thay vì `127.0.0.1` (để container gọi được);
- `extra_hosts: - "host.docker.internal:host-gateway"` trong override, và
  `SLM_ENDPOINT=http://host.docker.internal:8093` trong `.env`;
- một luật `ufw` cho dải mạng Docker, vì lưu lượng container → host vẫn đi qua chuỗi
  `INPUT` của ufw:

```bash
sudo ufw allow from 172.16.0.0/12 to any port 8093 proto tcp
```

> **Cổng 8093 không có xác thực nào.** Với `--host 0.0.0.0`, thứ duy nhất che nó khỏi
> Internet là ufw mặc định chặn incoming — và điều đó **chỉ đúng vì llama-server là
> tiến trình host, không phải cổng do Docker publish** (Docker ghi thẳng vào iptables
> trước ufw, xem mục 3). **Tuyệt đối không đưa 8093 qua Caddy và không publish nó
> trong compose.**

### Cảnh báo RAM — chỗ chật nhất của cả hệ

| | RAM |
|---|---:|
| llama-server (đỉnh đo được) | 3 352 MB |
| 3 container backend | 1 208 MB |
| Next.js | ~150 MB |
| **Tổng** | **~4 710 MB** |
| Máy có | 4 915 MB |
| **Dư** | **~205 MB (4%)** |

3 352 MB là **đỉnh** lúc nạp model; lúc chạy ổn định có thể thấp hơn. Đo thật trước
khi chốt — **trên VPS, đứng ở đâu cũng được, lúc llama-server đang chạy**:

```bash
free -h && ps -o rss=,comm= -C llama-server | awk '{printf "%s: %.0f MB
", $2, $1/1024}'
```

- RSS ổn định **2,2–2,5 GB** → còn biên, chạy được.
- Vẫn **3,3 GB** → phải dừng frontend lúc demo, hoặc nâng RAM.

Swap đã ở 20% **trước khi** bật SLM. Model rơi vào swap thì 6,8 tok/s tụt thảm hại
trong khi không có log lỗi nào — kiểu hỏng khó chẩn đoán nhất.

## 8.4. Nếu đo đạt — dựng service

```bash
sudo cp /tmp/vps/vivi-slm.service /etc/systemd/system/vivi-slm.service
```

> File nay dat `-t 4`. Neu so nhan vat ly khac 4 thi sua trong
> `deploy/vps/vivi-slm.service` **truoc khi scp**, hoac sua tai cho bang
> `sudo nano /etc/systemd/system/vivi-slm.service`.

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now vivi-slm
```

```bash
curl -s http://127.0.0.1:8093/health
```

```bash
nano /opt/vivi/.env
```

```
SLM_ENABLED=true
```

```bash
cd /opt/vivi && docker compose up -d --force-recreate backend
```

```bash
curl -s http://127.0.0.1:8000/healthz | python3 -m json.tool
```

`llm` phải là **`ready`**.

**Hai cờ không được đụng:**

- **`-c 2048`** ràng buộc RAM — toàn bộ số 2 109 MB đo ở đúng giá trị này.
- **`--host 127.0.0.1`** là chốt chặn duy nhất; cổng 8093 **không có xác thực**.

## 8.5. Từ lúc bật SLM, `npm run build` phải nhường chỗ

Còn trống ~1,0 GB, `next build` đỉnh 1 173 MB:

```bash
sudo systemctl stop vivi-slm
```

```bash
cd /opt/vivi/frontend && npm run build
```

```bash
sudo systemctl start vivi-slm
```

---

# 9. Vận hành

## Cập nhật mã nguồn — chọn đúng mức, đừng làm thừa

```bash
cd /opt/vivi && git pull
```

Rồi **chỉ chạy phần tương ứng với thứ đã đổi**:

| Đổi gì | Chạy gì | Mất bao lâu |
|---|---|---|
| Chỉ Python trong `src/` | `cd /opt/vivi && docker compose build backend && docker compose up -d --wait` | 1–3 phút (cache còn) |
| `requirements*.txt` hoặc `Dockerfile` | như trên, nhưng cache vỡ | **20–40 phút** |
| Chỉ code frontend | `cd /opt/vivi/frontend && npm run build && sudo systemctl restart vivi-frontend` | 2–5 phút |
| `frontend/package.json` đổi | thêm `npm ci` trước `npm run build` | +3 phút |
| **Bất kỳ `NEXT_PUBLIC_*`** | **bắt buộc `npm run build`** — `restart` một mình vô tác dụng | |
| `models/` hoặc `data/rag/` | `scp` lại như W6 | |

Biết đã đổi gì bằng cách đọc chính `git pull`, hoặc:

```bash
cd /opt/vivi && git diff --stat HEAD@{1} HEAD
```

**Nếu đã bật SLM**, nhường RAM trước khi build frontend (còn trống ~1,0 GB, `next
build` đỉnh 1 173 MB):

```bash
sudo systemctl stop vivi-slm
```

```bash
cd /opt/vivi/frontend && npm run build
```

```bash
sudo systemctl start vivi-slm
```

## Lùi phiên bản khi bản mới hỏng

Đây là thứ đường `git archive` **không** làm được, và là lý do chính chọn `git clone`:

```bash
cd /opt/vivi && git log --oneline -5
```

```bash
git checkout <sha-cũ>
```

Rồi build lại theo bảng trên. Quay lại nhánh:

```bash
git checkout develop
```

## Đổi nhánh

```bash
cd /opt/vivi && git fetch origin
```

Phải in ra một dòng trước khi đổi:

```bash
git show origin/develop:Dockerfile | grep requirements-voice
```

```bash
git checkout develop && git pull
```

Rồi build lại (đổi `Dockerfile` = cache vỡ, tính 20–40 phút).


## Sao lưu SQLite

```bash
cp /opt/vivi/data/app.db /opt/vivi/data/app.db.$(date +%F)
```

## Dọn cache build Docker

```bash
docker system df
```

```bash
docker builder prune -f
```

> Đừng chạy ngay trước ngày demo — lần build kế tiếp sẽ lâu hơn vì mất cache.

## Xem log

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

# 9b. Đổi máy chủ — sao lưu cái gì, dựng lại cái gì

Câu trả lời ngắn: **gần như không có gì bắt buộc phải sao lưu.** Máy này dựng lại
được từ máy Windows + git trong **~30 phút**.

## 9b.1. Nguồn thật của từng thứ nằm ở đâu

| Thứ | Nguồn thật | Máy mới lấy lại bằng |
|---|---|---|
| Mã nguồn | GitHub | `git clone` — 30 giây |
| `models/voice/` (89 MB) | **Máy Windows** | `scp` — 1–3 phút |
| `data/rag/` (2 MB) | **Máy Windows** | `scp` |
| Qwen 3B GGUF (2 GB) | **`C:\vivi-models`** | `scp` — 88 giây (đã đo) |
| Image Docker (2,6 GB) | — | `docker compose build` — 8,6 phút (đã đo) |
| llama.cpp | GitHub | `curl` — 16,5 MB |
| 4 file cấu hình | **`deploy/vps/` trong repo** | `scp` |

**Không thứ nào chỉ tồn tại trên VPS.** Đó là thiết kế, không phải may: `models/` và
`data/rag/` nằm ngoài git chính vì thế, và `deploy/vps/` sinh ra để cấu hình cũng
không mắc kẹt trên máy chủ.

## 9b.2. Ba thứ *có* đáng mang theo

```bash
cd /opt/vivi && tar -czf ~/vivi-state-$(date +%F).tar.gz .env config/mosquitto/passwd data/app.db
```

```bash
sudo tar -czf ~/caddy-$(date +%F).tar.gz -C /var/lib/caddy .
```

Kéo về máy Windows:

```powershell
scp vivi@103.146.23.41:~/vivi-state-*.tar.gz .
```

```powershell
scp vivi@103.146.23.41:~/caddy-*.tar.gz .
```

**1. `.env` + `config/mosquitto/passwd` — đi thành cặp.** Mật khẩu MQTT sinh ngẫu
nhiên nằm ở cả hai nơi; chép một cái mà quên cái kia thì broker từ chối backend và
`/healthz` báo `mqtt: down`. Sinh lại cũng chỉ là 6 lệnh ở V11, nên đây là tiện chứ
không bắt buộc.

**2. `data/app.db`** — user, session, approval, idempotency. Với một buổi demo thì
**gần như không đáng giữ**: hai user demo được seed lại từ mã nguồn lúc khởi động,
session hết hạn sau 24 h, approval dùng một lần.

**3. `/var/lib/caddy`** — xem 9b.3, đây mới là thứ thật sự đáng.

## 9b.3. Hạn mức Let's Encrypt — cái duy nhất có thể cắn bạn

Let's Encrypt giới hạn **5 chứng chỉ trùng lặp mỗi tuần** cho cùng một bộ tên miền.
Dựng lại máy vài lần trong một tuần với cùng tên miền là chạm trần, và khi đó **không
xin được chứng chỉ mới** cho tới hết tuần.

`/var/lib/caddy` giữ chứng chỉ đã cấp và khoá tài khoản ACME. Khôi phục nó thì Caddy
**dùng lại chứng chỉ cũ** thay vì đi xin cái mới:

```bash
sudo systemctl stop caddy
```

```bash
sudo tar -xzf ~/caddy-2026-08-22.tar.gz -C /var/lib/caddy
```

```bash
sudo chown -R caddy:caddy /var/lib/caddy
```

```bash
sudo systemctl start caddy
```

**Trỏ lại A record sang IP mới trước**, nếu không Caddy thấy tên miền không còn về
máy nó và vẫn cố xin lại.

## 9b.4. Thời gian dựng máy mới

| Giai đoạn | Thời gian |
|---|---:|
| V1–V7 (hệ, user, ufw, Docker, Node) | ~10 phút |
| Khoá SSH GitHub + `git clone` | ~2 phút |
| `scp` model + `deploy/vps` | ~3 phút |
| Khôi phục `.env` + `passwd` (thay cho V10–V11) | ~1 phút |
| `docker compose build` | **8,6 phút** |
| `npm ci` + `npm run build` | ~5 phút |
| Caddy + khôi phục cert | ~2 phút |
| **Tổng** | **~30 phút** |

## 9b.5. Thứ sẽ đáng giữ về sau — hiện chưa có

Chạy `scripts/spike3_bench.py` trên VPS thì nó ghi run vào
`eval/results/spike-003/<run-id>/`. **Đó là bằng chứng, không tái tạo được** — mỗi
run gắn với một máy tại một thời điểm. Chép về máy Windows và commit vào repo, đừng
để nó chết theo VPS.

Hiện mới chạy `llama-bench` (in ra màn hình, không ghi run), nên chưa có gì thuộc
loại này — kết quả 7,17 tok/s ở mục 8.3b vẫn là phép đo tại chỗ.

---

# 10. Bảng tra lỗi cho máy này

| # | Lỗi | Triệu chứng | Sửa ở |
|---|---|---|---|
| 1 | `chown -R 700` thay vì `chown -R vivi:vivi` | SSH vẫn hỏi mật khẩu, **không báo lý do** | 3.3 |
| 2 | `rsync ~/.ssh` khi root chưa có khoá | `authorized_keys` rỗng | 3.2 |
| 3 | Dán lệnh dài bị ngắt dòng | `syntax error near unexpected token` | 3.1 |
| 4 | Host key đổi sau `apt upgrade` | `REMOTE HOST IDENTIFICATION HAS CHANGED` | V1 |
| 5 | Build từ `develop` trần | Build xanh, `stt`/`tts`/`rag_index` = `down` | V9 |
| 6 | Quên `scp models/voice/` | Build chết ở `THIEU ARTIFACT VOICE` | W6 |
| 7 | Quên `scp data/rag/` | Câu sổ tay trả "không tìm thấy", container vẫn xanh | W6 |
| 8 | `MQTT_URL=...localhost...` | `/healthz` báo `mqtt: down` | V10 |
| 9 | `CORS_ORIGINS` sai một ký tự | **WS đóng `4403`, REST xanh** | V10 |
| 10 | Quên `chown 1883:1883` | `mqtt` restart vô hạn | V11 |
| 11 | Quên `!override` | Cổng 8000 vẫn mở ra Internet | V12 |
| 12 | `handle /api/*` | Nút đăng nhập 1 chạm chết, còn lại xanh | 7.5 |
| 13 | Quên một cờ `USE_MOCK_*` | Giao diện chạy **mock**, nhìn y như thật | V15 |
| 14 | Sửa `NEXT_PUBLIC_*` rồi chỉ `restart` | Không có gì thay đổi | 7.4 |

---

# 11. Giới hạn — deploy xong ≠ mở cho công chúng

**Cả sáu đều là việc code, không phải việc deploy:**

- **Một chiếc xe ảo dùng chung** — `vehicle_id` là hằng số, mọi người điều khiển cùng
  một chiếc xe.
- **Hai tài khoản demo hard-code** (`src/db.py:267`) — ai đọc source cũng đăng nhập
  được, và `/engineer` lộ trace của mọi lượt.
- **Khoá `threading.Lock` toàn cục trên STT/TTS** (`voice.py:97`, `:192`) — mỗi lúc
  **một người** nói được. Máy to hơn không gỡ được.
- **Không có rate limit** ở bất kỳ tầng nào.
- **Không mở rộng ngang được** — SQLite một kết nối; `InMemorySaver` mất lượt đang
  chờ duyệt khi restart.
- **License CC-BY-NC-ND của model STT** — image có nướng model vào, **đừng push lên
  registry công khai**.

---

# 12. Việc tiếp theo — trạng thái 2026-08-22

Backend xanh, đã đo `llama-bench`. **Chưa cài frontend, chưa có tên miền.**

## Miễn phí, làm trước mọi chuyện đổi máy

1. **Thêm lời gọi warm-up cho `vivi-slm.service`** (mục 8.3c) — lượt planner đầu tiên
   hiện tốn ~33 s prefill nên chắc chắn hỏng, và hỏng **hai lần** vì `graph.py` thử
   lại. Không cờ nào chữa được.
2. **Đếm tỉ lệ planner thật sự chạy** trong kịch bản demo — chỉ khi
   `route_reason == "default_to_manual"` (`graph.py:254`). Nếu chỉ ~2/30 câu thì toàn
   bộ câu hỏi hiệu năng SLM gần như vô nghĩa và không cần đổi gì cả.
3. **Thử model 0,5B** rồi kiểm chất lượng bằng đúng 30 câu đó. Quy đổi ~23 tok/s,
   p50 ~2,1 s, RAM 645 MB — rẻ hơn mọi phương án phần cứng.
4. **`./llama-bench -t 2,3,4 -r 3`** để thấy hình dạng đường cong ở đầu trên, trước
   khi trả tiền cho vCPU thứ 5–8.

## Cần vá mã trước khi chạy được

5. **`scripts/spike3_bench.py:32`** — `_server_rss_mb` gọi PowerShell đọc
   `PeakWorkingSet64`, không có `try/except`, nên ném `FileNotFoundError` trên Linux
   **sau khi đã đo xong**. Vá bằng cách đọc `VmHWM` từ `/proc/<pid>/status`. Chỉ khi
   có bản vá này mới đo được p50 so trực tiếp được với `5 329 ms` của máy dev.

## Còn lại của quy trình deploy

6. **Frontend (V15–V18)**: `cp deploy/vps/env.production.tunnel` + `env.runtime` →
   `npm ci` → `nice -n 10 npm run build` → systemd → `curl 127.0.0.1:3000` = 200.
7. **Kiểm bằng SSH tunnel** (mục 6) — micro thử được vì `http://localhost` là secure
   context, không cần tên miền.
8. **Tên miền → Caddy** (mục 7). Chưa mua tên miền.

## Chỉ khi 1–4 vẫn không đủ

9. Hỏi LANIT ba câu: nâng lên 8 vCPU tại chỗ được không; gói nào chạy trên
   Platinum/Skylake; snapshot khôi phục sang node khác được không. Cơ sở để đi tiếp
   nằm ở mục **8.3d**.
