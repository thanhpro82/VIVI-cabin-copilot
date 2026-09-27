# VIVI Cabin Copilot — Hướng dẫn chạy hệ thống

**Runbook chính thức của nhóm P-192.** Thay thế `huong_dan_chay_nhanh.md` và `local_setup.md`.

> **Trạng thái: Chạy được trên PC.** Kiểm chứng ngày **2026-08-15** trên `develop` (`7cca412`),
> Windows 11 / PowerShell 5.1 / Docker 28.1.1. Mọi lệnh, con số và thông báo lỗi ở đây đều lấy từ
> một lần dựng máy sạch có thật. Chỗ nào chưa kiểm được thì ghi rõ là chưa.

**Đọc phần nào:**

| Bạn là | Đọc |
|---|---|
| Máy đã dựng rồi, chỉ muốn chạy | **Phần I** (1 trang) |
| Máy mới, lần đầu dựng | **Phần II** |
| Cần chứng minh hệ thống chạy đúng | **Phần III** |
| Muốn gọi bằng giọng "Hey Vi Vi" | **§2.8** |
| Muốn bật LLM | **Phần IV** |
| Đang gặp lỗi | **Phần V** |
| Cần biết cái gì đã/chưa chứng minh được | **Phần VI** |
| Sắp demo trước khán giả | [`demo_runbook.md`](demo_runbook.md) — kịch bản S0→S3, ranh giới không được hứa. Nó **không** lặp lại phần dựng máy: mọi bước cài đặt và khởi động vẫn nằm ở tài liệu này |

---

# PHẦN I — CHẠY NHANH

Dành cho máy **đã dựng xong** (đã có `.env`, index RAG, model giọng nói).

Mở **3 cửa sổ PowerShell**, cửa sổ nào cũng `cd` vào repo trước:

```powershell
# ---- Cửa sổ 1: broker MQTT
docker compose up -d --wait mqtt

# ---- Cửa sổ 2: xe mô phỏng  (để mở, đây là chỗ gõ lệnh tốc độ)
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m src.vehicle_sim

# ---- Cửa sổ 3: backend
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m src.serve

# ---- Cửa sổ 4 (nếu cần giao diện)
cd frontend; npm run dev
```

Kiểm còn sống: `curl.exe -s http://localhost:8000/healthz` → `"status":"ready"`.
Mở <http://localhost:3000/login>, bấm **"Bắt đầu lái"**.

**Bốn cái sai kinh điển — nhớ đúng bốn cái này là hết 90% sự cố:**

| ✗ Đừng | ✓ Làm | Vì sao |
|---|---|---|
| `uvicorn src.main:app` | `python -m src.serve` | uvicorn chọn ProactorEventLoop → **mọi kết nối MQTT chết** |
| `docker compose up -d` (trống) | `docker compose up -d --wait mqtt` | Lệnh trống bật thêm xe ảo thứ hai, hai cái đá nhau khỏi broker |
| Quên `$env:PYTHONIOENCODING` | Đặt ở **mọi** cửa sổ | Console cp1252 làm mọi CLI in tiếng Việt chết |
| Chạy test với `MQTT_ENABLED=true` | `$env:MQTT_ENABLED="false"` | Mỗi `TestClient(app)` chờ broker 10 giây |

**Tài khoản demo** (nguồn: `DEMO_USERS` trong `src/db.py`):

| Vai | Email | Mật khẩu |
|---|---|---|
| Tài xế | `driver.demo@example.com` | `DemoDriver123!` |
| Kỹ sư | `engineer.demo@example.com` | `DemoEngineer123!` |

**Lệnh xe mô phỏng** (gõ vào cửa sổ 2): `speed 45` · `gear P` · `stop` · `state` · `help`.
Tốc độ chỉ do **xe tự báo lên**, nên không có lệnh MQTT nào của hợp đồng xe đặt được nó.
Từ ADR-024 có thêm một đường thứ hai: kênh harness `v1/sim/` — vẫn là xe tự đặt tốc độ của
chính nó, chỉ khác là được nhắn từ ngoài. Xem §3.3.

**Dừng:** `Ctrl+C` từng cửa sổ, rồi `docker compose down`.

---

# PHẦN II — DỰNG MÁY LẦN ĐẦU

## 2.1 Điều kiện tiên quyết

| Thứ | Yêu cầu |
|---|---|
| Python | **3.11.9** — bản duy nhất repo được kiểm chứng, CI pin đúng nó |
| Docker Desktop | Đang chạy |
| Node.js | Kèm npm |
| PowerShell | 5.1 là đủ |

> **Chỉ dựng đúng một venv.** `.venv311` đã bị xoá từ 2026-08-13; `.venv` chính là bản 3.11.9.
> Đừng tạo venv thứ hai: một venv 3.13 song song từng để lọt `asyncio.run(..., loop_factory=...)`
> (API 3.12+) vào `src/vehicle_sim/`, chết trên 3.11 và chặn cả một tầng test nhiều ngày.

### Thứ repo **không** chứa — clone xong chưa chạy được

| Thứ | Vì sao | Lấy ở đâu |
|---|---|---|
| Corpus sổ tay VF9 (~157 MB) | Có bản quyền | **Xin trong nhóm**, giải nén vào `VF9_2026_vi/` |
| Chỉ mục RAG | Sinh từ corpus | §2.5 |
| Model STT/TTS (~92 MB) | License riêng | §2.6 |
| `.env`, `frontend/.env.local`, `config/mosquitto/passwd` | Cấu hình/bí mật cục bộ | §2.3, §2.4, §2.7 |

> **Worktree không dùng chung được thứ gì ở trên.** `git worktree` chỉ chia sẻ lịch sử git;
> mọi thứ trong `.gitignore` — `models/voice/` (150 MB), `data/rag/`, `VF9_2026_vi/`,
> `frontend/node_modules/`, `.env` — là **của riêng từng thư mục**. Một worktree mới luôn bắt đầu
> trống, nên `/healthz` ở đó sẽ báo `stt`/`tts`/`rag_index` = `down` dù thư mục chính chạy tốt.
> Chép sang hoặc chạy hẳn ở thư mục đã dựng.

Thiếu corpus → mọi câu hỏi sổ tay trả lời rỗng. Thiếu model giọng nói → luồng nói hỏng, **luồng
gõ chữ vẫn chạy đủ**.

## 2.2 Python và thư viện

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -V                                      # phải in Python 3.11.9
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"            # sherpa-onnx + piper
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt  # kéo torch ~2 GB
```

## 2.3 Tệp `.env`

```powershell
Copy-Item .env.example .env
```

Mặc định đã đủ chạy. Bốn biến cần biết:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `MQTT_ENABLED` | `true` | Chạy test thì **phải** đặt `false` |
| `SLM_ENABLED` | `false` | **Đúng thiết kế** — router là luật tất định. Muốn bật xem **Phần IV** |
| `MQTT_HOST_PORT` / `MQTT_URL` | `1883` | Đổi sang `1884` nếu 1883 bị chiếm — xem §5.2 |
| `DATABASE_URL` | `sqlite:///./data/app.db` | Phải là SQLite, không phải postgres |

### Bốn cờ model — bật cái nào để được gì

Bốn vai dùng model, **cả bốn tắt mặc định**. Nghĩa là một checkout sạch trả lời 100%
bằng luật và **không gọi model lần nào** — đó là hợp đồng P0, không phải sự rụt rè.

| Cờ | Vai | Cần gì | Bật thì được gì |
|---|---|---|---|
| `SLM_ENABLED` | `QwenPlanner` — đề xuất lệnh cho câu luật không hiểu | llama-server + `qwen2.5-3b-instruct-q4_k_m` | Câu lạ có cơ hội thành lệnh (vẫn phải qua HITL — ADR-021) |
| `CAU_DAN_DUNG_SLM` | `QwenLeadIn` — viết câu dẫn nhánh sổ tay | như trên | Câu dẫn tự nhiên hơn. **Đo được: tốn 2.316 ms = 64% ngân sách một lượt** — đó là lý do nó tắt |
| `TOM_TAT_ENABLED` | `QwenTomTat` — nén câu nói sổ tay | llama-server + `Qwen3-4B-Instruct-2507-Q4_K_M` | Câu nói ngắn hơn, chở được nhiều bước hơn trong cùng trần. 7 cổng thuật toán chặn model bịa; hỏng cổng thì rơi về nguyên văn |
| `CHON_CAU_THAC_ENABLED` | `ThacChonCau` — cross-encoder chọn câu | `models/reranker/bge-reranker-v2-m3` (~2,2 GB, ngoài git) | **Đừng bật.** PR #179 đã đóng vì đo được luật **64% / 0 ms** thắng thác **54% / 981 ms**. Mã còn lại chờ gỡ |

> ⚠️ **`SLM_ENDPOINT` và `TOM_TAT_ENDPOINT` cùng trỏ `127.0.0.1:8093` nhưng cần HAI model
> khác nhau.** Bật cả `SLM_ENABLED` lẫn `TOM_TAT_ENABLED` thì vai nào nạp sau thắng, vai
> kia chạy nhầm model **trong im lặng** — triệu chứng là câu trả lời nhại lại ví dụ
> few-shot trong prompt. Muốn cả hai thì chạy hai `llama-server` và đổi một trong hai
> biến sang cổng khác.

**Nhánh bước** (câu hỏi *"thế nào / làm sao / bằng cách nào / cách…"* trả về các bước
thay vì câu mô tả) **không có cờ** — nó là luật thuần, 0 ms, luôn bật. Xem
`chon_buoc_thao_tac` trong `src/agents/nodes/speech_policy.py`.

## 2.4 Broker MQTT

```powershell
.\scripts\bootstrap_mqtt_secrets.ps1     # chạy MỘT lần
```

Script in ra 4 dòng — **chép `MQTT_BACKEND_PASSWORD` và `MQTT_SIMULATOR_PASSWORD` vào `.env`**.
File `config/mosquitto/passwd` sinh ra **không bao giờ được commit**.

```powershell
docker compose up -d --wait mqtt
```

Kỳ vọng kết thúc bằng `Container ... Healthy`.

## 2.5 Chỉ mục RAG

Cần corpus trong `VF9_2026_vi/` trước.

```powershell
.\scripts\prepare_vf9_index.ps1
```

Verify checksum corpus → chuyển sang `data/manuals/` → ingest → in bảng chất lượng. Vài phút;
lần đầu nạp model embedding E5 thêm ~30 giây.

**Kỳ vọng (đo thật 2026-08-15):**

```
documents : 58      chunks : 482      vectors : 536
page_resolved_rate : 1.0   (gate >= 95%)
worst_section_rate : 1.0   (gate >= 80%)
edition : VF9_23-25_VN_VI_2.4 [New UI]        OK
```

Kiểm lại index bất cứ lúc nào:

```powershell
.\.venv\Scripts\python.exe -m src.rag.cli verify
.\.venv\Scripts\python.exe -m src.rag.cli query "áp suất lốp khi lốp nguội"
```

> Cảnh báo `Token indices sequence length is longer than ... (613 > 512)` là **bình thường**.
> Nếu nó làm script *dừng*, xem §5.1 — lỗi nằm ở cách bạn gọi script.

> `src.rag.cli eval` hiện trả **FAIL** với `hallucination 5.0%` (ngưỡng `< 5%`) do đúng một ca âm
> tính RAG-209. Lỗi **có sẵn trong repo**, không phải do máy bạn.

## 2.6 Model giọng nói (bỏ qua được nếu chỉ test gõ chữ)

**STT — có script:**

```powershell
.\.venv\Scripts\python.exe -m pip install "huggingface_hub[cli]"
.\scripts\setup_voice_models.ps1
```

Tải Zipformer-30M-RNNT-6000h (license `cc-by-nc-nd-4.0` — phi thương mại, không phái sinh; hợp
với đồ án học thuật), ghi kèm `.sha256` + `.metadata.json`. Cần mạng lúc setup, **không** lúc chạy.

**TTS — phải tải tay** (script chỉ in hướng dẫn):

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\hf.exe download rhasspy/piper-voices `
  --revision 3d796cc2f2c884b3517c527507e084f7bb245aea `
  --include "vi/vi_VN/vais1000/medium/*" --local-dir .\models\voice\_piper_tmp

$src = ".\models\voice\_piper_tmp\vi\vi_VN\vais1000\medium"
Copy-Item "$src\vi_VN-vais1000-medium.onnx"      .\models\voice\vi_VN-piper.onnx
Copy-Item "$src\vi_VN-vais1000-medium.onnx.json" .\models\voice\vi_VN-piper.onnx.json
Remove-Item -Recurse -Force .\models\voice\_piper_tmp
```

**Tên file phải đúng `vi_VN-piper.onnx`** cho khớp `Settings.tts_model_path`.
SHA256 đúng: `ec7c89e2c85f4d1edc24b6120c18aaf1bda614f06b511567eb9c7c0de15e2dab`.

> Dùng `hf.exe`, **không** `huggingface-cli.exe`: bản cũ in cảnh báo deprecation có emoji, console
> cp1252 crash `UnicodeEncodeError` giữa chừng — lệnh thoát code 0 nhưng **không tải được gì**.

Mic chỉ chạy trên **`localhost` hoặc HTTPS** — `getUserMedia` bị chặn trên HTTP thường.

## 2.7 Giao diện

```powershell
cd frontend
npm install
```

Mặc định giao diện chạy **mock, không nối backend**. Để nối thật, tạo `frontend/.env.local`:

```ini
NEXT_PUBLIC_USE_MOCK_SESSION=false
NEXT_PUBLIC_USE_MOCK_TURN=false
NEXT_PUBLIC_USE_MOCK_ENGINEER=false
NEXT_PUBLIC_USE_MOCK_ROUTINES=false
NEXT_PUBLIC_USE_MOCK_PLACES=false

NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_IVI_URL=ws://localhost:8000/ws/ivi
NEXT_PUBLIC_WS_ENGINEER_URL=ws://localhost:8000/ws/engineer

# Gọi bằng giọng "Hey Vi Vi" — xem §2.8. Thiếu dòng này là TẮT, im lặng.
NEXT_PUBLIC_WAKE_WORD_ENABLED=true

# KHÔNG thêm prefix NEXT_PUBLIC_ cho hai dòng dưới: chúng chỉ được đọc trong
# Route Handler server-side. Thêm prefix là Next.js nhét mật khẩu vào bundle
# gửi thẳng cho trình duyệt (đã bị bắt ở review PR #11).
DEMO_DRIVER_EMAIL=driver.demo@example.com
DEMO_DRIVER_PASSWORD=DemoDriver123!
```

**Cả năm cờ `USE_MOCK` phải cùng `false`** — thiếu một cái là còn một phần hệ thống chạy giả.
Sửa xong phải **tắt `npm run dev` rồi chạy lại**; khi nạp đúng, log Next.js in
`Environments: .env.local`.

> **Ảnh chụp ở chế độ mock không chứng minh gì về backend.** Mock còn lệch contract: dùng tên tool
> không canonical (`control_lights`, `control_trunk`) và kẹp mức quạt `0..5` trong khi backend chỉ
> nhận `0..3`.

---

## 2.8 Gọi bằng giọng "Hey Vi Vi" (tuỳ chọn)

**Trạng thái: chạy được, nhưng dưới cổng nghiệm thu.** recall **0,696** trên tập held-out, dưới
cổng 0,95 nhóm tự đặt (run `eval/results/wake-word/2026-08-21T14-12Z-v8-sequence-head/`). Vẫn
được đưa vào bản demo BTC theo quyết định PM/PO, với chạm-mic là đường chính.

### Bật

Một dòng trong `frontend/.env.local`:

```ini
NEXT_PUBLIC_WAKE_WORD_ENABLED=true
```

**Thiếu dòng này là tắt, và tắt trong im lặng.** `DriverShellProvider.tsx` đọc
`=== "true"`, nên không có cờ thì bộ dò không bao giờ khởi động: không lỗi, không cảnh báo,
không log. Dấu hiệu duy nhất là màn hình chính hiện `Chạm mic để ra lệnh` thay vì
`Nói "Hey Vi Vi" hoặc chạm mic`. Sửa `.env.local` xong phải **tắt `npm run dev` rồi chạy lại**.

### Ba file model phải có đủ

`frontend/public/models/wake-word/` cần **cả ba** mới chạy:

| File | Nguồn |
|---|---|
| `melspectrogram.onnx` + `embedding_model.onnx` | vendored, **có trong git** |
| `model.onnx` + `manifest.json` + `LICENSE.txt` | **có trong git** từ PR #238 (1,2 MB) |

Khác với `models/voice/` và `data/rag/`, bộ này **đi theo git**, nên clone về là có. Nếu thiếu,
`onnxWakeWordDetector` băm lại file và từ chối nạp khi `sha256` không khớp manifest — bộ dò báo
không khả dụng và giao diện tự quay về câu chạm-mic.

### Sau khi pull PR #238: phải chạy lại `npm install`

`#238` thêm phụ thuộc `onnxruntime-web`. `node_modules` cũ không có nó, và `npm run dev` sẽ chết
ở bước `prepare:ort` với một lỗi **không hề gợi ý nguyên nhân**:

```
Error: ENOENT: no such file or directory, copyfile
  '...node_modules\onnxruntime-web\dist\ort-wasm-simd-threaded.wasm'
```

Chữa: `cd frontend; npm install`.

### Cách dùng

Nói **"Hey Vi Vi"** → nghe một tiếng bíp ngắn → nói lệnh. Bộ dò tạm ngừng nghe trong lúc VIVI
đọc trả lời, để nó không nghe chính giọng mình qua loa rồi tự đánh thức.

Nút mic tay vẫn chạy song song và **không bị ảnh hưởng**: bộ dò dùng micro riêng, `openVoice`
tắt nó trước khi thu tay và bật lại sau khi overlay đóng.

## 2.9 Nhiều người cùng lái — pool xe ảo

**Mặc định repo là MỘT xe, và một xe nghĩa là KHÔNG cấp phát** — mọi phiên dùng chung
chiếc xe đó, y hệt hành vi trước khi có pool. Phần này chỉ cần khi anh muốn nhiều người
lái cùng lúc, mỗi người một chiếc xe riêng.

### Vì sao cần

Với một chiếc xe dùng chung, cơ chế chống ghi đè theo `state_version` bị người khác kích
hoạt liên tục. Triệu chứng người dùng thấy: *"lệnh chạy nửa chừng rồi thôi"*
(`skipped_external_state_change`), *"bấm Đồng ý mà báo xe không còn an toàn"*
(`approval_invalidated_state`), và ô nhập text bị khoá vì **xe của người khác** vừa lăn
bánh. Xem `docs/adr/ADR-028-pool-xe-ao-theo-phien.md`.

### Bật

Thêm vào `.env` (backend **và** xe ảo phải cùng giá trị — hai tiến trình đọc chung một
biến để biết dựng bao nhiêu xe):

```text
VEHICLE_POOL_SIZE=3
```

Rồi khởi động lại cả hai:

```powershell
docker compose up -d --wait mqtt vehicle-simulator
```

```powershell
.\.venv\Scripts\python.exe -m src.serve
```

> **Đừng đặt quá 3.** Trần này là **con số đo được**, không phải chọn cho tròn:
> llama-server bão hoà quanh 3 lượt đồng thời, và STT/TTS có khoá toàn cục nên mỗi lúc
> chỉ một người nói. Thêm xe thứ tư là mua thêm xe cho một cái cổ chai nằm ở chỗ khác.
> RAM thì dư — 13 KB mỗi xe ảo, 512 KB mỗi phiên backend.

### Kiểm nhanh: có đúng 3 xe không

```powershell
docker compose logs vehicle-simulator | Select-String "sẵn sàng"
```

Phải thấy ba dòng, mỗi dòng một `vehicle_id`: `vehicle-demo-01`, `vivi-xe-02`,
`vivi-xe-03`. `vehicle-demo-01` **luôn là ô số 0** — đó là chiếc mà màn kỹ sư,
healthcheck của `docker-compose` và mọi tài liệu đang trỏ tới, nên một người dùng duy
nhất luôn rơi đúng vào nó.

### Đọc trạng thái xe khi đã bật pool

`GET /vehicle/state` **đổi hợp đồng**: cần đăng nhập, và cần `session_id` để biết hỏi xe
nào.

```powershell
curl.exe -s -H "Authorization: Bearer <token>" "http://localhost:8000/api/v1/vehicle/state?session_id=<ses_...>"
```

Thiếu `session_id` khi pool đang cấp phát thì trả `400 REQUEST_CONTEXT_INVALID` — cố ý.
Trả về xe demo lúc đó là câu trả lời **sai một cách im lặng**: người đang lái `vivi-xe-02`
sẽ điều khiển xe của mình nhưng nhìn màn hình của xe người khác.

### Nghiệm thu — hai trình duyệt, và đây mới là phép kiểm quyết định

Bộ test **không** thay thế được bước này. Cùng tinh thần bốn kịch bản ở §3.3.

1. Mở `/driver` trên **hai trình duyệt khác nhau** (Chrome và Edge, hoặc một cửa sổ ẩn
   danh). **Hai tab trong cùng một trình duyệt không đủ** — chúng dùng chung
   `localStorage` nên chia nhau đúng một phiên, tức đúng một chiếc xe.
2. Mỗi bên ra một lệnh S1 (*"bật điều hoà"*, *"tăng nhiệt độ"*) gần như cùng lúc.
3. **Đạt khi:** cả hai lượt hoàn tất. Trước khi có pool, một bên nhận
   `skipped_external_state_change`.
4. Cho xe của bên A chạy (`speed 45` vào cửa sổ xe ảo — console chỉ lái **ô số 0**).
   **Đạt khi:** chỉ giao diện bên A bị siết; bên B vẫn gõ text được.

### Người thứ tư vào thì sao

Vẫn tạo được phiên và vẫn tra sổ tay được, nhưng **không lái được** — `POST /sessions` trả
`can_drive: false` kèm `pool: {"total": 3, "in_use": 3, "free": 0}`, và mọi lệnh điều
khiển bị từ chối với `vehicle_pool_exhausted`.

Một chiếc xe được nhả lại sau `VEHICLE_LEASE_TTL_S` (mặc định 180 giây) không hoạt động —
người dùng đóng tab không báo cho server, nên không có hạn dùng thì mỗi lượt khách ghé qua
là một chiếc xe mất vĩnh viễn.

### Ba chuyện hay gặp

| Triệu chứng | Nguyên nhân |
|---|---|
| Người thứ hai thấy `503 no_snapshot_yet` | Xe ảo chưa dựng đủ K xe — `VEHICLE_POOL_SIZE` của tiến trình xe ảo khác của backend |
| Giao diện nhận `400` ở `/vehicle/state` | Frontend chưa gửi `session_id`. Bản frontend cũ **không chạy được** với pool đang bật |
| `can_drive: false` ngay người đầu tiên | Hợp đồng cũ chưa hết hạn từ lần chạy trước; chờ hết `VEHICLE_LEASE_TTL_S` hoặc khởi động lại backend |

---

---

# PHẦN III — XÁC NHẬN VÀ CHẠY TEST

## 3.0 CI gác những gì — và không gác những gì

Bảng này tồn tại vì trước 30/08 người đọc **không có cách nào biết**. Frontend có 576 test
mà chưa từng được chạy tự động; `npm run build` đã hỏng trên `develop` bằng một lỗi
TypeScript và không ai biết, vì không có gì chạy nó (issue #239).

| Kiểm | Lệnh | Workflow | Có CI gác? |
|---|---|---|---|
| Python lint | `ruff check src/ tests/ scripts/` | `ci.yml` | ✅ |
| Python test nhanh | `pytest -m "not slow and not integration"` | `ci.yml` | ✅ |
| Frontend lint | `npm run lint` | `frontend.yml` | ✅ từ 30/08 |
| Frontend type-check | `npx tsc --noEmit` | `frontend.yml` | ✅ từ 30/08 |
| Frontend test | `npm run test` | `frontend.yml` | ✅ từ 30/08 |
| Frontend build | `npm run build` | `frontend.yml` | ✅ từ 30/08 |
| MQTT L2 contract | `MQTT_CONTRACT_TESTS=1 pytest …` | `mqtt-contract.yml` | ✅ |
| **Python format** | `ruff format --check src/ tests/ scripts/` | — | ❌ **78 file lệch** |
| **MQTT L3 hai tiến trình** | `MQTT_L3_TESTS=1 pytest …` | — | ❌ |
| **Test `slow`/`integration`** | cần chỉ mục FAISS + model giọng nói | — | ❌ runner không cài |
| **Bộ đo** (`--mode …`, `rag.cli eval`) | xem §3.6 | — | ❌ chạy tay, và cố ý |

**`frontend.yml` chỉ chạy khi `frontend/**` đổi.** Runner là self-hosted của BTC nên thời
gian không miễn phí, và `paths` chỉ lọc được ở mức workflow — đó là lý do nó là một file
riêng chứ không phải một job trong `ci.yml`.

**Vì sao `ruff format --check` chưa bật.** 78 file đang lệch, nên bật thẳng là đỏ ngay.
Cần một commit `ruff format` toàn repo trước, và commit ấy **không được** đi chung PR với
một thay đổi hành vi — diff format lẫn diff logic là cách chắc chắn nhất để một thay đổi
thật lọt qua review.

**Bộ đo không nằm trong CI, và đó là chủ ý.** `agent-multiturn`, `rag`, `bao-loi-2408`
cần chỉ mục FAISS hoặc llama-server; chúng sinh **bằng chứng có mã run**, không phải cổng
pass/fail. Xem `CLAUDE.md` §"Evidence is the product".


## 3.1 `/healthz`

```powershell
curl.exe -s http://localhost:8000/healthz
```

Khi dựng đủ: `"status":"ready"`, 7 component `ready`, `llm` là `disabled`, `faults` chỉ có
`slm_disabled`.

**Đừng dùng HTTP status làm cổng — đọc từng component.** Bốn trạng thái, hai cái cuối **khác nhau**:

| Trạng thái | Nghĩa | Kéo 503? |
|---|---|---|
| `ready` | chạy được | không |
| `degraded` | trả lời được nhưng không đạt yêu cầu | **có** |
| `down` | hỏng, thiếu, hoặc hết giờ | **có** |
| `disabled` | **tắt có chủ đích trong cấu hình đang chạy** | không |

Nguồn: `BLOCKING_STATUSES = {"down", "degraded"}` (`src/services/health.py`).

- `llm = disabled` ở mặc định P0 vì `slm_enabled=false` (issue #95). **Không** kéo 503.
- `MQTT_ENABLED=false` → `mqtt` **và** `vehicle_simulator` cũng thành `disabled`. Đó là lựa chọn,
  không phải sự cố. Component `disabled` **vẫn hiện đủ** trong `components` và `faults` —
  **tắt khác giấu**.
- Chưa làm §2.6 thì `stt`/`tts` là `down` và `/healthz` trả **503** — đúng, vì chúng thiếu thật.

> **Lần gọi `/healthz` đầu tiên sau khởi động có thể trả 503 với `tts_timeout` /
> `rag_index_timeout`** — model đang nạp nguội (E5 mất ~30 s), không phải hỏng. Gọi lại sau khi
> log backend đứng yên.

## 3.2 Trạng thái xe và hợp đồng MQTT

`GET /api/v1/vehicle/state` phải trả **đủ 9 domain**:
`motion hvac windows doors media navigation seat lights trunk`.
Thiếu `lights`/`trunk` nghĩa là simulator cũ — xem §5.3.

Kiểm schema MQTT (không cần broker, thuần offline):

```powershell
.\.venv\Scripts\python.exe scripts\validate_mqtt_schemas.py
```

Kỳ vọng: `TẤT CẢ ĐẠT: 7 phải-pass + 17 phải-fail` (đo thật 2026-08-15).

Smoke end-to-end đủ ba acceptance criteria (cần **cả** broker, xe ảo và backend đang chạy):

```powershell
.\.venv\Scripts\python.exe scripts\smoke_mqtt.py
```

Kỳ vọng: `SMOKE ĐẠT: cả 3 acceptance criteria` (đo thật 2026-08-16 trên `develop` `e6b87c2`).

> Script **tự đăng nhập** bằng `engineer.demo@example.com` rồi chào WS đủ `vivi.v1` +
> `bearer.<base64url-access-token>`, kèm header `Origin` lấy từ `CORS_ORIGINS`. Ba điều kiện đó là
> bắt buộc từ khi `/ws/engineer` siết auth (`docs/api_spec.md:505`, `src/api/ws.py`) — issue #143.
> Sửa `CORS_ORIGINS` thành giá trị backend không nhận thì script báo
> `WS từ chối: FORBIDDEN`, **không** phải traceback.

## 3.3 Bốn kịch bản nghiệm thu

Gõ ở `/driver`. **Đây là bốn nhánh khác nhau của hệ thống** — đã chạy thật 2026-08-15:

| # | Câu | Kết quả đúng |
|---|---|---|
| 1 | `Đặt điều hòa 24 độ` | **S1** — thực thi ngay, tool `set_hvac_temperature`, `status=completed` |
| 2 | `Mở kính bên lái 30%` | **S2** — `status=waiting_approval`, hỏi *"Bạn có đồng ý không?"* |
| 3 | `Áp suất lốp khi lốp nguội là bao nhiêu?` | Trích **nguyên văn** sổ tay + citation có `section`/`page`/`score` |
| 4 | `speed 45` ở cửa sổ xe ảo, rồi `Mở cửa bên lái` | **S3** — *"Xe đang chạy 45 km/h nên tôi chưa làm được. Khi xe dừng hẳn và về số P thì tôi làm ngay."*, **không** hộp thoại. Câu phải nêu **đúng tốc độ trên đồng hồ**; nếu nó nói "trạng thái xe hiện tại không cho phép" thì compose đã lui về câu chung — xem `cau_bi_chan` (SP-3 mục 4). Và nó **không được** đề nghị hành động nào (review #338): một lời mời chưa có đường thực hiện thì tài xế đồng ý xong sẽ nhận một câu từ chối tra cứu. |
| 4b | `gear D` nhưng để `speed 0`, rồi `Mở cửa bên lái` | **S3** vì lý do KHÁC — *"Xe chưa về số P (đang ở số D)…"*. Nếu nó nói "xe đang chạy" ở đây là **sai sự thật**: xe đứng yên. |

**Đặt tốc độ mà không cần cửa sổ xe ảo (ADR-024).** Cửa sổ 2 chỉ tồn tại khi có người ngồi trước máy;
trên một bản deploy công khai thì không. Bật cờ cho **cả hai** service — `SIM_CONTROL_ENABLED=true`
ở backend *và* ở `vehicle-simulator` — rồi gọi:

```powershell
curl.exe -X POST http://localhost:8000/api/v1/sim/motion `
  -H "Authorization: Bearer $token" -H "Content-Type: application/json" `
  -d '{"speed_kph": 45, "gear": "D"}'
```

Trả **202** (xe đổi state bất đồng bộ, poll `GET /vehicle/state` để xác nhận), **404** khi cờ tắt,
**422** khi ngoài dải `0..200` hoặc gear lạ. Thanh trượt trên màn `/driver` là **phần FE của issue
#183, chưa làm** — tới khi có nó, đường không-console vẫn là dòng `curl` ở trên.

`SIM_DRIVE_CYCLE=true` thì xe tự lặp 0 ↔ 45 km/h mỗi 30 giây, không cần ai chạm vào.

Sau khi duyệt lệnh #2, `GET /vehicle/state` phải cho `windows.front_left = 30`. Đó là bằng chứng
lệnh đã đi trọn **HTTP → agent → policy → HITL → MQTT → xe mô phỏng → về lại state**.

Đối chứng cho #4: cùng lúc xe chạy 45 km/h, `Mở kính bên lái 30%` **vẫn là S2** và câu hỏi còn nêu
rõ tốc độ (*"Xe đang chạy 45 km/h. Tôi sẽ…"*). Đúng invariant: **cửa và ghế là S2 chỉ khi
`speed_kph == 0 && gear == P`, ngoài ra là S3; kính thì luôn S2.**

## 3.4 Gọi API bằng dòng lệnh — bốn cái bẫy

1. **`X-Schema-Version: 1.0` bắt buộc ở MỌI route**, kể cả `/auth/login`.
2. **Token nằm ở `data.access_token`**, không phải `data.token`. `/sessions` trả **200**, không phải 201.
3. **`/sessions` và `/turns/text` đều đòi `Idempotency-Key`, hai khoá phải KHÁC nhau.**
4. **`/traces/{trace_id}`** cần id thật; gọi `/traces` trơn là 404 của router, không phải lỗi phân quyền.

> **Đừng gửi JSON tiếng Việt inline qua `curl.exe` trên Windows** — shell làm hỏng encoding,
> backend trả `{"detail":"There was an error parsing the body"}`. `curl.exe` cũng **không đọc được
> path kiểu `/tmp/...` của Git Bash**. Dùng script Python với `urllib`, hoặc ghi body ra file rồi
> `--data-binary "@C:\đường\dẫn\windows.json"`.

Phân quyền đã kiểm: `/metrics/summary` và `/traces/{id}` cho engineer **200**, cho driver **403**.

## 3.5 Chạy test

```powershell
$env:MQTT_ENABLED = "false"
.\.venv\Scripts\python.exe -m pytest tests\ -q
```

**Đo thật 2026-08-15, cùng một checkout, hai trạng thái máy:**

| Trạng thái máy | Kết quả | Thời gian |
|---|---|---|
| Đã dựng đủ index (§2.5) + model giọng nói (§2.6) | **1178 passed, 17 skipped** | ~109 s |
| Chưa dựng index, chưa có model | **1165 passed, 30 skipped** | ~135 s |

Đây là **mốc tham chiếu, không phải cổng** — số nhích mỗi lần có người land test.

### Số skip **không cố định** — đừng lấy nó làm dấu hiệu hỏng

Tài liệu cũ nói sai theo hai hướng ngược nhau ("17 skip đều là marker `slow`+`integration`" và
"17 skip đều là MQTT"). Sự thật:

| Nhóm skip | Số test | Bật bằng cách nào |
|---|---|---|
| `test_contract_mosquitto.py` | 12 | `MQTT_CONTRACT_TESTS=1` + broker thật |
| `test_l3_two_process.py` | 5 | `MQTT_L3_TESTS=1` + broker thật |
| `test_rag_integration/` | 10 | dựng index — §2.5 |
| `test_voice_integration.py`, `test_synthesize_domain_audio.py` | 3 | tải model — §2.6 |

**17 skip là tầng MQTT gán bằng biến môi trường**, luôn skip nếu không đặt env. **13 cái còn lại
biến mất khi dựng xong index + model** — đúng bằng chênh lệch 1178 − 1165 ở bảng trên.

Hệ quả: **CI không bao giờ chạy 13 test kia** — `ci.yml` chạy `-m "not slow and not integration"`
và không cài extra `rag` lẫn model giọng nói. Chúng **chỉ chạy trên máy dev**.

Tự kiểm: thêm `-rs` để in lý do skip.

### Frontend và lint

```powershell
cd frontend; npm run test    # Vitest — bắt buộc khi động vào lib/services/
cd frontend; npm run lint
ruff check src\ tests\
ruff format src\ tests\
```

Đo thật 2026-08-15: **57 passed / 9 file**, ~60 s.

### Evidence — đây mới là deliverable

Thư mục `eval/results/<suite>/<run-id>/` là **bất biến**. Muốn số mới thì chạy lại CLI, nó sinh
run-id mới; **không bao giờ sửa tay file cũ**.

```powershell
.\.venv\Scripts\python.exe scripts\report_mqtt_e2e.py --with-contract --with-l3
.\.venv\Scripts\python.exe -m src.agents.eval --mode intent
.\.venv\Scripts\python.exe -m src.agents.eval --mode routing
```

---

# PHẦN IV — BẬT SLM (tuỳ chọn)

**Mặc định `SLM_ENABLED=false` và đó là thiết kế, không phải thiếu sót** (ADR-006/010): định tuyến
100% bằng luật tất định, không có LLM trên đường chạy. Phần này chỉ dành cho ai cần demo nhánh LLM.

SLM có **bốn vai** sau cùng một cờ (ADR-016, ADR-026, SP-2):

- **`QwenClassifier`** (SP-1, ADR-026) — phân loại 3 lớp `control/manual/chitchat` cho câu
  **trượt hết luật** (`default_to_manual`), TRƯỚC khi tra sổ tay. Grammar ép enum, timeout
  riêng `SLM_CLASSIFY_TIMEOUT_S=2.0`, hỏng kiểu gì cũng rơi về manual (= hành vi cũ).
  Đo 21/08: ~450 ms/lượt ấm; 56/62 đúng trên `dinh-tuyen-v1` so với 41/62 của luật thuần
  (run `20260821T130203.508716Z`). Câu khớp luật vẫn đi đường tắt, không gọi model.
- **`QwenPlanner`** — đề xuất lệnh khi luật bó tay: qua classifier chấm `control`, hoặc theo
  đường ADR-022 cũ (**sau khi** tra sổ tay thất bại) cho câu `not_control` không qua classifier.
  Vòng đời cứng: đề xuất → kiểm closed-schema → **đúng một** lần sửa → vẫn hỏng thì hỏi lại.
  Không ReAct, không retry mở.
- **`QwenLeadIn`** — viết câu mở đầu cho câu trả lời sổ tay. Không mang dữ kiện; hỏng thì rơi về
  chuỗi cố định.
- **`QwenChitchat`** (SP-2) — sinh câu xã giao cho lớp `chitchat` của classifier, prompt riêng, đi qua
  **cổng tất định bốn lớp** (`src/agents/nodes/chitchat_cong.py`: hệ chữ lạ → quá dài → số kèm đơn vị →
  "đã làm gì trên xe"); vỡ lớp nào rơi về câu mẫu. Timeout riêng `SLM_CHITCHAT_TIMEOUT_S=4.0`.
  Đo 22/08 (run `chitchat/20260822T043750.630790Z`, **hai server**: classify trên iGPU 8094, chitchat
  trên dGPU 8093): 14/14 qua cổng, chấm tay đúng phạm vi 13/14, bịa dữ kiện 0/14; tổng classify+sinh
  p50 2,9 s / p95 3,1 s. **Một server** thì classify xen kẽ với sinh mất 3,1 s mỗi lượt và tổng p50
  5,9 s (run `…043502`) — xem `docs/reports/sp0-do-tre-tung-doan-2026-08-22.md` §2.

Đo bộ phân loại (cần llama-server thật đang chạy):

```powershell
.\.venv\Scripts\python.exe -m src.agents.eval --mode dinh-tuyen   # -> eval/results/agent-routing/
$env:SLM_SERVER_TESTS="1"; .\.venv\Scripts\python.exe -m pytest tests/test_agents/test_slm_classifier_contract.py -q -s
.\.venv\Scripts\python.exe -m src.agents.eval --mode chitchat      # -> eval/results/chitchat/ (SP-2)
```

## 4.1 Hai thứ phải tải thêm

| Thứ | Nguồn | Kiểm |
|---|---|---|
| `llama-server` | llama.cpp release **`b10358`**, asset `llama-b10358-bin-win-vulkan-x64.zip` | SHA256 đã pin trong `tools/llama-vulkan/llama-vulkan.zip.sha256` |
| Qwen GGUF | `Qwen/Qwen2.5-3B-Instruct-GGUF` @ `7dabda4d13d513e3e842b20f0d435c732f172cbe`, file `qwen2.5-3b-instruct-q4_k_m.gguf` (~2,1 GB) | Sidecar `.sha256` có sẵn trong repo |

```powershell
# llama-server
curl.exe -sL -o .\tools\llama-vulkan\llama-vulkan.zip `
  https://github.com/ggml-org/llama.cpp/releases/download/b10358/llama-b10358-bin-win-vulkan-x64.zip
Expand-Archive .\tools\llama-vulkan\llama-vulkan.zip -DestinationPath .\tools\llama-vulkan -Force

# Model — dùng script pin sẵn của dự án (nó tự ghi .sha256 + .metadata.json)
.\experiments\offline_poc\scripts\download_models.ps1 -Profile qwen25-3b-q4 `
  -HfExecutable "$PWD\.venv\Scripts\hf.exe"
```

> Qwen 3B theo **license Qwen Research** (phi thương mại). `download_models.ps1` tải **đúng một
> profile mỗi lần gọi** — đừng sửa nó để tải hàng loạt.

## 4.2 Chạy

`-Device` là **bắt buộc** — không còn `auto` (issue #145). Liệt kê thiết bị trước, rồi chọn
theo **tên** (không phải nhãn `VulkanN` — nhãn đó đảo thứ tự giữa các lần chạy, không ổn định):

```powershell
.\tools\llama-vulkan\llama-server.exe --list-devices
# Vulkan0: AMD Radeon(TM) Graphics (8034 MiB, ...)              <- iGPU
# Vulkan1: NVIDIA GeForce RTX 3050 Laptop GPU (3962 MiB, ...)   <- dGPU thật

# Cửa sổ riêng: SLM server (cổng 8093) — match theo MỘT PHẦN tên thiết bị
.\scripts\run_slm_server.ps1 -Model "$PWD\experiments\offline_poc\models\qwen2.5-3b-instruct-q4_k_m.gguf" `
  -Device "RTX 3050"   # hoặc -Device cpu

# Trong .env:  SLM_ENABLED=true
# Rồi KHỞI ĐỘNG LẠI backend — cờ chỉ được đọc lúc dựng graph.
```

Script tự verify checksum model trước khi load ("no unverified artifacts"), in cả danh sách
thiết bị mỗi lần chạy (không chỉ cái được chọn), và ghi tên thiết bị đã resolve vào
`eval/results/spike-003/device-last.json` để manifest của lượt đo lấy từ đó. Dừng:
`.\scripts\run_slm_server.ps1 -Stop`.

Kiểm: `curl.exe -s http://127.0.0.1:8093/health` → `{"status":"ok"}`, rồi `/healthz` của backend
phải cho `llm: ready` và `faults: []`.

> ⚠️ **Bật SLM thì 3 test sẽ fail — nhớ tắt lại trước khi chạy `pytest`.** Bộ test đọc `.env`,
> nên `SLM_ENABLED=true` làm hỏng ba test khẳng định hành vi mặc định P0:
> `test_slm_disabled_means_no_planner_and_no_behavior_change`,
> `test_model_profile_la_not_selected_o_p0`,
> `test_health_dung_shape_200_ke_ca_khi_co_component_down`.
> Đây **không** phải regression — đặt lại `SLM_ENABLED=false` là cả ba xanh lại.

> ⚠️ **`-Device` chọn theo TÊN thiết bị và từ chối đoán khi mơ hồ.** Nếu chuỗi khớp nhiều hơn một
> thiết bị (vd `-Device "Radeon"` trên máy có cả iGPU và dGPU Radeon), script dừng và liệt kê —
> không tự chọn bừa. Trước đây mặc định là `-Device auto`, chọn theo dung lượng VRAM khai báo lớn
> nhất; iGPU khai báo RAM hệ thống chia sẻ nên thường thắng dGPU thật — máy kiểm chứng chọn *AMD
> Radeon iGPU (8034 MiB)* thay vì *RTX 3050 (3962 MiB)*, tức **âm thầm đo nhầm tầng phần cứng**
> (issue #145). `auto` đã bị bỏ hẳn, không sửa ngưỡng.

> ⚠️ **Server nguội làm hỏng vài lượt đầu, và hỏng lặng lẽ.** Vừa khởi động llama-server mà demo
> ngay thì model còn đang nạp vào VRAM, mỗi lời gọi SLM vượt `slm_timeout_s` = 8 s và **rơi về
> hành vi không-SLM** — planner thành `clarify`, lead-in thành chuỗi cố định. Log backend hiện
> `SLM attempt 1/2 hỏng (hạ tầng): timed out`. Đây **không** phải SLM chậm; đo thật trên cùng máy
> đó khi đã ấm thì một lời gọi chỉ **669–989 ms** (decode 71–74 tok/s). **Luôn bắn vài lượt nháp
> trước khi demo.**

## 4.3 Đã kiểm được gì — và bốn cảnh báo

Đo thật 2026-08-15, Qwen 3B q4_k_m, cùng một máy, **hai tầng phần cứng**, server đã ấm.
Số là **độ trễ end-to-end cả lượt** (HTTP + RAG + graph + SLM) — **không** phải p50 SLM-only của
`spike3_bench.py`, đừng đặt cạnh 877 ms / 17,4 s trong bảng tầng của SPIKE-003.

| Câu | iGPU (AMD, 8034 MiB) | dGPU (RTX 3050, 3962 MiB) |
|---|---|---|
| `Hôm nay trời đẹp nhỉ?` (rơi về sổ tay) | 2,39 s | **2,28 s** |
| `Xin chào cabin copilot` | 6,65 s | **3,59 s** |
| `Cảm ơn nhé` | **5,14 s** | 8,27 s |
| `Chuyển khoản giùm tôi 2 triệu cho anh Ba` | 4,74 s | **3,84 s** |
| `Tôi thấy hơi nóng, làm gì đó đi` (planner) | 8,17 s | **3,81 s** |
| `Áp suất lốp khi lốp nguội…` (lead-in) | 4,62 s | **3,55 s** |

Một **lời gọi SLM đơn lẻ** trên dGPU khi đã ấm: **669–989 ms**, decode 71–74 tok/s.

**Bốn thứ phải biết trước khi demo nhánh này:**

1. **Chậm hơn hẳn, kể cả trên dGPU.** 2,3–8,3 s mỗi lượt, so với ~0,2 s khi tắt SLM. dGPU nhanh
   hơn iGPU khoảng gấp đôi ở các lượt thật sự gọi SLM, nhưng mục tiêu P0 p50 ≤ 2,5 s thì **cả hai
   tầng đều không đạt**.
2. **Rớt token ngoại ngữ.** `Cảm ơn nhé` → *"Không**客气**, có gì khác tôi giúp bạn không?"* —
   ký tự tiếng Trung lọt vào câu tiếng Việt. **Tái hiện y hệt trên cả iGPU lẫn dGPU**, nên là lỗi
   chất lượng model chứ không phải lỗi tích hợp hay phần cứng.
3. **Planner có thể đề xuất hành động sai mà vẫn hợp schema, và nó sẽ được thực thi.**
   `Tôi thấy hơi nóng, làm gì đó đi` → SLM đề xuất `media_control(set_volume, 10)` → phân loại
   **S1** → **chạy luôn, không hỏi**. Cổng an toàn chặn cái *nguy hiểm*, không chặn cái *vô nghĩa*.
4. **Chỉ chitchat gần với few-shot mới ra chitchat.** `Hôm nay trời đẹp nhỉ?` vẫn rơi về
   *"Tôi không tìm thấy thông tin này trong sổ tay xe."*

**Kết luận vận hành:** với demo thường có thể để `SLM_ENABLED=false` để ưu tiên độ trễ và tính
tất định. **Với demo Gate G2, phải bật `SLM_ENABLED=true` và xác minh LLM thật đã được gọi qua
health/trace**; đó là bằng chứng bắt buộc cho user flow end-to-end, không dùng mock.

---

# PHẦN V — TRA CỨU KHI HỎNG

## 5.1 `prepare_vf9_index.ps1` dừng với `NativeCommandError`

```
python.exe : Token indices sequence length is longer than ... (613 > 512)
    + FullyQualifiedErrorId : NativeCommandError
```

**Không phải lỗi của project.** Dòng đó chỉ là cảnh báo tokenizer trên stderr. PowerShell 5.1 bọc
stderr của native exe thành `ErrorRecord`; gặp `$ErrorActionPreference = "Stop"` thì thành lỗi
dừng. Nguyên nhân là **bạn đã thêm `2>&1`** khi gọi script:

```powershell
.\scripts\prepare_vf9_index.ps1          # ĐÚNG
.\scripts\prepare_vf9_index.ps1 2>&1     # SAI — biến cảnh báo thành lỗi
```

## 5.2 `docker compose up` báo `port is already allocated`

```
Bind for 127.0.0.1:1883 failed: port is already allocated
```

Thường là **broker của một worktree/compose project khác vẫn đang chạy**:

```powershell
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Hai cách xử lý — tắt container kia, hoặc đổi cổng cho project này trong `.env`
(`MQTT_HOST_PORT=1884` **và** `MQTT_URL=mqtt://localhost:1884`), rồi:

```powershell
docker compose rm -fs mqtt vehicle-simulator; docker compose up -d --wait mqtt
```

> ⚠️ **Đây là cái bẫy nguy hiểm nhất trong repo.** Nếu backend nối nhầm broker của project khác,
> mọi thứ vẫn "xanh" nhưng test tầng L2 đang kiểm sai broker — từng có lần nó kết nối **ẩn danh**
> vào broker khác rồi báo cáo phát hiện ACL về broker đó. Luôn xác nhận log backend in đúng cổng
> bạn cấu hình.

## 5.3 `GET /vehicle/state` trả 503 `no_snapshot_yet`, màn hình IVI đứng im

Simulator cũ publish 7 domain, backend mới đòi 9 (`lights` + `trunk` là **required**):

```
WARNING src.services.vehicle_state:170 Snapshot sai schema trên
        v1/vehicles/vehicle-demo-01/state/snapshot: 2
```

Số `2` là đúng hai field thiếu. Dây chuyền: `VehicleStateCache._state` giữ `None` →
`/vehicle/state` 503 → `safety_node` từ chối lượt với `vehicle_state_unavailable` → IVI đứng im.

**Tắt/bật backend không chữa được** — `state/snapshot` là **retained**, và `mosquitto.conf` bật
`persistence true` với named volume `mosquitto_data`, nên bản 7-domain sống qua cả
`docker compose down`.

```powershell
docker compose up -d --build --force-recreate vehicle-simulator
```

Chạy simulator bằng tay thì chỉ cần khởi động lại tiến trình.

## 5.4 Mọi kết nối MQTT ném `NotImplementedError`

Bạn chạy `uvicorn src.main:app` thay vì `python -m src.serve`.

## 5.5 Xe ảo báo `Disconnected during message iteration` lặp lại

Đang có **2 xe mô phỏng thật sự** cùng chạy trên một broker — thường là bạn quên
`docker compose stop vehicle-simulator` sau khi lỡ `docker compose up -d` trống.

> ⚠️ **Đếm tiến trình Python trên Windows sẽ báo động giả.** `python.exe` trong venv là
> **launcher**: nó exec interpreter gốc, nên **một** lần chạy luôn hiện **hai** dòng — một ở
> `.venv\Scripts`, một ở `AppData\...\Python311`. Đó là cặp cha–con, không phải hai tiến trình.
> Kiểm bằng `ParentProcessId` chứ đừng đếm dòng:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'src\.vehicle_sim' } |
  Select-Object ProcessId, ParentProcessId, ExecutablePath
```

Muốn tắt thì tắt **tiến trình cha** kèm `/T` để hạ cả cây: `taskkill /PID <cha> /T /F`.

## 5.6 Backend chết ngay khi khởi động

```
ValueError: unsupported DATABASE_URL scheme: 'postgresql://...'
```

Chết **lúc import**. `.env` của bạn còn dòng boilerplate cũ (issue #93). `.env.example` trên
`develop` đã sửa — copy lại là xong.

## 5.7 Bấm mic thì lượt thất bại với `INTERNAL_ERROR`

Chưa làm §2.6. Ghi âm thành công nhưng `get_stt_engine()` ném lỗi vì thiếu `sherpa_onnx` hoặc
`models/voice/`. Lỗi này **không** phải `STT_FAILED` — nhánh đó dành riêng cho audio hỏng thật, cố
ý tách ra để hệ thống không đổ lỗi oan cho micro tài xế.

## 5.8 Giao diện hiện dữ liệu đẹp nhưng backend im

`frontend/.env.local` thiếu ba cờ `USE_MOCK`, hoặc chưa restart `npm run dev`.

## 5.9 Sửa code rồi mà vẫn thấy hành vi cũ

Tiến trình cũ vẫn giữ cổng 8000/3000; tiến trình mới không bind được và **chết lặng lẽ**, còn
`curl` vẫn trả 200 — của bản cũ.

```powershell
Get-NetTCPConnection -LocalPort 8000,3000,1883,1884 -State Listen |
  ForEach-Object { "{0}: {1} PID {2}" -f $_.LocalPort, (Get-Process -Id $_.OwningProcess).ProcessName, $_.OwningProcess }
```

---

# PHẦN VI — CHỨNG MINH ĐƯỢC GÌ, CHƯA CHỨNG MINH ĐƯỢC GÌ

| Muốn chứng minh | Cần | Được? |
|---|---|---|
| Router, an toàn S0–S3, HITL, persistence | pytest | ✅ 1178 test (2026-08-15) |
| Điều khiển thật qua MQTT tới xe mô phỏng | Phần I + II | ✅ S1 và S2-đã-duyệt đều đổi được state |
| Chặn lệnh nguy hiểm khi xe chạy | §3.3 #4 | ✅ S3 chặn thẳng; kính vẫn S2 |
| Hỏi đáp sổ tay có trích dẫn | §2.5 | ✅ trích **nguyên văn**, không diễn giải (ADR-015) |
| Phân quyền tài xế / kỹ sư | §3.4 | ✅ engineer 200, driver 403 |
| 4 tầng MQTT L0–L3 | broker thật | ✅ 190/190 (đo 2026-08-13) |
| UI/UX, luồng màn hình | FE mock | ✅ |
| Regression logic FE | `npm run test` | ✅ 57/57 (2026-08-15) |
| Hợp đồng BE↔FE, HITL, S2/S3 | FE real + backend | ✅ 23/26 nút |
| Trò chuyện tự nhiên (chitchat) | Phần IV | ⚠️ chạy được nhưng **chậm 2,4–8,2 s** và rớt token tiếng Trung |
| Giọng nói mic → STT → TTS → loa | §2.6 | ⚠️ chạy được, **chưa đo WER người thật** |
| Nói "nghe tiếp" để đọc tiếp đoạn sổ tay | — | ❌ **không có trong code** |
| Tra áp suất lốp theo cấu hình xe (ECO/PLUS, SDI/CATL) | — | ❌ `src/safety/ap_suat_lop.py` có, **chưa nút nào trong luồng lượt gọi tới** |
| Đọc/ghi cấu hình xe `/vehicle/profile` | — | ❌ **chưa có trên `develop`** |
| Quạt +/−, nút tắt đèn | FE real | ❌ FE phải đổi câu gửi — xem TASK-BE-FE-004 |
| Trạng thái đèn/cốp trên màn hình | FE real | ❌ `turn/real.ts` hard-code `lights: false` / `trunk: "closed"` |
| Duyệt HITL bằng giọng nói | — | ❌ `approval.intent.detected` chưa implement |
| Replay khi mất kết nối | — | ❌ server làm đủ (ADR-014) nhưng client không gửi cursor |
| Độ trễ end-to-end đạt p50 ≤ 2,5 s | — | ❌ **chưa đo bao giờ.** Nhánh SLM đo được thì **trượt** |
| Diễn tập offline (no-network) | `scripts/offline_drill.py` | ✅ **đã chạy** 2026-08-15, 7/7 ca đạt — run [`eval/results/offline-drill/20260815T103754.705204Z/`](../eval/results/offline-drill/20260815T103754.705204Z/report.md). **Điểm mù đã biết:** drill chặn DNS nên nó chỉ chứng minh *không có gì thoát ra khi bị chặn*, không chứng minh *runtime không gọi ra ngoài khi có mạng* — xem `tests/test_rag_integration/test_embedder_khong_mo_ket_noi_mang.py` |

**Test đơn vị xanh không phải bằng chứng về chất lượng model hay độ trễ.** Audio Piper tổng hợp
không phải WER người thật. Mọi khẳng định định lượng phải truy được về một run-id trong
`eval/results/`.
