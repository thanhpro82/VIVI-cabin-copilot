# VIVI trên VPS — sổ tay vận hành

Trạng thái hệ thống **hiện tại** (2026-08-22), viết theo kiểu tham khảo — không phải
nhật ký. Muốn xem quá trình dựng máy, lỗi đã vấp và cách sửa từng cái, đọc
[`deploy_vps_thuc_te_2026-08-21.md`](deploy_vps_thuc_te_2026-08-21.md). Muốn biết
phải chạy lệnh gì mỗi khi đẩy code mới lên GitHub, đọc
[`deploy_vps_cap_nhat_code.md`](deploy_vps_cap_nhat_code.md) — không lặp lại ở đây.

## 1. Địa chỉ

| | |
|---|---|
| Domain | **`https://c4-app-192.io.vn/`** |
| VPS | `103.146.23.41` (LANIT, `cloud2026082116.lanit.com.vn`) |
| SSH | `ssh vivi@103.146.23.41` — khoá, không mật khẩu |
| Mã nguồn trên máy | `/opt/vivi`, nhánh `develop` |

DNS: `c4-app-192.io.vn`, `www.c4-app-192.io.vn`, `vivi.c4-app-192.io.vn` đều trỏ về
`103.146.23.41`. Domain **trần** (không tiền tố) là địa chỉ chính thức — Caddy chỉ
cấp chứng chỉ cho tên đó, hai tên còn lại trỏ đúng IP nhưng không có Caddyfile phục
vụ riêng.

## 2. Máy

| | |
|---|---|
| CPU | Xeon E5-2696 v4 @ 2,20 GHz, Broadwell-EP 2016, AVX2 (không AVX-512) |
| vCPU | **5** — nâng từ 4 lên ngày 2026-08-22, xác nhận là nhân vật lý thật (không phải SMT) qua `llama-bench -t 4,5`: dự đoán 8,62 tok/s, đo 8,44 — sai số <2% |
| RAM | **~6,8 GiB** — nâng từ 4,8 GiB cùng ngày |
| GPU | Không — `lspci` chỉ ra card VGA giả lập QEMU, không CUDA/Vulkan |
| Swap | 4 GiB (đã có sẵn từ trước) |

## 3. Kiến trúc — một origin, Caddy phân luồng

```
                          ┌─────────────────────────┐
 Trình duyệt ──HTTPS──▶   │  Caddy :80/:443          │
                          │  c4-app-192.io.vn        │
                          └───────┬─────────┬────────┘
                     /api/v1/*    │         │  còn lại
                     /ws/*        │         │
                     /healthz     ▼         ▼
                          ┌──────────┐  ┌──────────┐
                          │ backend  │  │ frontend │
                          │ :8000    │  │ :3000    │
                          │ (Docker, │  │ (systemd,│
                          │ loopback)│  │ loopback)│
                          └────┬─────┘  └──────────┘
                               │
                   host.docker.internal:8093
                               │
                          ┌────▼─────┐
                          │llama-server│  (systemd, 0.0.0.0,
                          │  :8093    │   chỉ ufw che khỏi Internet)
                          └──────────┘
```

Ba container Docker khác (`mqtt`, `vehicle-simulator`) không lộ ra ngoài, chỉ nói
chuyện với `backend` qua mạng nội bộ Compose.

**Vì sao gom về một origin:** frontend gọi API bằng URL tuyệt đối
(`https://c4-app-192.io.vn/api/v1/...`), không phải đường dẫn tương đối — xem
`docs/deploy_vps_thuc_te_2026-08-21.md` mục 7b.3 nếu muốn đổi sang cách linh hoạt
hơn (chưa làm).

## 4. Dịch vụ và cách quản lý

> Mục này liệt kê **dịch vụ nào chạy bằng gì**. Lệnh cụ thể để restart / xem log /
> kiểm trạng thái nằm ở [`deploy_vps_lenh_nhanh.md`](deploy_vps_lenh_nhanh.md) — ở đó
> có tách rõ "restart để bật lại" với "restart để áp cấu hình mới", hai chuyện khác
> nhau và lẫn lộn chúng là nguyên nhân sự cố 2026-08-23.

| Dịch vụ | Chạy bằng | Cổng | Lệnh xem trạng thái |
|---|---|---|---|
| `caddy` | systemd | 80, 443 | `systemctl status caddy` |
| `vivi-frontend` | systemd | `127.0.0.1:3000` | `systemctl status vivi-frontend` |
| `vivi-slm` (llama-server) | systemd | `0.0.0.0:8093` | `systemctl status vivi-slm` |
| `backend` | Docker Compose | `127.0.0.1:8000` | `docker compose -f /opt/vivi/docker-compose.yml ps` |
| `mqtt` | Docker Compose | nội bộ | — |
| `vehicle-simulator` | Docker Compose | nội bộ | — |

Cả ba systemd service đều `enable`, cả ba container đều `restart: unless-stopped` —
**sống qua việc đóng terminal SSH và qua cả reboot của máy ảo**. Riêng
`vivi-slm.service` sau reboot cần lại ~30 giây warm-up trước khi lượt planner đầu
tiên nhanh trở lại.

## 5. File cấu hình — cái gì nằm ở đâu

Không cái nào trong nhóm này nằm trong git (trừ bản mẫu ở `deploy/vps/`, xem §7).

| File trên VPS | Chứa gì | Bản mẫu trong repo |
|---|---|---|
| `/opt/vivi/.env` | `CORS_ORIGINS`, `SLM_*`, `MQTT_*`, `OMP_NUM_THREADS` | `.env.example` |
| `/opt/vivi/docker-compose.override.yml` | Ép backend loopback-only + `extra_hosts` cho llama-server | **không có** — `.gitignore:65`; tạo tay ở bước V12 |
| `/opt/vivi/frontend/.env.production` | `NEXT_PUBLIC_*`, nướng vào JS lúc build | `deploy/vps/env.production.domain` |
| `/opt/vivi/frontend/.env.runtime` | `DEMO_DRIVER_EMAIL/PASSWORD` cho route `/api/auth/demo-driver` | `deploy/vps/env.runtime` |
| `/etc/caddy/Caddyfile` | Định tuyến domain | `deploy/vps/Caddyfile` |
| `/etc/systemd/system/vivi-slm.service` | Lệnh chạy llama-server + warm-up | `deploy/vps/vivi-slm.service` |
| `/etc/systemd/system/vivi-frontend.service` | Lệnh chạy `next start` | `deploy/vps/vivi-frontend.service` |
| `/opt/vivi/config/mosquitto/passwd` | Mật khẩu MQTT (sinh ngẫu nhiên, không tái tạo được) | — |

**Giá trị hiện tại trong `.env` đáng nhớ:**

```
CORS_ORIGINS=https://c4-app-192.io.vn
SLM_ENABLED=true
SLM_ENDPOINT=http://host.docker.internal:8093
SLM_TIMEOUT_S=20.0
OMP_NUM_THREADS=4
```

`OMP_NUM_THREADS=4` chưa hạ xuống 2 như khuyến nghị lý thuyết (STT/TTS là pha ngắn,
2 luồng đủ, nhường phần còn lại cho llama). Chưa gấp — chỉ đáng làm nếu đo thấy
tranh chấp CPU thật giữa hai pha.

## 6. SLM — cấu hình đang chạy

| | |
|---|---|
| Model | Qwen2.5-3B-Instruct, GGUF `q4_k_m` (1,95 GiB) |
| llama.cpp | build `b10358`, `/opt/vivi/tools/llama/llama-b10358/` |
| Tham số | `-c 2048 --cache-reuse 256 -ngl 0 -t 5` — có đề xuất nâng `-c` lên 8192, **chưa áp dụng**, xem mục bên dưới |
| Warm-up | `deploy/vps/slm_warmup.sh`, chạy qua `ExecStartPost`, nạp sẵn 562 token tiền tố (`SLM_UNION_PROMPT`) sau mỗi lần khởi động — không có bước này thì lượt đầu tốn ~35 s và hỏng |
| Hiệu năng đo được (2026-08-22, `spike3_bench.py`, cùng phương pháp máy dev) | Lượt sinh kế hoạch (điều khiển xe) **p50 ≈ 6,3–7 s** ở `-t 5`; lượt tán gẫu **~4,3–6 s** |
| Cổng 8093 | **Không xác thực** — chỉ `ufw` (chặn incoming mặc định, trừ dải Docker) che khỏi Internet. Tuyệt đối không đưa qua Caddy, không publish trong Compose |

`SLM_ENABLED=true` bật vai **planner** (`QwenPlanner`). Câu dẫn tự nhiên vẫn tắt —
`cau_dan_dung_slm` mặc định `False` trong `src/config.py`, **cố ý giữ nguyên**: câu
dẫn ghép từ câu hỏi nhanh hơn (0 ms so với ~2,3 s trên CPU) và không có rủi ro bịa.

### Bốn vai cùng chia sẻ MỘT llama-server — tranh chấp có thật (phát hiện 2026-08-22)

Sau khi pull `0f0a31f`, `src/agents/slm.py` có thêm vai `QwenChitchat` (SP-2), cộng
`slm_classify` đã có từ trước (PR #232/#242). Tổng cộng llama-server ở cổng 8093
phục vụ:

| Vai | Timeout | Khi nào gọi |
|---|---:|---|
| `QwenPlanner` | 20,0 s (`SLM_TIMEOUT_S`) | Router không khớp luật nào |
| `slm_classify` | **2,0 s** | Trước khi vào RAG, phân loại có cần tra sổ tay không |
| `QwenChitchat` | 4,0 s | Câu tán gẫu (chào hỏi, cảm xúc, hỏi đường) |
| `QwenLeadIn` | — | **Tắt** (`cau_dan_dung_slm=False`) |

> **Đính chính 2026-08-23** — đoạn dưới đây trước ghi *"llama-server mặc định xử lý
> tuần tự, `--parallel` chưa được đặt"*. **Sai cơ chế.** Journal khai
> `n_slots = 4, n_ctx_slot = 2048, kv_unified = 'true'`, và `/slots` đọc được **4
> rãnh**. Bốn vai chạy **song song** chứ không xếp hàng — nhưng dùng chung **một bể
> KV**, nên chúng đá tiền tố của nhau. Triệu chứng (timeout) đúng, chẩn đoán cũ sai;
> cách chữa vì thế cũng khác. Xem PR #257 và run `20260823T120422`.

Nếu một lượt `planner` (7–8 s) đang chạy, một request `slm_classify` tới cùng lúc
**vẫn có thể vượt quá 2 giây** — không phải vì phải chờ, mà vì bốn rãnh tranh 5 luồng
CPU và tranh chỗ trong bể KV. Log thật đã quan sát được:

```
WARNING:src.agents.graph:slm_classify hỏng, rơi về manual: timed out
```

**Không phải lỗi** — đây là fail-safe hoạt động đúng thiết kế
(`config.py` comment: *"chờ lâu hơn nghĩa là server đang ốm, fail-safe về manual rẻ
hơn bắt tài xế đợi"*). Nhưng dưới tải dồn dập (nhiều câu hỏi liên tiếp), tỉ lệ rơi về
`manual` sẽ tăng — không phải vì máy yếu mà vì bốn vai đang tranh nhau một bể KV và
năm luồng CPU.
Cách chữa **không** phải thêm `--parallel` (đã có 4 rãnh sẵn) mà là nới bể KV cho đủ
chỗ chứa tiền tố của cả bốn — xem mục ngay dưới.

### Nâng `-c` 2048 → 8192 — CHƯA ÁP DỤNG, quy trình chuẩn bị sẵn

> **Máy đang chạy `-c 2048`.** Thay đổi này từng nằm trong PR #257 nhưng đã được
> **tách ra** ngày 2026-08-25, vì **không một phép đo nào của PR đó chạy ở 8192**: cả
> bốn run `slm-dong-thoi` lẫn hai run `luot-that-dong-thoi` đều ở `-c 2048`. Toàn bộ
> cải thiện đo được đến từ `asyncio.to_thread`, không phải từ `-c`.
>
> Mục này giữ lại **nguyên vẹn** vì quy trình vẫn đúng và ba ô RAM còn trống vẫn là
> việc phải làm. Đọc nó như một bản chuẩn bị, không phải một bản mô tả hiện trạng.

**Vì sao.** Hai tiền tố thật đã chiếm 1 037 cell (`classify` 479 + `planner` 558)
trong bể 2 048 dùng chung. Cộng phần đang sinh của từng chuỗi là hết chỗ, nên mỗi mức
tải có đúng một lượt phải nạp nguội lại từ đầu, tốn 20–25 s, và nó rơi trúng một
người dùng thật (run `20260823T120422`).

**`deploy.sh` KHÔNG chép file service** (`deploy/vps/deploy.sh:6` nói rõ nó không làm
thay `.env`, `Caddyfile`, `vivi-slm.service`, `vivi-frontend.service`). Nên sau khi
`git pull` về bản có `-c 8192`, llama-server **vẫn chạy `-c 2048`** cho tới khi làm
tay bốn lệnh sau, trên VPS:

```bash
free -m
```

```bash
sudo cp /opt/vivi/deploy/vps/vivi-slm.service /etc/systemd/system/vivi-slm.service
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart vivi-slm
```

```bash
free -m
```

Restart làm mất tiền tố đang nóng: lượt đầu sau đó tốn ~35 s cho tới khi
`ExecStartPost` (`slm_warmup.sh`) nạp xong. **Đừng làm trong lúc có người đang dùng.**

**Xác nhận RAM bằng số thật, đừng dùng số ước.** Ghi chú trong `vivi-slm.service`
đoán *"~300 MB, còn trống 3,3 GB"* — đó là **ước tính chưa đo lại**. Số thật do
llama-server tự in:

```bash
sudo journalctl -u vivi-slm -b --no-pager | grep -iE "KV self size|n_ctx|n_slots|kv_unified"
```

Chép hai lần `free -m` và dòng `KV self size` vào bảng dưới. **Ba ô này còn trống —
chưa đo trên VPS:**

| | `-c 2048` | `-c 8192` |
|---|---|---|
| `KV self size` (llama-server tự in) | chưa đo | chưa đo |
| RAM trống sau khởi động (`free -m`, cột `available`) | chưa đo | chưa đo |

**Hoàn tác.** Giá trị gốc là **`-c 2048`**, xác nhận còn sống trên
`/etc/systemd/system/vivi-slm.service:20` ngày 2026-08-25 trước khi đổi:

```bash
sudo sed -i 's/-c 8192/-c 2048/' /etc/systemd/system/vivi-slm.service
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart vivi-slm
```

```bash
grep -n -- "-c " /etc/systemd/system/vivi-slm.service
```

> Lệnh `sed` trên chỉ sửa **bản đang chạy**. Bản mẫu trong repo vẫn là `-c 8192`, nên
> lần `cp` sau sẽ đưa 8192 trở lại. Muốn hoàn tác lâu dài thì phải revert cả commit
> trong repo — nguyên tắc đồng bộ hai chiều ở §7.

**Nâng `-c` một mình chưa phải là xong** — và đây chính là lý do nó bị tách khỏi
PR #257. PM/PO review (2026-08-24) đã chốt:
cột `nạp nguội = 0` không đủ làm mức đạt. Ngay ở N=3, `classify` vẫn có 5/9 lượt vượt
ngưỡng 3,5 s; luồng trộn có 3/9 lượt chạm trần 30 s. Còn thiếu: mức sức chứa công
khai, cơ chế xếp hàng/từ chối nhanh, và một lần đo end-to-end **có cả STT/TTS**.

## 7. Cập nhật bản mẫu cấu hình khi máy thay đổi

Bản mẫu trong `deploy/vps/` phải khớp với file thật đang chạy trên VPS — nếu sửa tay
trực tiếp trên máy (ví dụ đổi `-t`), nhớ đồng bộ ngược lại bản mẫu trong repo, nếu
không lần dựng máy sau sẽ cài nhầm cấu hình cũ. Đã xảy ra một lần: `-t` sửa bằng
`sed` thẳng trên `/etc/systemd/system/vivi-slm.service` lúc nâng vCPU, quên đồng bộ
ngược `deploy/vps/vivi-slm.service` — phát hiện và sửa cùng ngày.

## 7b. Máy chủ tự sinh file mà nhánh đích có bản tracked — bẫy vấp 4 lần trong ngày 25/08

Triệu chứng luôn giống nhau, ở `deploy.sh` bước 2:

```
error: The following untracked working tree files would be overwritten by ...
```

Nguyên nhân: một thứ **sinh ra trên máy chủ** (thư mục run của phép đo, script `git show`
ra để chạy tạm) sau đó được **commit ở máy dev** vào đúng đường dẫn ấy. Git từ chối ghi đè
file untracked — đúng và nên thế, vì nó không biết bản trên máy chủ có quý không.

Cách xử, ba dòng, an toàn vì bản trong git chính là bản đã `scp` từ máy chủ lên:

```bash
mkdir -p ~/vps-untracked-$(date +%Y%m%d)
```

```bash
mv <đường-dẫn-git-báo> ~/vps-untracked-$(date +%Y%m%d)/
```

```bash
DEPLOY_REF=<nhánh> /opt/vivi/deploy/vps/deploy.sh
```

Xong thì đối chiếu `diff -r --strip-trailing-cr` giữa bản sao lưu và bản git; không in gì
là đúng.

**Cách không vấp lại:** đừng để máy chủ ghi vào cây git.
`scripts/do_luot_that_dong_thoi.py` có `--out-dir`; trên VPS luôn chạy với
`--out-dir ~/vivi-runs` rồi `scp` về máy dev mà commit. Cùng nguyên tắc cho mọi script đo
sau này.

**Một bẫy anh em của nó:** `chmod +x` trên file đã tracked cũng làm `deploy.sh` dừng, vì
Git trên Linux coi bit quyền là thay đổi nội dung. Trên máy chủ đặt một lần:

```bash
git -C /opt/vivi config core.fileMode false
```

File vẫn executable trên đĩa; `git checkout` vẫn áp mode từ index. Chỉ tắt việc git *phát
hiện* thay đổi bit.

## 8. Kiểm tra sức khoẻ toàn hệ thống

```bash
curl -s https://c4-app-192.io.vn/healthz | python3 -m json.tool
```

Mọi thành phần phải `ready`, `llm.status` phải `ready` (không phải `disabled`).

```bash
docker compose -f /opt/vivi/docker-compose.yml ps
```

Ba container `Up`/`healthy`.

```bash
systemctl is-active caddy vivi-frontend vivi-slm
```

Cả ba `active`.

**Phép thử thật, không qua tunnel:** mở `https://c4-app-192.io.vn/` từ điện thoại,
tắt WiFi (dùng 4G) — đăng nhập, một lệnh điều khiển, một câu buộc rơi vào planner,
bấm micro nói và nghe phản hồi.

## 8b. Ai có quyền vào máy

| Tài khoản | Quyền | Vào bằng |
|---|---|---|
| `vivi` | `docker`, `sudo` — toàn quyền | Khoá SSH của Sơn |
| `thanh` | `docker`, `sudo` — toàn quyền (2026-08-22) | Khoá SSH riêng của Thành |

Cả hai tài khoản đọc được `/opt/vivi/.env` (mật khẩu MQTT thật) và chạy được Docker
— chạy Docker tương đương root, vì mount được toàn bộ ổ đĩa qua container. **Không
đặt mật khẩu cho tài khoản mới** (`adduser --disabled-password`) — chỉ vào được bằng
khoá SSH đã đăng ký trong `authorized_keys` của chính tài khoản đó.

Thu hồi quyền một tài khoản:

```bash
sudo deluser --remove-home <tên>
```

## 9. Giới hạn đã biết — không chặn việc mở link, chỉ cần biết trước

| Giới hạn | Vì sao | Ảnh hưởng |
|---|---|---|
| Một xe ảo dùng chung | `vehicle_id` là hằng số, một tiến trình simulator | Nhiều người cùng lúc thấy trạng thái xe nhảy theo nhau |
| Hai tài khoản demo hard-code | `DEMO_USERS` trong `src/services/auth.py` | Ai đăng nhập cũng thành `usr_driver_01`; `/engineer` lộ trace mọi lượt của mọi người |
| Khoá toàn cục STT/TTS | `threading.Lock()` + `num_threads=1` trong `src/services/voice.py` | Mỗi lúc một người nói được; người sau xếp hàng, giao diện không báo đang chờ |
| Không rate limit | — | Không giới hạn số lượt/IP ở tầng nào |
| SQLite một kết nối, `InMemorySaver` | — | Chưa từng chạy nhiều worker; restart backend làm mất mọi lượt hội thoại đang dở (approval, checkpoint LangGraph) |

`/ws/ivi` **không** còn là giới hạn — uvicorn ping mỗi 20 s, client tự reconnect kèm
replay cursor, đã xác nhận đủ cả hai đầu ngày 2026-08-22.

## 10. Việc chưa làm — biết để không tưởng nhầm là xong

- Chưa hạ `OMP_NUM_THREADS` xuống 2 (§5).
- Chưa dọn `frontend/src/lib/services/*/real.ts` sang đường dẫn tương đối (mục 7b.3
  của nhật ký) — nếu đổi domain lần nữa vẫn phải build lại frontend theo cách thủ
  công ở `deploy_vps_cap_nhat_code.md` §3/§6.
- Chưa sửa 5 lỗ hổng ở §9.
- Chưa đo RAM thật sau khi nâng `-c` lên 8192 — bảng ở §6 còn ba ô trống.
- Chưa đo `spike3_bench.py` sau khi nâng lên 5 vCPU — số p50/p95 ở §6 là suy từ mô
  hình bão hoà băng thông, không phải đo trực tiếp bằng script đó ở cấu hình mới.
