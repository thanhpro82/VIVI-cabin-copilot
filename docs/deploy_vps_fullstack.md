# Runbook đầy đủ — Deploy **tất cả** lên một VPS, một tên miền

## Trạng thái: **Chưa kiểm chứng đầu-cuối** (soạn 2026-08-19; bổ sung mục 7.1
và cảnh báo nhánh ở mục 7, 2026-08-20)

Chưa ai chạy trọn quy trình này. Nhưng **mọi đường định tuyến, tên biến và số đo trong
file đều đã đối chiếu thẳng vào code hoặc vào phép đo ngày 2026-08-18** (`src/main.py`,
`src/api/ws.py`, `frontend/src/lib/services/*/real.ts`,
`frontend/src/app/api/auth/demo-driver/route.ts`, `tech_stack.md` mục 4b) chứ không
suy từ tài liệu khác. Chỗ nào là ước lượng chưa đo thì có ghi rõ.

**File này tự đủ** — đọc từ trên xuống, chạy từng lệnh, không cần mở file khác.

| File | Vai trò |
|---|---|
| **file này** | **Hình dạng A: một máy chạy hết, một domain.** Chọn đường này thì chỉ cần file này |
| `docs/deploy_vps.md` | Hình dạng B, nửa backend (frontend đi Vercel). Nội dung backend trùng với mục 3–11 dưới đây |
| `docs/deploy_frontend_vercel.md` | Hình dạng B, nửa frontend |
| `docs/deploy_platform_choice.md` | Vì sao VPS chứ không phải Render/Fly/Railway/Coolify |
| `docs/tech_stack.md` | Nguyên liệu: RAM/đĩa/độ trễ đã đo |

Quy ước: lệnh có dấu nhắc **PowerShell trên máy Windows** hay **bash trên VPS** đều
được ghi rõ ở đầu mục. Mỗi khối là **một lệnh** — chép từng khối một, đừng dán cả loạt.

---

# PHẦN I — CHUẨN BỊ

## 0. Bảng kiểm trước khi bắt đầu

| Thứ | Yêu cầu | Vì sao |
|---|---|---|
| VPS | Ubuntu 24.04. **SLM tắt:** 4 GB RAM, ≥ 25 GB đĩa. **SLM bật (3B — cấu hình đã chốt): tối thiểu 5 GB RAM, ≥ 30 GB đĩa** | xem mục 1 |
| **Tên miền** | đã mua, đã trỏ **A record** về IP VPS | **Bắt buộc.** `getUserMedia` (micro) chỉ chạy trên HTTPS. IP trần = không có chứng chỉ = không có giọng nói |
| Máy Windows | có đủ `models/voice/` và `data/rag/` | Cả hai **nằm ngoài git**, `git clone` trên VPS không mang theo |
| **Nhánh mã nguồn** | `develop` **đã gộp commit `Dockerfile` của PR #214** — không phải `develop` trần, cũng **không phải** nhánh 184 trần (thiếu 37 commit) | Kiểm và cách gộp ở mục 7 |
| Khoá SSH | đã tạo, đã thêm vào VPS | Đừng dùng mật khẩu root |

**Trỏ A record trước tiên** — DNS mất vài phút tới vài giờ để lan. Làm bước đó ngay
bây giờ rồi mới đọc tiếp, tới mục 16 là vừa kịp.

### 0.1. Tên miền: bắt buộc, nhưng **không bắt buộc phải mua**

Ba lý do khiến nó không bỏ được, và cả ba đều nằm ở phía trình duyệt chứ không phải
phía ta:

1. `getUserMedia` (micro) chỉ chạy trên **secure context** — HTTPS hoặc `localhost`.
   Người dùng ở xa không có `localhost`.
2. **Let's Encrypt không cấp chứng chỉ cho IP trần.**
3. Trang HTTPS **không được phép** gọi `http://<ip>:8000` — trình duyệt chặn mixed
   content, WebSocket cũng vậy.

Điều này đúng cho **cả hai hình dạng**: đi Vercel thì frontend có sẵn `*.vercel.app`,
nhưng **API vẫn cần một tên miền**, nếu không trang HTTPS trên Vercel không gọi được
backend.

| Lựa chọn | Chi phí | Đánh giá |
|---|---|---|
| **`.id.vn` của VNNIC** | **0₫ trong 2 năm** (công dân VN 18–23 tuổi), sau đó ~60–70k₫/năm | **Nên chọn.** Tên miền thật, Let's Encrypt cấp chứng chỉ bình thường. Đăng ký qua iNET/PA/Nhân Hoà/Tenten |
| `.io.vn`, `.xyz`, `.com` | ~50k–350k₫/năm | Bình thường, mua ở đâu cũng được |
| **DuckDNS** (`<tên>.duckdns.org`) | 0₫ | Chạy được với Let's Encrypt, nhưng là subdomain dùng chung → dính hạn mức của người khác. Chấp nhận được cho thử nghiệm |
| **`nip.io` / `sslip.io`** | 0₫ | **Đừng dùng.** Hạn mức 50 000 chứng chỉ/tuần của Let's Encrypt cho cả tên miền đó đã cạn từ 02/2026 — xin chứng chỉ hay trượt |
| Cloudflare Tunnel / Tailscale Funnel | 0₫ | Không cần tên miền, nhưng đó là **hình dạng C** (tunnel), và tunnel free hay cắt WebSocket sống lâu |

**Không phải mua:** chứng chỉ SSL (Caddy tự xin Let's Encrypt, mục 16), và Cloudflare
(tuỳ chọn — hơn nữa proxy free của nó thường bị nhắc là cắt WS ở mốc ~100 s, **chưa đo
trên hệ này**, nên nếu bật thì phải kiểm lại luồng sự kiện).

## 1. Chọn máy — RAM quyết định, đĩa thì không

Đã đo (`tech_stack.md` mục 4b, mốc `warm_voice`, một phiên một người):

| Thành phần | RAM | Nguồn số |
|---|---:|---|
| 3 container backend (backend 1 148 + xe ảo 52 + broker 6,7) | **1 208 MiB** | **đã đo** 2026-08-18 |
| `next start` | **138 MB** | **đã đo** 2026-08-19 (2 tiến trình node: 49,8 + 88,6) |
| Ubuntu + Docker daemon + Caddy | ~500 MB | ước lượng |
| **Nền lúc chạy — SLM tắt** | **~1,74 GiB** (1 776 MiB) | |
| `llama-server` **3B** q4_k_m | **+2 109 MB** | **đã đo** 2026-08-19 (mục 18), chỉ khi `SLM_ENABLED=true` |
| **Nền lúc chạy — SLM bật (3B)** | **~3,79 GiB** (3 885 MiB) | xem PHẦN VII |
| `next build` (đỉnh, chỉ lúc build) | **1 173 MB** | **đã đo** 2026-08-19, đỉnh ở 17 tiến trình node trên máy 16 nhân |

| RAM máy | SLM tắt | SLM bật (**3B**, model đã chốt) |
|---|---|---|
| 2 GB | **Không đủ**, kể cả chỉ backend | **Không đủ** |
| 4 GB | **Chạy được** (~44%) | **Không đủ** — 3,79 GiB gần bằng toàn bộ RAM khả dụng sau kernel |
| **5 GB** (gói phổ biến ở VN) | Thoải mái | **Chạy được** (~76–82%), trống **0,86–1,21 GB**. Lúc `next build` chỉ cần dừng **một** trong hai — xem mục 14 |
| **8 GB** | **Mua sự đơn giản.** Build lúc nào cũng được | **Mua sự đơn giản** |

Bản **0,5B** chỉ tốn 645 MB (SPIKE-003) → tổng ~2,47 GiB. Nhưng model **đã chốt là 3B**
(quyết định 2026-08-19), nên bảng trên dùng 3B; 0,5B chỉ còn là điểm tham chiếu.

**Đĩa — SLM tắt: 25 GB đủ.** ≈6–8 GB cho `/var/lib/docker` sau lần build đầu, ~900 MB
cho `node_modules` + `.next`, ~90 MB cho `models/` + `data/rag` trên host (đã đo), còn
lại dự phòng.

**Đĩa — SLM bật (3B): cộng ~6,4 GB**, nên mức tối thiểu nên đặt là **30 GB**:

| Khoản thêm khi bật SLM | Dung lượng |
|---|---:|
| `qwen2.5-3b-instruct-q4_k_m.gguf` | **2 007 MB** |
| Nhị phân llama.cpp `b10358` (tarball + thư mục giải nén) | ~300 MB |
| **Swapfile 4 GB** (mục 4.1 — bắt buộc trên máy 4–5 GB) | 4 096 MB |

> Bản 0,5B chỉ 469 MB — nhưng model đã chốt là 3B.

### 1.1. CPU — chọn vCPU **nhanh**, đừng chọn vCPU **nhiều**

Hai chi tiết trong code quyết định chuyện này:

- **`src/services/voice.py:137` đặt `num_threads=1`** cho recognizer sherpa-onnx →
  STT chạy **một luồng**, thêm lõi không làm nó nhanh hơn.
- **Khoá `threading.Lock` toàn cục trên STT và TTS** (`voice.py:97`, `:192`) → mỗi lúc
  đúng **một** lượt thoại, thêm lõi không tăng thông lượng mà chỉ xếp hàng.

Cộng với router thuần luật (0,055 ms), kết luận là **tốc độ một lõi quyết định độ
mượt, không phải số lõi** — nhưng **chỉ đúng khi `slm_enabled=False`**.

**Bật SLM thì lập luận trên đảo chiều một nửa.** `llama-server` là thành phần **duy
nhất** trong hệ thật sự chia việc ra nhiều luồng, và nó nằm **trên đường tới hạn** của
lượt thoại (planner được gọi đồng bộ trong `slm_stage`, `graph.py:257`). Từ lúc đó, số
nhân **vật lý** có ảnh hưởng trực tiếp tới độ trễ lượt nói.

Nhưng "nhiều hơn" không tự động là "nhanh hơn": giải mã của llama.cpp bị chặn ở **băng
thông bộ nhớ**, và model lượng tử hoá chạm trần đó sớm. Đo 2026-08-19 với **3B**
(mục 18): `-t 2` → 9,2 tok/s, `-t 4` → **14,0**, `-t 6` → 13,1. Tức **từ 4 luồng trở lên
là gần bão hoà**; SPIKE-003 còn đo được cpu12 *chậm hơn* cpu6 — thêm luồng SMT là lỗ.

| vCPU | SLM tắt | SLM bật (**3B**) |
|---|---|---|
| **2 vCPU** | **Đủ để chạy.** Nhưng `docker compose build` cache lạnh mất 141 s trên máy 16 lõi → ở đây tính bằng chục phút | **Không nên.** `-t 2` đo được planner p50 **8 561 ms**, vượt trần 8 000 ms → quá nửa số lời gọi hỏng. Muốn dùng phải nới `SLM_TIMEOUT_S` (mục 22) |
| **4 vCPU** | **Nên chọn** — để build đỡ lâu và để Caddy + Next + Docker không tranh CPU với backend lúc demo | **Mức tối thiểu.** `-t 4` đo được planner p50 5 352 ms / max 7 359 ms, lọt dưới trần 8 s — **nhưng chỉ nếu 4 vCPU là 4 nhân *vật lý***. Kiểm bằng mục 1.2 |
| 8 vCPU trở lên | **Không cần** | **Gần như không giúp.** `-t 4` → `-t 6` đo được 14,0 → 13,1 tok/s, tức đã bão hoà băng thông bộ nhớ. Tiền nên tiêu vào nhân *nhanh*, không phải nhân *nhiều* |

> **Ghi chú về Qwen.** `slm_enabled` mặc định là **`True`** kể từ **ADR-027** (2026-08-22;
> trước đó là `False`). Trên VPS điều đó **không** tự chạy LLM — llama-server là một tiến
> trình riêng, không có trong compose — nhưng nó khiến mỗi câu trượt luật trả thêm một nhịp
> timeout vô ích. **VPS phải ghi rõ `SLM_ENABLED=false` trong `.env`**; im lặng không còn đủ.
> Khi đã ghi rõ thì định tuyến 100% bằng luật theo ADR-006/ADR-010 y như trước. Bật cờ đó lên thì backend gọi HTTP tới một tiến trình
> **llama-server riêng** ở `http://127.0.0.1:8093` — tiến trình đó **không có trong
> `docker-compose.yml`**, phải tự cài và tự chạy (**PHẦN VII**).
>
> Mặc định `slm_model_id` là `qwen2.5-3b-instruct-q4_k_m`, và **giá trị đó giữ nguyên**
> (quyết định 2026-08-19). Mục 18 có số đo trên CPU, mục 22 là dòng `.env` phải thêm.
>
> **Nếu đặt `SLM_ENABLED=true` thì chuyện gì xảy ra?** Hai kịch bản, và cái nào cũng
> không làm sập hệ:
>
> - **Bật cờ mà không chạy llama-server** — `slm_stage` bắt `httpx.HTTPError`, thử lại
>   đúng một lần, rồi **lui về câu trả lời sổ tay** đã tính sẵn (`_lui_ve_so_tay`,
>   `graph.py:288`) hoặc `clarify`. Kết nối bị từ chối nên hỏng ngay, không phải chờ
>   hết `slm_timeout_s`. `/healthz` báo `llm: down` nhưng **không chặn readiness**
>   (miễn trừ theo tên ở P0, issue #48). Kết quả: hành vi gần như y hệt lúc tắt, chỉ
>   thêm dòng log cảnh báo. Vô hại, nhưng cũng vô ích.
> - **Bật cờ và chạy được llama-server** — planner chỉ được gọi cho câu mà router
>   **không khớp luật** (`route_reason == "default_to_manual"`, `graph.py:253`), không
>   phải mọi lượt. Cái được: câu đó có thể thành một *lệnh điều khiển* thay vì tra sổ
>   tay, và câu trả lời sổ tay có câu dẫn tự nhiên thay vì chuỗi cố định (câu dẫn
>   **fail-open**, hỏng thì rơi về chuỗi cũ).
>
> Cái mất mới là vấn đề: `graph.py:299` ghi một lời gọi planner tốn **1 450–8 200 ms**
> — **đo trên máy dev có GPU RTX 4050**. Đỉnh của khoảng đó đã chạm `slm_timeout_s = 8`.
> Trên VPS không GPU thì gần như chắc chắn quá hạn, thử lại lần hai, rồi vẫn lui về
> đúng câu trả lời mà bản tắt cờ đưa ra trong ~100 ms — chỉ chậm hơn tới 16 giây.
>
> Đó là lý do **PHẦN VII bắt đầu bằng việc đổi model**, không phải bằng việc cài
> llama.cpp.

#### Đọc *tên* CPU, không chỉ *số* vCPU — ví dụ Xeon E5-2696 v4

Trang bán VPS hay ghi tên CPU nền. Nó nói nhiều hơn con số vCPU, vì bảng trên giả định
mỗi lõi nhanh cỡ nhân đã đo (i7-14650HX). Cách đọc ngược:

| Dấu hiệu trên trang bán | Nghĩa là gì |
|---|---|
| **Xeon E5 v3/v4** (Haswell/Broadwell, 2014–2016) | Nhân **cũ và chậm**, base 2,1–2,4 GHz. Nền của phần lớn VPS giá rẻ bán lại |
| Xeon Gold/Platinum, EPYC 7xx2 trở lên, Ryzen | Nhân đời mới, gần với nhân đã đo hơn |
| "shared", "burstable", "credit" | Xem cảnh báo ngay dưới bảng này |

**Ví dụ đã gặp: `Intel Xeon E5-2696 v4 @ 2.20GHz`** — Broadwell-EP, ra **2016**,
22 nhân / 44 luồng, base **2,2 GHz**. Hai hệ quả, và hệ quả thứ hai mới là hệ quả giết
người:

1. **Single-thread yếu.** *Ước lượng* chậm hơn nhân đã đo khoảng **2–3 lần** — đây là
   suy luận từ đời nhân và xung nhịp, **không phải số đo**; mục 24 vẫn là bước bắt buộc.
2. **"4 vCPU" trên một máy 22 nhân / 44 luồng gần như chắc chắn là 4 *luồng*, tức
   2 nhân vật lý.** Nhà cung cấp bán luồng, không bán nhân.

Điểm 2 mới là điểm giết, và giờ có số đo trực tiếp cho nó. Chạy `-t 2` **trên nhân
i7-14650HX đời 2024** (đo 2026-08-20, đúng đường code thật có `json_schema`):

| | Planner p50 | Planner max | Quá trần 8 s |
|---|---:|---:|---:|
| `-t 4` | 5 329 ms | 6 540 ms | 0 / 8 |
| **`-t 2`** | **7 326 ms** | **11 851 ms** | **2 / 8** |

Tức trên **nhân đời 2024**, hai luồng đã làm hỏng một phần tư số lời gọi. Hai nhân
**Broadwell 2016 @ 2,2 GHz** chậm hơn đáng kể, nên "4 vCPU" của một máy E5 v4 nhiều
khả năng còn tệ hơn cột `-t 2` này.

Ánh xạ hai hệ quả đó vào bảng vCPU ở trên:

| | Trên CPU đời mới | Trên E5-2696 v4, "4 vCPU" |
|---|---|---|
| **SLM tắt** (mặc định) | Đủ | **Vẫn đủ.** Đường tới hạn là STT một luồng; chậm hơn thấy rõ nhưng tải nền chỉ 0,24–0,65% CPU và mọi thứ dồn vào đợt ngắn |
| **SLM bật (3B)** | `-t 4`: p50 5 352 ms, max 7 359 ms — lọt dưới trần 8 s, **biên 0,6 s** | **Hỏng.** 2 nhân vật lý = đúng kịch bản `-t 2` đã đo: **p50 8 561 ms > 8 000 ms**, quá nửa số lời gọi quá hạn |

Hỏng ở đây không phải là sập: `slm_stage` thử lại đúng một lần rồi **lui về câu trả lời
sổ tay** — tức người dùng đợi tới **16 giây** để nhận đúng thứ mà bản tắt cờ đưa ra
trong ~100 ms.

**Một điểm giảm nhẹ, ghi cho công bằng.** Giải mã llama.cpp bị chặn ở **băng thông bộ
nhớ** chứ không ở IPC, nên khoảng cách giữa hai đời CPU **không** nhân lên tuyến tính —
bằng chứng là RK3588 (ARM, 4× A76 @ 2,4 GHz) cũng cho 12–18 tok/s, cùng khoảng với i7
`-t 4` (14,0). E5 v4 có 4 kênh DDR4 ở mức host nên băng thông tổng không tệ. Nhưng một
VM chỉ được **một lát** của nó, và hàng xóm ăn cùng băng thông đó. Nên "không tệ hơn
nhiều lần" là có cơ sở; "lọt dưới 8 giây" thì không ai hứa được.

**Kết luận cho nhân đời E5 v3/v4: để `SLM_ENABLED=false`** — cũng chính là mặc định của
`config.py:32` và là hình dạng ADR-006/ADR-010 mô tả. Mất đúng một thứ: câu dẫn tự
nhiên trước câu trả lời sổ tay. Không mất chức năng nào. Nếu vẫn muốn bật, ba đường
theo thứ tự nên thử: nới `SLM_TIMEOUT_S` (mục 22) — đổi "lỗi" lấy "chậm"; hoặc đổi
sang **0,5B** (cpu6 p50 1 135 ms, RAM 645 MB) và **kiểm lại chất lượng**, vì prompt ở
`src/agents/slm.py` được hiệu chỉnh cho 3B; hoặc đổi máy.

**Quan trọng hơn số lõi: đừng chọn gói "shared/burstable" rẻ nhất.** Loại đó cấp CPU
theo credit rồi bóp lại khi hết — mà một buổi demo chính là một đợt bùng. Có tuỳ chọn
"dedicated CPU" hoặc "high-frequency" thì trả thêm cho nó đáng hơn là mua thêm lõi.

**Tải lúc nghỉ gần như bằng không, nhưng lúc chạy thì không** — và phải đọc cả hai,
đọc một vế là sai. Đo trong container Linux 2026-08-20 bằng `cpu.stat` của cgroup:

| Chế độ | CPU |
|---|---|
| Nghỉ | **0,4% một nhân** (khớp mốc 0,24–0,65% đo trước đó) |
| Đang trả lời một câu sổ tay | **4–12 nhân**, trong ~0,5 giây |

Đợt bùng ấy là **TTS**, không phải RAG: Piper chiếm gần hết. Nhưng nó **bão hoà ở 4
luồng**, nên bốn nhân là đủ để không mất gì (bảng ở mục kế). **Con số này đo lúc
`slm_enabled=false`** — bật SLM thì thêm một đợt bùng nữa, dài vài giây và ăn hết số
luồng đặt ở `-t`. Xem `tech_stack.md` mục 4b để biết vì sao con số độ trễ ở đó phải
đọc kèm bối cảnh nguội/ấm.

#### Bão hoà ở 4 luồng — đo trên cả bốn thành phần

Đo 2026-08-20 trong container `python:3.11-slim`, i7-14650HX. **Phép đo tại chỗ, chưa
có run id** — muốn trích thành bằng chứng thì phải chạy lại qua script và ghi run.

| Thành phần | 1 luồng | 2 | **4** | 8 | 12 |
|---|---:|---:|---:|---:|---:|
| **Piper TTS** (câu trả lời 267 ký tự) | 1 369 ms | — | **490 ms** | — | 471 ms |
| **E5 embed** (1 câu truy vấn) | 24,3 ms | 17,7 ms | **14,5 ms** | 13,4 ms | **15,5 ms** ↑ |
| **Zipformer STT** | 41–58 ms | \- | \- | \- | \- (cố định 1 luồng, `voice.py:137`) |
| **llama.cpp 3B** (mục 18) | — | 9,2 tok/s | **14,0** | — | 13,1 ↓ |

Bốn dòng, cùng một hình dạng: **lên tới 4 thì đáng, quá 4 thì không, quá 8 thì âm.**
E5 ở 12 luồng *chậm hơn* ở 8; llama.cpp ở `-t 6` chậm hơn `-t 4`; TTS đổi 8 nhân lấy
4% thời gian.

**Hệ quả vận hành: hệ đang đốt 12 nhân để lấy tốc độ của 4.** Không có biến nào ghim
số luồng, nên ONNX Runtime tự lấy hết. Trên máy dev thì vô hại; trên VPS 4 nhân nó
không làm chậm một người dùng đơn lẻ, nhưng mỗi lượt TTS chiếm trọn máy. Ghim lại
trong `.env` (mục 9):

```
OMP_NUM_THREADS=4
```

### 1.2. Đối chiếu với một gói VPS thật — ví dụ FPT Cloud VPS 3

Trang bán VPS chỉ hiện vài dòng, và đúng là chỉ có bấy nhiêu để chọn. Đây là cách đọc
chúng ngược lại thành "đủ hay không đủ":

| Dòng trên trang bán | Con số | Kết luận |
|---|---|---|
| CPU | **4 vCPU** | **Đủ**, đúng mức khuyến nghị ở 1.1 |
| RAM | **4 GB + 1 GB = 5 GB** | **Đủ để chạy, kể cả có SLM 3B** — ~76–82%, trống 0,86–1,21 GB (bảng dưới). Chỗ chật là lúc **build** → làm mục 4.1 |
| Ổ cứng | **60 GB + 20 GB = 80 GB** | **Thừa nhiều.** Cả hệ **kể cả SLM và swapfile 4 GB** chỉ cần ~13–15 GB (bảng đĩa ở mục 1) |
| Dữ liệu truyền | Không giới hạn | Thừa |
| Băng thông | 300 Mbps | Thừa. Một lượt thoại là ~0,4 MB lên (WAV 16 kHz mono, tối đa 12 s) và ~0,5 MB xuống (WAV của TTS, mã hoá base64) |
| IPv4 | 1 | Đủ. Nhưng **vẫn phải có tên miền** — IP trần không xin được chứng chỉ, xem mục 0.1 |
| Datacenter | FPT, Việt Nam | Đúng lý do chọn VPS trong nước: độ trễ tới người demo |
| Anti-DDoS, uptime, support | — | Không ảnh hưởng quyết định kỹ thuật |

**Ngân sách RAM khi đã bật SLM** (gói 5 GB):

| Thành phần | RAM | Nguồn số |
|---|---:|---|
| Ubuntu 24.04 + Docker daemon | ~400 MB | ước lượng |
| 3 container backend | **1 208 MiB** | **đã đo** 2026-08-18, mốc `warm_voice` |
| `llama-server` **3B** q4_k_m, `-c 2048` | **2 109 MB** | **đã đo** 2026-08-19, mục 18 |
| `next start` | **138 MB** | **đã đo** 2026-08-19 (2 tiến trình node: 49,8 + 88,6) |
| Caddy | ~30 MB | ước lượng |
| **Tổng lúc chạy** | **3 885 MiB ≈ 3,79 GiB** | **~82%** nếu "5 GB" là thập phân (4 768 MiB), **~76%** nếu là 5 GiB |

#### Vì sao "đủ" — ba lý do, không phải một phép cộng

Cộng vài con số rồi thấy nhỏ hơn 5 GB thì chưa nói lên gì. Điều cần chứng minh là
**các con số đó không lớn lên**. Ba chỗ trong code bảo đảm chuyện đó:

**1. `1 208 MiB` là trần, không phải một mẫu ngẫu nhiên.** Cùng lần đo có ba mốc liên
tiếp, và chúng cho thấy đúng hình dạng của một đường cong bão hoà:

| Mốc | Tổng RAM 3 container | Vừa nạp thêm gì |
|---|---:|---|
| `idle` | 1 056,3 MiB | — |
| `warm_rag` | 1 109,3 MiB | torch + FAISS + embedder E5 |
| `warm_voice` | **1 207,7 MiB** | sherpa-onnx (STT) + piper (TTS) |

RAM chỉ tăng khi một model *lười nạp* được nạp lần đầu, và mỗi model chỉ nạp **đúng
một lần** vì mọi hàm nạp đều bọc `@lru_cache` (`voice.py:117` và `:205` cho STT/TTS,
`rag_node.py` cho E5). Sau mốc `warm_voice` thì **không còn gì nặng chưa nạp** — nên
đó là trần của tiến trình, không phải điểm giữa của một đường đang đi lên.

**2. Không thành phần nào cấp phát theo số người dùng.** Đây mới là câu hỏi thật, vì
"đủ cho một người" mà cứ thêm phiên là phình thì không dùng được. Trạng thái theo phiên
hoặc nằm trên đĩa, hoặc bị chặn trần cứng:

| Trạng thái | Nằm ở đâu / trần | Nguồn |
|---|---|---|
| users, sessions, approvals, idempotency | **SQLite**, không phải RAM | ADR-017, `src/db.py` |
| Trace cho màn hình kỹ sư | `BoundedCache(maxsize=200)` ×2 | `trace_store.py:143-145` |
| Bộ đệm phát lại của luồng tài xế | `deque(maxlen=200)` mỗi phiên | `ivi_events.py:31,47` |
| Audio TTS đẩy qua WS | `MAX_SPEECH_BYTES = 700 KiB`, `MAX_SPEECH_CHARS = 400` | `ivi_events.py:321,344` |

Không chỗ nào là "cứ thêm là lớn mãi". Mức tăng theo phiên là vài chục KB, không phải
vài chục MB.

**3. `2 109 MB` của llama-server cũng là trần, vì lý do khác.** `-c 2048` (mục 21) **cố
định kích thước KV cache ngay lúc khởi động** — trọng số q4 là 2,0 GB, phần còn lại là
cache đã cấp phát sẵn. Nó không lớn lên theo số lượt gọi. Con số đó là **đỉnh working
set đo qua ba cấu hình luồng** (mục 18), và nó khớp với `server_peak_rss_mb = 1 903 MB`
mà SPIKE-003 ghi độc lập.

**Và `138 MB` của `next start` là số đo, không phải ước lượng nữa** — hai tiến trình
node, 49,8 + 88,6 MB, sau khi đã tải cả ba trang `/login`, `/driver`, `/engineer`.

Cộng lại: **3 885 MiB ≈ 3,79 GiB trên 5 GB, còn trống 0,86–1,21 GB**. Phần trống đó
không phí — Linux dùng làm page cache, đúng thứ khiến lần chạy thứ hai nhanh hơn lần đầu.

#### Vì sao 4 vCPU đủ, dù SLM nằm trên đường tới hạn

**Đường tới hạn là tuần tự.** Trong một lượt thoại: STT → định tuyến → SLM → an toàn →
thực thi → TTS. **Không có hai chặng nào chạy cùng lúc.** Nên câu hỏi không phải "đủ lõi
cho STT *cộng* SLM chưa" mà là "đủ lõi cho chặng nặng nhất chưa".

Và chỉ có **đúng một** chặng biết dùng nhiều lõi:

| Chặng | Dùng mấy lõi | Nguồn |
|---|---|---|
| STT (sherpa-onnx) | **1** — `num_threads=1` | `voice.py:137` |
| Định tuyến | không đáng kể — 0,055 ms | đo |
| **SLM (llama-server)** | **`-t`, đặt tay** | mục 21 |
| Soạn câu trả lời | thao tác chuỗi | `compose.py` |

Nên `-t 2` cho llama-server, còn 2 vCPU cho backend + Caddy + Next + Docker, là đã phủ
được khoảnh khắc bận nhất. Tải trung bình đo được là **0,24–0,65% CPU** — máy này rảnh
và bùng từng đợt, không phải máy tải nặng liên tục.

#### "Đủ" ở đây nghĩa là gì — và không nghĩa là gì

**Có nghĩa:** đủ cho **một phiên, một người nói**, đúng phạm vi P0 và đúng hình dạng
buổi demo. Mọi số ở trên đều đo ở trạng thái đó.

**Không có nghĩa:** đủ cho nhiều người dùng đồng thời. `voice.py:97` và `:192` đặt
`threading.Lock` toàn cục quanh STT và TTS, nên **mỗi lúc đúng một lượt thoại** — người
thứ hai xếp hàng chứ không chạy song song. Đó là giới hạn **thông lượng**, và thêm RAM
hay thêm lõi đều không gỡ được. Xem `deploy_platform_choice.md` mục 9.

**Một thứ duy nhất lớn dần theo thời gian: cache build của Docker.** Trên máy dev nó đã
là **27,61 GB** (`docker system df`). Với 80 GB thì còn lâu mới chạm, nhưng đó là lý do
mục 25 có `docker builder prune`. Log thì đã chặn ở mục 5.



#### Kiểm kê đĩa — toàn bộ những gì sẽ nằm trên máy

Đo trên máy dev, không ước lượng, trừ các dòng ghi rõ là ước lượng:

| Khoản | Dung lượng | Nguồn |
|---|---:|---|
| Ubuntu 24.04 sau `apt upgrade` | ~2,5 GB | ước lượng |
| Docker engine | ~500 MB | ước lượng |
| **Image `backend` + `vehicle-simulator`** | **~3,8 GB** | **đo** — hai service **build từ cùng `Dockerfile` và cùng context**, nên chung layer, **không phải 2×** |
| Image `eclipse-mosquitto:2` | 36 MB | **đo** |
| Cache build sau lần build đầu | ~2–4 GB | ước lượng — dọn bằng mục 25 |
| Node 22 + npm | ~150 MB | ước lượng |
| `frontend/node_modules` | **633 MB** | **đo** |
| `frontend/.next` | **249 MB** | **đo** |
| `models/voice` (STT + TTS) | **89 MB** | **đo** |
| `data/rag` (chunk store + FAISS) | **2 MB** | **đo** |
| `qwen2.5-3b-instruct-q4_k_m.gguf` | **2 007 MB** | **đo**: 2 104 932 768 byte |
| llama.cpp `b10358` | ~300 MB | ước lượng |
| Caddy | ~50 MB | ước lượng |
| **Swapfile** (mục 4.1) | **4 096 MB** | |
| **Tổng** | **≈ 17–19 GB** | **trên 80 GB → dùng ~23%** |

Ba điều làm con số này nhỏ hơn người ta tưởng:

- **Thư viện Python nặng nằm trong image, không nằm trên host.** `torch`, `faiss`,
  `sherpa-onnx`, `piper` cộng lại là **1 764 MB** ở `/home/appuser/.local` bên trong
  image, cộng **471 MB** cache embedder E5 ở `/opt/hf` (đo bằng `du` trong container).
  Chúng được tính **một lần** trong dòng image ở trên — không cài lại trên máy chủ,
  không đếm hai lần.
- **`backend` và `vehicle-simulator` dùng chung image.** `docker-compose.yml` dòng
  50–52 và 97–99 trỏ cùng `Dockerfile`, cùng `context: .`.
- **`data/manuals` (154 MB) không lên VPS.** Nó bị `.gitignore` chặn (dòng 39) nên
  `git clone` không kéo về, và mục 8 cũng không `scp` nó — VPS chỉ cần **chỉ mục đã
  dựng sẵn** (`data/rag`, 2 MB), không cần tài liệu nguồn. Chỉ khi nào phải `ingest`
  lại trên chính VPS mới cần gửi nó lên.

**Chỗ duy nhất chật là lúc build**, và nó chỉ xảy ra một lần. `next build` đỉnh **đo
được 1 173 MB**, còn lúc chạy chỉ trống 0,86–1,21 GB — tức **thiếu khoảng 100–300 MB**.
Không nhiều, nhưng vẫn phải xử lý:

1. Tạo swap 4 GB — **mục 4.1**, làm trước mọi thứ khác.
2. Dừng **một** dịch vụ trước khi `npm run build`, cái nào cũng được:
   `docker compose stop backend` (giải phóng 1 208 MB, **mục 14**) **hoặc**
   `sudo systemctl stop vivi-slm` (giải phóng 2 109 MB, **mục 21**). **Không cần cả hai.**

> Trên VPS 4 vCPU đỉnh này nhiều khả năng **thấp hơn** 1 173 MB: con số đo trên máy 16
> nhân, nơi Next mở tới **17 tiến trình node** song song. Ít nhân thì ít worker.

#### Năm thứ trang bán hàng không nói, phải tự kiểm sau khi máy được tạo

```bash
lscpu | grep -E "Model name|^CPU\(s\)|Thread|Core\(s\)|Socket"
```

```bash
free -h && df -h /
```

```bash
vmstat 1 5
```

1. **vCPU là dedicated hay shared/burst?** Trang bán không nói. Cột `st` (steal time)
   trong `vmstat` mà liên tục lớn hơn 0 nghĩa là máy đang bị hàng xóm giành CPU — đúng
   thứ mục 1.1 dặn tránh. Kiểm lúc máy rảnh và kiểm lại lúc chạy demo thử.
2. **Bao nhiêu nhân *vật lý*?** `Core(s) per socket` × `Socket(s)`. Rất nhiều gói
   "4 vCPU" thật ra là **2 nhân × 2 luồng**. Con số này quyết định cờ `-t` của
   `llama-server` ở mục 21 — SPIKE-003 đo được cpu12 **chậm hơn** cpu6, nên đặt `-t`
   bằng số luồng là tự làm chậm mình.
3. **Ảnh hệ điều hành.** Chọn **Ubuntu 24.04 LTS**. Runbook này viết cho nó (NodeSource
   setup_22.x ở mục 6, `get.docker.com` ở mục 5, đường dẫn systemd ở mục 15 và 21).
4. **Có swap sẵn không?** Phần lớn ảnh cloud là **không** — `free -h` cột `Swap` bằng 0.
   Xem mục 4.1.
5. **Snapshot/backup có tính phí riêng không?** Không ảnh hưởng lúc chạy, nhưng một
   snapshot sau khi cài xong là thứ rẻ nhất bạn mua được trước ngày demo.

**Một khối chép-dán, in thẳng ra kết luận.** Chạy ngay sau khi máy được tạo, trước khi
cài gì:

```bash
echo "== CPU =="; lscpu | grep -E "Model name|^CPU\(s\)|Thread\(s\) per core|Core\(s\) per socket|Socket\(s\)"; \
PHYS=$(( $(lscpu | awk -F: '/Core\(s\) per socket/{print $2}') * $(lscpu | awk -F: '/^Socket\(s\)/{print $2}') )); \
echo "-> nhan VAT LY = $PHYS  (dat -t bang so nay o muc 21)"; \
[ "$PHYS" -ge 4 ] && echo "-> du nhan cho SLM 3B (van phai do lai, muc 24)" || echo "-> KHONG du nhan cho SLM 3B: -t 2 da do p50 8561ms > tran 8000ms -> de SLM_ENABLED=false"; \
echo "== steal time (5 giay) =="; vmstat 1 5 | awk 'NR==2{for(i=1;i<=NF;i++) if($i=="st") c=i} NR>2{print "st="$c}'; \
echo "-> st > 0 lien tuc = hang xom dang gianh CPU"; \
echo "== RAM / dia / swap =="; free -h; df -h /
```

Cố ý viết **không dấu** trong phần `echo`: một số ảnh cloud tối giản chưa đặt locale
UTF-8, và output tiếng Việt sẽ ra ký tự hỏng đúng lúc đang cần đọc.

Khối này chỉ trả lời được **hai** trong năm câu hỏi trên (nhân vật lý, steal time) —
ba câu còn lại là chuyện của trang quản trị, không có lệnh nào hỏi hộ.

> **Đừng chép số độ trễ của SPIKE-003 sang máy này.** `cpu6` ở mục 18 là 6 luồng của
> một CPU laptop. Nhân VPS thường chậm hơn mỗi lõi và chia sẻ băng thông bộ nhớ, mà
> giải mã của llama.cpp thì bị chặn ở băng thông bộ nhớ. Khoảng cách bao nhiêu thì
> **chưa ai đo** — mục 24 là bước bắt buộc đo lại trên chính máy này trước khi trích
> bất kỳ con số nào.

### 1.3. Chốt: thuê gì, và bày ở đâu

Tổng hợp mọi số ở trên thành một quyết định. **Thuê đúng MỘT máy CPU VPS.** Không
thuê GPU VPS, và không thuê cả hai.

| Hạng mục | Chốt | Vì sao |
|---|---|---|
| Số máy | **1** | Xem "Vì sao không tách hai máy" bên dưới |
| CPU | **4 nhân *vật lý*, dedicated, đời mới** (Xeon Gold / EPYC 7xx2+ / Ryzen) | Cả bốn thành phần đều bão hoà ở 4 luồng (mục 1.1). Quá 4 là tiền vứt đi; dưới 4 là hỏng |
| Tránh | **Xeon E5 v3/v4, gói shared/burstable** | `-t 2` trên nhân **2024** đã hỏng 2/8 lời gọi planner |
| RAM | **5 GB** nếu bật SLM 3B, **4 GB** nếu tắt | Đo: 3,79 GiB / 1,74 GiB |
| Đĩa | **30 GB** (SLM bật) / 25 GB (tắt) | Gồm swapfile 4 GB |
| Swap | **4 GB, làm trước** | Lưới chống OOM lúc `next build` |
| GPU | **Không** | `torch` là bản `+cpu`, ORT chỉ có `CPUExecutionProvider` — card gắn vào cũng nằm không, trừ SLM |

**Vì sao không tách "CPU VPS + GPU VPS".** Nghe hợp lý nhưng hỏng ba thứ cùng lúc:
`slm_endpoint` mặc định là `127.0.0.1:8093` vì cả hệ giả định llama-server **cùng
máy**; trỏ nó qua Internet là một cuộc gọi mạng lúc chạy, đúng thứ ADR-001 cấm; và
cổng 8093 **không có xác thực** vì nó được thiết kế để chỉ nghe loopback.

**Vì sao không "GPU VPS thôi".** Không phải sai về kỹ thuật — GPU đo được **2 215 ms
so với 5 329 ms** (mục 18), một khoảng cách thật. Nhưng mục 19 cài asset **CPU Linux**;
chạy GPU cần build **CUDA** của llama.cpp, không có trong runbook này, chưa ai thử.
Đắt hơn nhiều lần, và loại rẻ thường đặt ở nước ngoài — mất đúng lý do chọn VPS trong
nước.

#### Nếu bắt buộc demo với `SLM_ENABLED=true` và 3B

Tách **sân khấu** khỏi **link công khai**. Cả hai đều `true`, đều 3B — chỉ khác thiết bị:

| | Chạy ở đâu | Số đo |
|---|---|---|
| **Buổi trình bày trực tiếp** | Máy có dGPU (`-Device "RTX 4050"`) | planner **2 215 ms**, câu dẫn **1 110 ms**, 0/12 quá trần |
| **Link công khai cho BTC** | CPU VPS, `-t 4` | planner **5 329 ms**, câu dẫn **3 173 ms**, 0/12 quá trần |

Nói thẳng cả hai con số khi trình bày. *"Cùng model, hai lớp phần cứng, hai kết quả"*
là một slide mạnh hơn một con số đẹp không nói rõ chạy ở đâu — và nó khớp với việc
ADR-005 vẫn ghi **"Not Yet"** cho lựa chọn model.

Nếu VPS chỉ có 2 nhân vật lý thì đặt **`SLM_TIMEOUT_S=15.0`** (mục 22) và nhớ: mỗi
lượt hỏng tốn **hai** lần timeout, tức ca xấu nhất 30 giây.

## 2. Kiến trúc sau khi gộp

```
                    Internet
                       │  443 (HTTPS + WSS, Let's Encrypt)
                  ┌────▼─────┐
                  │  Caddy   │   một site block, định tuyến theo path
                  └──┬────┬──┘
       /api/v1/*     │    │     mọi path còn lại
       /ws/*         │    │
       /healthz      │    │
              ┌──────▼─┐  └──▼──────────────┐
              │backend │     │ Next.js      │  systemd, 127.0.0.1:3000
              │ :8000  │     │ next start   │
              └───┬────┘     └──────────────┘
        docker compose (chỉ bind 127.0.0.1)
     ┌────────────┼────────────┐
   mqtt      vehicle-sim    backend
```

Backend và frontend **đều chỉ nghe loopback**. Chỉ Caddy mở ra Internet.

**Điểm bất đối xứng đáng biết:** `frontend/` **nằm trọn trong git** — không có artifact
ngoài git như backend. Nên phần frontend chỉ cần `git clone` + `npm ci` + `npm run build`
ngay trên VPS, không phải `scp` gì cả.

> Muốn có trải nghiệm kiểu Vercel ngay trên máy này (đẩy git là tự build, có UI) thì
> dùng **Coolify** thay cho mục 16 (Caddy) và mục 15 (systemd) — nhưng riêng nó ăn
> tối thiểu 2 GB RAM nên bắt buộc máy 8 GB. Xem `deploy_platform_choice.md` mục 11.3.

### 2.1. Bản đồ toàn bộ quy trình — và chỗ nào đổi nếu máy có GPU

Dùng làm danh sách kiểm. **22 trong 24 mục giống hệt nhau**; chỉ mục 19 và 21 đổi, cộng
một bước driver có trước tất cả.

| Phần | Mục | Việc | CPU VPS — **đường chuẩn** | GPU VPS — khác gì |
|---|---:|---|---|---|
| — | — | Driver | *(không có)* | ⚠️ **Cài driver NVIDIA, `nvidia-smi` phải chạy** |
| **I** | 0 | Tên miền + A record, khoá SSH | trỏ A record trước tiên | giống |
| | 1 | Chọn máy | 4 nhân vật lý · 5 GB RAM · 30 GB đĩa | **RAM vẫn giữ nguyên** (xem 2.2), **cộng thêm** ≥4 GB **VRAM** |
| | 2 | Đọc kiến trúc | Caddy → backend `:8000` + Next `:3000` | giống |
| **II** | 3 | Kiểm 4 model bằng checksum | `Get-FileHash` đối chiếu `.sha256` | giống |
| **III** | 4 | User, `ufw` 80/443, **swap 4 GB** | `fallocate -l 4G /swapfile` | giống |
| | 5 | Docker | `curl get.docker.com \| sudo sh` | **+ `nvidia-container-toolkit`** nếu llama-server chạy trong Docker |
| | 6 | Node 22 | NodeSource `setup_22.x` | giống |
| | 7 | Mã nguồn | `git clone` vào `/opt/vivi` | giống |
| | 8 | Artifact ngoài git | `scp models/`, `data/rag/` | giống |
| **IV** | 9 | `.env` | 4 dòng + `OMP_NUM_THREADS=4` | giống |
| | 10 | `passwd` Mosquitto | `mosquitto_passwd` cho 2 identity | giống |
| | 11 | Bind loopback | file override `127.0.0.1:8000` | giống |
| | 12 | Dựng backend | `docker compose build && up -d --wait` | giống — image vẫn `torch+cpu` |
| **V** | 13 | 6 biến `NEXT_PUBLIC_*` | **build-time**, sửa là phải build lại | giống |
| | 14 | Build frontend | `npm ci && npm run build` (dừng 1 dịch vụ) | giống, và **đỡ chật hơn** |
| | 15 | Chạy frontend | **systemd** `next start` | ⚠️ nhà cho thuê chỉ cho container thì không có systemd |
| **VI** | 16 | Caddy | một site block, Let's Encrypt tự động | giống |
| | 17 | Kiểm chứng | 4 kịch bản §3.3 + hâm nóng | giống |
| **VII** | 18 | Chọn model | `qwen2.5-3b-instruct-q4_k_m` | giống |
| | **19** | **Cài llama.cpp** | asset **`ubuntu-x64`** (CPU), `b10358` | ⚠️ **asset CUDA**, hoặc build `-DGGML_CUDA=ON`. **Khác backend**, không chỉ khác thiết bị |
| | 20 | Đưa model 3B lên | `scp` 2,0 GB + `.sha256` | giống |
| | **21** | **systemd llama-server** | **`-ngl 0 -t 4`** | ⚠️ **`-ngl 99`**; `-t` gần như vô nghĩa |
| | 22 | Bật cờ | `SLM_ENABLED=true` | giống |
| | 23 | Kiểm chứng SLM | `/healthz` → `llm: ready` | giống |
| | 24 | **Đo lại trên máy đích** | bắt buộc | bắt buộc **hơn** — đổi backend thì số cũ vô giá trị |

**Vì sao ít khác đến vậy:** GPU chỉ chạm đúng **một tiến trình**. `llama-server` nằm
ngoài `docker-compose.yml`, nói chuyện với backend qua HTTP `127.0.0.1:8093`, và backend
không biết nó chạy trên gì. Ba container còn lại bị đóng đinh vào CPU ngay từ
`Dockerfile:18` (`torch` cài từ index CPU-only) nên chúng chạy y hệt nhau ở cả hai loại máy.

**Nhưng hai mục đổi lại là hai mục chưa ai trong nhóm đi qua.** Đường CPU thì runbook
này viết tới từng lệnh; đường CUDA thì chưa. Với lịch gấp, dựng CPU trước rồi thử CUDA
như phần thêm — không phải phần thay thế.

### 2.2. VRAM **không** thay thế RAM — hai ngân sách rời nhau

Sai lầm dễ mắc khi đọc bảng trên: tưởng bật GPU thì 2 GB của model rời khỏi RAM sang
VRAM, nên máy 4 GB RAM là đủ. **Không phải.** Đo 2026-08-20, llama-server chạy
`-ngl 99` trên RTX 4050 (Vulkan, Windows):

| | Giá trị |
|---|---|
| **VRAM** chiếm | **2 412 MiB** (nghỉ 421 MiB → model ~2,0 GB) |
| **RAM hệ thống** vẫn chiếm | **WorkingSet 1 936 MB · PrivateBytes 2 241 MB** |

Tức bật GPU là **cộng thêm** một ngân sách, không phải chuyển ngân sách. Trọng số nằm
ở VRAM để tính, nhưng tiến trình vẫn giữ một bản trên RAM.

> Số này đo trên **Vulkan/Windows**. Backend **CUDA trên Linux** có thể khác — llama.cpp
> mmap file GGUF nên một phần có thể là page cache thu hồi được. **Chưa đo.** Cho tới
> khi đo, hãy quy hoạch theo hướng an toàn: **RAM giữ nguyên như bảng mục 1, VRAM là
> khoản cộng thêm.**

Ba hệ quả khi quy hoạch máy:

- **Không quy đổi được cho nhau.** 16 GB RAM không cứu được một card 2 GB VRAM, và
  ngược lại. Phải thoả **cả hai** ngưỡng.
- **VRAM tràn thì không có swap.** RAM tràn còn rơi vào swapfile 4 GB (mục 4.1) — chậm
  nhưng sống. VRAM tràn thì llama.cpp hoặc không cấp phát nổi, hoặc **lặng lẽ** offload
  một phần layer và tụt về tốc độ gần CPU mà không báo gì.
- **`-c` lái VRAM.** 2 412 MiB là với `-c 2048` (mục 21). Nới ngữ cảnh là nới KV cache,
  và con số này hết đúng.

Trên **CPU VPS thì VRAM bằng không và không liên quan** — toàn bộ 2 109 MB của
llama-server nằm trong RAM, đúng như bảng ngân sách ở mục 1.2.

---

# PHẦN II — MÁY WINDOWS

## 3. Kiểm artifact trước khi gửi đi

### 3.0. Bốn model trong hệ — đối chiếu từ file, không từ trí nhớ

| # | Vai trò | Model chính xác | Nguồn upstream (đã ghim) | Kích thước | Giấy phép | Đi lên VPS bằng cách nào |
|---|---|---|---|---:|---|---|
| 1 | **STT** | `zipformer-30m-rnnt-6000h` — encoder/decoder/joiner `.int8.onnx` + `tokens.txt` | `hynt/Zipformer-30M-RNNT-6000h` @ `24ed3024…` | **30,1 MB** | **CC-BY-NC-ND-4.0** | `scp` (mục 8) → nướng vào image |
| 2 | **TTS** | `vi_VN-vais1000-medium`, đổi tên thành `vi_VN-piper.onnx` | `rhasspy/piper-voices` @ `3d796cc2…` | **63,2 MB** | MIT | `scp` (mục 8) → nướng vào image |
| 3 | **Embedder RAG** | `intfloat/multilingual-e5-small` | ghim `E5_REVISION=614241f6…` trong `Dockerfile:40` | **471 MB** cache | MIT | **tự tải lúc `docker build`**, không `scp` |
| 4 | **SLM** | `qwen2.5-3b-instruct-q4_k_m` ← **mặc định hiện tại** (`config.py:34`) | `Qwen/Qwen2.5-3B-Instruct-GGUF` @ `7dabda4d…` | **2,0 GB** | **Qwen Research** | **KHÔNG dùng bản này trên VPS** — xem mục 18 |

**Ba thứ trông giống model nhưng không phải:**

- **BM25** (`src/rag/bm25.py`) là một **công thức ~40 dòng**, không có trọng số. Hybrid
  Search (RRF) không thêm model nào vào hệ.
- **VAD ở trình duyệt** là năng lượng RMS thuần (`createSpeechEnergyTracker`), không
  model — `frontend/package.json` không có `onnxruntime` hay `transformers`.
- **`frontend/public/assets/models/sedan-realistic/scene.gltf`** là model **3D**, không
  phải ML.

Và **không có reranker / cross-encoder** nào trong hệ.

> **Một đường chết cần biết để không nhầm:** `src/config.py:26` khai
> `model_name = "gpt-4o-mini"` và `src/services/llm.py` dựng `ChatOpenAI(...)`. Nhưng
> `get_llm` **không có nơi nào gọi** (grep toàn repo chỉ ra đúng dòng định nghĩa) — đây
> là boilerplate còn sót của môn học, không phải một cuộc gọi đám mây. Dù vậy
> `langchain-openai>=0.3.0` **vẫn nằm trong `pyproject.toml:21`** nên vẫn được cài vào
> image và vẫn tính vào 1 764 MB thư viện.

> **Giấy phép STT là `CC-BY-NC-ND-4.0`** — phi thương mại, **không cho phái sinh**.
> Đây là lý do image **không được đẩy lên registry công khai**, và cũng là lý do
> `models/` nằm ngoài git.

### 3.1. Kiểm file trước khi gửi

> PowerShell, tại thư mục gốc repo trên máy Windows.

Sáu file voice — thiếu một cái là `docker build` fail ở chốt chặn trong `Dockerfile`:

```powershell
Get-ChildItem models\voice\vi_VN-piper.onnx, models\voice\vi_VN-piper.onnx.json, models\voice\zipformer-30m-rnnt-6000h\encoder.int8.onnx, models\voice\zipformer-30m-rnnt-6000h\decoder.int8.onnx, models\voice\zipformer-30m-rnnt-6000h\joiner.int8.onnx, models\voice\zipformer-30m-rnnt-6000h\tokens.txt | Select-Object Name, Length
```

Index RAG:

```powershell
Get-ChildItem data\rag\vf9_2026_vi | Select-Object Name, Length
```

Đối chiếu checksum với file `.sha256` được track trong git (đây là lý do chúng tồn tại):

```powershell
Get-FileHash -Algorithm SHA256 models\voice\zipformer-30m-rnnt-6000h\encoder.int8.onnx
```

```powershell
Get-Content models\voice\zipformer-30m-rnnt-6000h\encoder.int8.onnx.sha256
```

Hai chuỗi phải khớp. Không khớp thì đừng gửi lên — tải lại model trước.

---

# PHẦN III — DỰNG VPS

## 4. Tài khoản và tường lửa

> Từ đây tới hết mục 16 là **bash trên VPS**, trừ khi ghi rõ khác. Đăng nhập bằng root
> lần đầu.

```bash
adduser --disabled-password --gecos "" vivi
```

```bash
usermod -aG sudo vivi
```

```bash
rsync --archive --chown=vivi:vivi ~/.ssh /home/vivi/
```

```bash
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

> **Cảnh báo:** `ufw` **không** chặn được cổng do Docker publish — Docker ghi thẳng
> rule vào chain `DOCKER` của iptables, đứng trước rule của ufw. Đó là lý do mục 10
> dùng file override để ép backend chỉ bind `127.0.0.1`. Đừng dựa vào ufw để giấu
> cổng 8000. (Cổng 3000 của Next thì ufw chặn được, vì đó là tiến trình thường —
> nhưng mục 12.3 vẫn bind loopback cho chắc.)

### 4.1. Swap — làm trước, không phải khi đã hết RAM

Ảnh cloud thường không có swap. Kiểm:

```bash
free -h
```

Cột `Swap` bằng `0B` thì tạo 4 GB (bỏ qua nếu đã có):

```bash
sudo fallocate -l 4G /swapfile
```

```bash
sudo chmod 600 /swapfile
```

```bash
sudo mkswap /swapfile && sudo swapon /swapfile
```

```bash
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

```bash
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-vivi-swap.conf && sudo sysctl -p /etc/sysctl.d/99-vivi-swap.conf
```

```bash
free -h
```

Hai điều phải hiểu đúng về khối này:

- **Swap ở đây là lưới an toàn chống OOM lúc build, không phải RAM cộng thêm.** Nếu một
  lượt thoại lúc demo mà phải chạm swap thì độ trễ hỏng hẳn — mà `swapfile` trên SSD
  vẫn chậm hơn RAM hàng trăm lần. `vm.swappiness=10` là để nhân hệ điều hành đừng đẩy
  tiến trình đang rảnh ra swap khi RAM còn trống.
- **Nó ăn 4 GB đĩa.** Với 80 GB thì không đáng kể; với gói 25 GB thì tính vào.

## 5. Docker và cấu hình daemon

```bash
curl -fsSL https://get.docker.com | sudo sh
```

```bash
sudo usermod -aG docker vivi
```

Xoay vòng log — **không bỏ qua bước này**. Xe ảo phát heartbeat mỗi 5 giây và để
`restart: unless-stopped`, nên log sẽ phình cho tới lúc đầy đĩa:

```bash
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "no-new-privileges": true
}
EOF
```

```bash
sudo systemctl restart docker
```

**Đăng xuất và SSH vào lại bằng user `vivi`** để nhóm `docker` có hiệu lực. Mọi lệnh
từ đây chạy dưới `vivi`.

## 6. Node 22 cho frontend

Next 16.3.0 cần Node 20 trở lên; Ubuntu 24.04 mặc định có Node 18 — **không đủ**.
Máy dev đang chạy Node v22.19.0 / npm 10.9.3, dùng đúng dòng đó:

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
```

```bash
sudo apt install -y nodejs
```

```bash
node -v && npm -v
```

## 7. Lấy mã nguồn

> **Kiểm nhánh trước khi clone — tính tới 2026-08-20 `develop` chưa dùng được.**
> PR #214 (`Dockerfile` cài thêm `requirements-rag.txt` + `requirements-voice.txt`, nướng
> sẵn cache E5) **vẫn đang mở**, chưa merge. Clone `develop` trần thì `docker compose
> build` ở mục 12 vẫn **xanh**, container vẫn `healthy`, nhưng `/healthz` báo `stt`/`tts`
> = `down` và mọi câu tra sổ tay trả về *"Tôi không tìm thấy thông tin này trong sổ tay
> xe."* — đúng ba lỗi "build xanh rồi hỏng sau" mà PR đó sinh ra để chặn.
>
> Kiểm bằng chính repo, đừng tin dòng này (nó chỉ đúng tại ngày viết):
>
> ```bash
> git ls-remote --heads origin
> ```
>
> Trên máy Windows đã có repo thì kiểm thẳng nội dung — **không in ra dòng nào** nghĩa
> là `develop` chưa có PR:
>
> ```powershell
> git fetch origin
> ```
>
> ```powershell
> git show origin/develop:Dockerfile | Select-String -Pattern requirements-voice
> ```

```bash
sudo mkdir -p /opt/vivi && sudo chown vivi:vivi /opt/vivi
```

**Đừng clone thẳng nhánh của PR #214.** Đo 2026-08-20:

```
git rev-list --count origin/feat/issue-184-deploy-image..origin/develop  →  37
git rev-list --count origin/develop..origin/feat/issue-184-deploy-image  →   1
```

Nhánh đó **thiếu 37 commit** của `develop` (PR #190, #209, #211, #216… — tự chuyển màn
theo giọng, thanh trượt tốc độ, mic chờ duyệt, đọc câu hỏi duyệt thành tiếng), còn
`develop` chỉ thiếu **đúng một** commit: `99e7128`, cái `Dockerfile`. Deploy nhánh 184
trần là demo một bản frontend cũ hàng chục commit.

Thứ cần deploy là **`develop` + đúng commit đó**. Hai đường, đều đúng:

- **Merge PR #214 trước** → `develop` là bản deploy chuẩn, `git clone -b develop` như
  bình thường, không phải nghĩ gì thêm.
- **Gộp cục bộ, không chờ ai** → nhánh chỉ nằm trên máy bạn, rồi đi **mục 7.1 / B1** để
  đưa lên VPS. Đã thử khô: **0 xung đột**.

  ```powershell
  git checkout -b deploy-<ngày> origin/develop
  ```

  ```powershell
  git merge origin/feat/issue-184-deploy-image
  ```

  Kiểm — phải in ra một dòng:

  ```powershell
  git show HEAD:Dockerfile | Select-String requirements-voice
  ```

**Cách tự kiểm về sau**, khi các con số ở trên đã cũ. Câu hỏi đúng không phải "nhánh nào
mới nhất" mà là **"nhánh tôi định deploy có bị bỏ lại sau `develop` không"**:

```powershell
git rev-list --count <nhánh-định-deploy>..origin/develop
```

`0` = nhánh đó đã có mọi thứ `develop` có → deploy được. Số lớn = nó cũ, đừng deploy.

Khi nhánh đã đúng (`develop` đã có commit `Dockerfile`), clone như bình thường — đây là
**bash trên VPS**:

```bash
git clone -b develop https://github.com/AI20K-Build-Phase-Cohort-3/P-192.git /opt/vivi
```

> Repo là **private**. Lệnh này sẽ hỏi tài khoản; xem mục 7.1 bước 2–3 để biết mình đang
> vướng ở đâu và chữa thế nào. Nếu chọn đường **gộp cục bộ** ở trên thì bỏ qua lệnh này —
> nhánh đó chưa có trên GitHub, nó đi bằng **B1**.

Lúc này repo **chưa chạy được** — thiếu model và index.

**Không clone được?** → mục 7.1.

### 7.1. Nếu không dùng được GitHub

> **Trạng thái: chưa kiểm chứng.** Ba đường dưới đây đối chiếu vào `.gitignore`,
> `.dockerignore` và `docker-compose.yml` của repo, nhưng **chưa ai chạy trọn đường
> nào trên VPS thật** — xem mục 28.

`docs/tech_stack.md` mục 6a đã trả lời câu hỏi nguyên tắc: **không bước deploy nào bắt
buộc đi qua GitHub.** Không có workflow nào deploy hộ, và hai workflow hiện có
(`ci.yml`, `mqtt-contract.yml`) chỉ chạy test trên self-hosted runner của BTC. `git
clone` ở mục 7 là lựa chọn cho tiện, không phải ràng buộc.

Nhưng **"GitHub không được" có ba nghĩa khác nhau**, và ba cách chữa khác nhau. Xác
định đúng cái nào trước khi gõ lệnh — chữa nhầm ca là mất hàng giờ tải file vô ích:

| Triệu chứng thật sự | Đường | Phải chuyển bao nhiêu byte |
|---|---|---|
| `git clone` hỏi mật khẩu / `Authentication failed` (repo private, chưa có PAT hay deploy key) | **B1** | **66 MB** + 91 MB artifact |
| `git clone` treo hoặc `Could not resolve host: github.com` | **B1** (hoặc **B2** nếu cần cả file chưa commit) | như trên |
| `docker compose build` chết ở `pip install` hoặc ở `snapshot_download` (chặn PyPI / Hugging Face), hoặc máy quá yếu để build | **B3** | **~2,6 GB** |

#### Bốn lệnh xác định mình đang ở ca nào

> **bash trên VPS** — không phải trên máy Windows. Máy bạn đương nhiên vào được GitHub;
> đó không phải câu hỏi đang hỏi.

**1. Mạng có tới được GitHub không?**

```bash
curl -sS -m 10 -o /dev/null -w '%{http_code}\n' https://github.com
```

**2. Có quyền đọc repo không?** Repo `P-192` là **private**, nên lệnh này thất bại là
chuyện bình thường trên máy chưa đăng nhập — nó không đồng nghĩa "mạng hỏng":

```bash
GIT_TERMINAL_PROMPT=0 git ls-remote https://github.com/AI20K-Build-Phase-Cohort-3/P-192.git
```

`GIT_TERMINAL_PROMPT=0` là phần quan trọng: thiếu nó, lệnh **ngồi đợi bạn gõ mật khẩu**
thay vì trả lời câu hỏi.

| Lệnh 1 | Lệnh 2 | Kết luận |
|---|---|---|
| `200` | in ra SHA + tên nhánh | **Dùng được** — quay lại mục 7 |
| `200` | `could not read Username` / `Authentication failed` | Mạng OK, **chưa có quyền**. Gắn deploy key (dưới) hoặc đi **B1** |
| treo / `Could not resolve host` | (không cần chạy) | Mạng chặn → **B1**, hoặc **B2** nếu cần cả file chưa commit |

**3. Muốn chữa thay vì đi đường vòng.** Ba loại "khoá" của GitHub tên na ná nhau nhưng
không thay thế nhau được — chọn nhầm là mất thời gian ở một trang bạn không có quyền mở:

| Loại | Gắn với | Ai tạo được | Mở được gì |
|---|---|---|---|
| SSH key cá nhân | **tài khoản** | bạn | mọi repo bạn có quyền |
| **Deploy key** | **một repo** | **chỉ admin của repo đó** | đúng repo đó |
| PAT (token) | **tài khoản** | bạn | mọi repo bạn có quyền, có hạn |

> **Thành viên nhóm không phải admin của `P-192`** — repo thuộc org của BTC. Kiểm bằng
> lệnh dưới; `"admin": false` nghĩa là **Settings → Deploy keys sẽ không mở được**, và
> `gh repo deploy-key list` trả `HTTP 404` (GitHub trả 404 thay cho 403 để không lộ sự
> tồn tại của repo). Đo trên tài khoản `hason0510`, 2026-08-20.
>
> ```bash
> gh api repos/AI20K-Build-Phase-Cohort-3/P-192 --jq .permissions
> ```

Nên đường khả thi cho thành viên thường là một trong hai cái sau — **không phải deploy
key**:

- **`gh auth login` trên VPS** (không phải tạo token tay):

  ```bash
  sudo apt install -y gh
  ```

  ```bash
  gh auth login
  ```

  Chọn *GitHub.com* → *HTTPS* → *Login with a web browser*, rồi dán mã `XXXX-XXXX` nó in
  ra vào `https://github.com/login/device` trên máy mình.

- **PAT classic** trên **tài khoản cá nhân**: ảnh đại diện → *Settings* → *Developer
  settings* → *Personal access tokens* → **Tokens (classic)** → *Generate new token*.
  Trang đó có ~50 ô scope; tick **đúng một ô `repo`** (*Full control of private
  repositories*) — 5 ô con tự sáng theo, cứ để vậy. **Không** tick `admin:org`,
  `delete_repo` hay `workflow`. Hạn **7 days**. Chuỗi `ghp_...` chỉ hiện **một lần**,
  chép ngay.

  Dùng làm **mật khẩu** khi `git clone` hỏi (username là tên GitHub của bạn; lúc dán
  mật khẩu terminal không hiện ký tự nào — bình thường).

  > Scope `repo` là quyền trên **mọi** private repo tài khoản bạn truy cập được, không
  > riêng `P-192` — token classic không hẹp hơn được. Chuỗi đó sẽ nằm trên máy đi thuê,
  > nên đặt hạn ngắn và **xoá token sau buổi demo** (*Settings → Tokens → Delete*).

  > **Đừng dùng bản *fine-grained* cho repo này.** Ở đó có ô *Resource owner* mặc định là
  > tài khoản cá nhân, mà `P-192` thuộc org `AI20K-Build-Phase-Cohort-3` nên **không hiện
  > trong danh sách repo** — triệu chứng là "tìm mãi không thấy repo đâu". Phải đổi
  > *Resource owner* sang org, và org phải đã bật fine-grained PAT **cộng** có owner duyệt
  > token; nếu org chưa bật (hoặc bạn là outside collaborator) thì org không hiện trong ô
  > đó luôn. Token classic không vướng gì trong số này.

  > Token sẽ nằm **nguyên văn** trong `/opt/vivi/.git/config` trên một máy đi thuê. Đặt
  > hạn 7 ngày, và xoá remote sau khi clone xong nếu không cần `git pull`.

Nếu bạn **là** admin repo thì deploy key chỉ-đọc vẫn là cách sạch nhất (`ssh-keygen -t
ed25519 -f ~/.ssh/id_ed25519 -N ""` → dán `.pub` vào *Settings → Deploy keys*, không tick
*Allow write access*). Kiểm bằng `ssh -T git@github.com`; lệnh này **luôn thoát mã 1**
kể cả khi thành công, đó là hành vi bình thường của GitHub.

> **Cân nhắc trước khi làm bất kỳ cái nào ở trên:** đường **B1** không cần xác thực gì
> hết, và bạn **đằng nào cũng phải** `scp` `models/` + `data/rag/` ở mục 8. Với một lần
> deploy cho buổi demo, thêm một cơ chế xác thực là thêm một chỗ hỏng.

**4. Hai mạng khác quyết định có phải đi B3 không.** GitHub thông **không** có nghĩa là
build được — `docker compose build` ở mục 12 gọi ra PyPI và Hugging Face. Kiểm trước,
đừng ngồi đợi nó chết ở phút thứ mười:

```bash
curl -sS -m 10 -o /dev/null -w '%{http_code}\n' https://pypi.org/simple/
```

```bash
curl -sS -m 10 -o /dev/null -w '%{http_code}\n' https://huggingface.co
```

```bash
curl -sS -m 10 -o /dev/null -w '%{http_code}\n' https://registry.npmjs.org
```

Một trong hai cái đầu không ra `200`/`301` → **B3**, bất kể GitHub có thông hay không.
`registry.npmjs.org` hỏng thì `npm ci` ở mục 14 cũng hỏng — đó là nhánh phụ ghi ở cuối
B3.

#### B1 — đóng gói cây đã commit bằng `git archive`

**Nói bằng lời trước, vì cái tên nghe phức tạp hơn việc nó làm.** `git clone` không phải
một cơ chế đặc biệt — nó chỉ là **chép mã nguồn về máy**. VPS cần thư mục `src/`,
`frontend/`, `Dockerfile`… để build, chỉ vậy. Đường chính bảo VPS *"lên GitHub tải
xuống"*; GitHub từ chối vì repo private và VPS chưa đăng nhập.

Nhưng **mã nguồn đã nằm sẵn trên máy Windows của bạn**, và đường từ máy bạn sang VPS thì
bạn đã có: chính kết nối SSH đang dùng để đăng nhập. `scp` là "chép file qua SSH".

```
Đường chính:   GitHub  ──git clone──►  VPS      (cần đăng nhập GitHub)
B1:            Máy bạn ──── scp ────►  VPS      (dùng đúng SSH đang có)
```

B1 gọn trong ba câu: **nén mã nguồn thành một file → `scp` sang VPS → bung ra
`/opt/vivi`.** Xong là VPS có y hệt thứ `git clone` tạo ra, và mục 8 trở đi không khác
một chữ nào.

**Và bạn đằng nào cũng đang dùng `scp`** — `models/` với `data/rag/` nằm ngoài git nên
`git clone` không mang theo, mục 8 tồn tại chính vì vậy. Khác biệt thật sự giữa hai đường
là **đúng một lệnh `scp` nữa**:

| Gói | Đi bằng gì được | Dung lượng (đo 2026-08-20) | Đường chính | B1 |
|---|---|---:|---|---|
| Mã nguồn | `git clone` **hoặc** `scp` | 66 MB | GitHub | `scp` |
| `models/` | **chỉ** `scp` | 89 MB | `scp` (mục 8) | `scp` (mục 8) |
| `data/rag/` | **chỉ** `scp` | 2 MB | `scp` (mục 8) | `scp` (mục 8) |


> **PowerShell trên máy Windows**, tại thư mục gốc repo.

Kiểm mình đang đứng đúng nhánh muốn deploy trước đã — `git archive` đóng gói `HEAD`,
không phải nhánh bạn nghĩ trong đầu:

```powershell
git branch --show-current
```

```powershell
git archive --format=tar.gz -o ..\vivi-src.tar.gz HEAD
```

```powershell
scp ..\vivi-src.tar.gz vivi@<IP-VPS>:/tmp/
```

> Quay lại **bash trên VPS**.

```bash
sudo mkdir -p /opt/vivi && sudo chown vivi:vivi /opt/vivi
```

```bash
tar -xzf /tmp/vivi-src.tar.gz -C /opt/vivi
```

Rồi đi tiếp **mục 8** như bình thường.

`git archive` chỉ đóng file **đã track**, nên nó tự động bỏ `models/`, `data/rag/`,
`.env`, `node_modules/` và `.venv*/`. Đó không phải thiếu sót — đó đúng bằng cái mà
`git clone` ở mục 7 cũng không mang theo, và cũng chính là lý do mục 8 vẫn phải chạy.

**Đo trên nhánh `feat/issue-184-deploy-image`, 2026-08-20: gói ra 66 MB / 1 549 file.**
Trong đó **54 MB là `frontend/public/`** (xe 3D `sedan-realistic` + mấy file mp3) — không
bỏ được, frontend cần. Đối chiếu: cây làm việc đầy đủ là **3,1 GB**
(`tech_stack.md` mục 4b), nên nén cả thư mục thay vì dùng `git archive` là gửi thừa
`node_modules` (751 MB), `.venv`, `.next` và 154 MB PDF nguồn — toàn thứ VPS tự dựng lại
được hoặc không đọc tới.

Bốn file nhỏ trong `models/voice/` **vẫn nằm trong gói** (`.sha256` và `.metadata.json`
của Piper — chúng được track trong git, xem mục 3.1). Model thật thì không: file
`.onnx` lớn nhất trong gói chỉ là texture của xe 3D.

**Hai cái mất khi bỏ `git clone`:**

- Trên VPS không có thư mục `.git`, nên `git pull` ở mục 25 không dùng được. Cập nhật về
  sau = đóng gói và gửi lại tarball. Chấp nhận được cho một buổi demo, phiền nếu deploy
  nhiều lần.
- **`git archive` chỉ đóng file đã commit.** Sửa dở mà chưa commit thì thay đổi đó
  **không** đi theo, và triệu chứng là "sửa rồi mà VPS không đổi". Cần cả file nháp thì
  dùng **B2** thay vì B1.

#### B2 — gửi cây làm việc hiện tại, kể cả file chưa commit

Giống B1, chỉ khác lệnh đóng gói. `tar` có sẵn trong Windows 11 (bản bsdtar):

```powershell
tar -czf ..\vivi-src.tar.gz --exclude=.git --exclude=node_modules --exclude=.next --exclude=.venv --exclude=data/manuals --exclude=__pycache__ .
```

Dòng `--exclude=data/manuals` là dòng đáng giá nhất ở đây: **154 MB PDF nguồn** chỉ
dùng lúc `python -m src.rag.cli ingest`, backend lúc chạy không đọc file nào trong đó.
Đây cũng đúng lý do `.dockerignore` loại thư mục này.

#### B3 — chuyển thẳng image bằng `docker save` / `docker load`

Đây là ca nặng nhất và là ca duy nhất phải đổi cách làm thật sự: **build trên máy
Windows, chuyển image sang VPS**, VPS không build gì cả.

> **PowerShell trên máy Windows.**

```powershell
docker compose build
```

Lấy **tên image thật** — nó suy từ tên thư mục repo, đừng chép mù dòng dưới:

```powershell
docker images
```

```powershell
docker tag <tên-image-vừa-thấy> vivi-app:local
```

```powershell
docker save vivi-app:local -o ..\vivi-app.tar
```

```powershell
scp ..\vivi-app.tar vivi@<IP-VPS>:/tmp/
```

> **bash trên VPS.**

```bash
docker load -i /tmp/vivi-app.tar
```

Rồi **bắt buộc** viết file override của mục 11 theo bản dưới đây thay vì bản gốc. Cả
hai service đều còn khoá `build:` trong `docker-compose.yml`, nên nếu không khai
`image:` thì Compose vẫn đi build lại từ đầu — đúng thứ vừa tốn 2,6 GB đường truyền để
tránh:

```bash
cat > /opt/vivi/docker-compose.override.yml <<'EOF'
services:
  backend:
    image: vivi-app:local
    pull_policy: never
    ports: !override
      - "127.0.0.1:8000:8000"
  vehicle-simulator:
    image: vivi-app:local
    pull_policy: never
EOF
```

Bốn điều về đường này:

1. **`backend` và `vehicle-simulator` dùng chung một image** (`docker-compose.yml` trỏ
   cả hai vào cùng `Dockerfile`, chỉ khác `command`). Nên chỉ gửi **một** file — nhưng
   phải khai `image:` cho **cả hai** service, thiếu một là service đó build lại.
2. **File ~2,6 GB**, nén còn khoảng 1,3–1,5 GB. Trên đường truyền trong nước đó là
   hàng chục phút. Tính vào lịch, đừng làm sát giờ demo.
3. **Kiến trúc phải khớp.** Docker Desktop trên Windows build qua WSL2 ra
   `linux/amd64`, khớp VPS x86 thông thường. VPS ARM (Oracle Ampere, AWS Graviton) thì
   image này **không chạy** — lúc đó phải `docker build --platform linux/arm64`, và
   việc đó tốn công hơn là chữa cái mạng đang chặn.
4. **Đừng đẩy image này lên registry công khai.** Model STT
   `zipformer-30m-rnnt-6000h` mang license **CC-BY-NC-ND-4.0** (phi thương mại, không
   cho phái sinh) và nó được nướng vào image — xem mục 3.0. `docker save` + `scp` là
   đường hợp lệ; Docker Hub public thì không.

**Frontend trong ca B3:** `npm ci` ở mục 14 vẫn cần `registry.npmjs.org`. Nếu chỉ
`github.com` bị chặn còn npm thì thông, cứ chạy bình thường. Nếu npm cũng chặn thì phải
build Next trên Windows rồi gửi `.next/`, `public/`, `package.json` và `node_modules/`
— nhưng `node_modules` là **751 MB**, nặng hơn cả image backend, nên cân nhắc sửa mạng
trước.

#### Điều cả ba đường đều không bỏ được

**Vẫn phải `scp` `models/` và `data/rag/` theo mục 8** — trong mọi trường hợp, kể cả
B3. Image dựng ở B3 có nướng model voice, nhưng `docker-compose.yml` bind-mount
`./data` đè lên `/app/data`, nên index RAG **thật sự được dùng** là bản trên host.

Đây là chỗ hay quên nhất, và triệu chứng của nó không giống lỗi thiếu file chút nào:
container vẫn `healthy`, REST vẫn xanh, chỉ có `/healthz` báo `rag_index` = `down` và
mọi câu tra sổ tay trả về *"Tôi không tìm thấy thông tin này trong sổ tay xe."*

## 8. Đẩy artifact lên

> **PowerShell trên máy Windows**, tại thư mục gốc repo.

```powershell
scp -r models vivi@<IP-VPS>:/opt/vivi/
```

```powershell
scp -r data\rag vivi@<IP-VPS>:/opt/vivi/data/
```

> Quay lại **bash trên VPS**.

```bash
find /opt/vivi/models /opt/vivi/data/rag -type f | sort
```

Phải thấy đủ 6 file voice (kèm `.sha256`/`.metadata.json`) và 5 file trong
`data/rag/vf9_2026_vi/`.

---

# PHẦN IV — BACKEND

## 9. File `.env`

```bash
cd /opt/vivi && cp .env.example .env
```

```bash
nano /opt/vivi/.env
```

Sửa tối thiểu bốn dòng — **chú ý `MQTT_URL` là `mqtt:1883`, không phải `localhost`**,
vì backend nói chuyện với broker qua tên service trong mạng Docker:

```
APP_ENV=production
MQTT_ENABLED=true
MQTT_URL=mqtt://mqtt:1883
CORS_ORIGINS=https://<domain>
OMP_NUM_THREADS=4
```

`OMP_NUM_THREADS` không phải tinh chỉnh hiệu năng — nó là **cái phanh**. Không đặt thì
ONNX Runtime tự lấy hết số nhân thấy được, và một lượt TTS chiếm trọn máy trong nửa
giây mà **không nhanh hơn** (bão hoà ở 4 luồng — mục 1.1). Đặt bằng số nhân *vật lý*,
cùng con số dùng cho `-t` của llama-server ở mục 21.

Ba điều về `CORS_ORIGINS`, đọc kỹ vì đây là dòng dễ mất buổi tối nhất:

- **Cùng origin rồi vẫn phải khai.** `src/api/ws.py:176` **không làm CORS** — nó tự
  đối chiếu header `Origin` của WebSocket với chính biến này. Trình duyệt vẫn gửi
  `Origin` cho WS cùng origin.
- **Khớp chính xác từng ký tự**, và giá trị `None` cũng trượt. Không dấu `/` cuối,
  không kèm cổng, đúng scheme `https`.
- Sai một ký tự → **WS chết mã `4403` trong khi REST vẫn xanh**. Triệu chứng trông
  y hệt "backend chết".

Cuối cùng: **xoay `AI_LOG_API_KEY`** trước khi để `.env` nằm trên máy không phải của
bạn — giá trị mặc định trong `.env.example` là key dùng chung.

## 10. Sinh `passwd` cho Mosquitto

`scripts/bootstrap_mqtt_secrets.ps1` là PowerShell. Đây là bản bash tương đương, giữ
nguyên ba điều quan trọng của bản gốc: `-c` **chỉ dùng cho user đầu tiên**, và file
phải thuộc uid `1883` với mode `0640`.

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
> 0600 thuộc root, trong khi broker chạy dưới user `mosquitto` (uid 1883) nên không
> đọc nổi — container sẽ restart vô hạn với "Unable to open pwfile".

In ra để chép vào `.env`:

```bash
echo "MQTT_BACKEND_PASSWORD=$BACKEND_PW" && echo "MQTT_SIMULATOR_PASSWORD=$SIM_PW"
```

```bash
nano /opt/vivi/.env
```

Thêm/sửa đủ **bốn** dòng: `MQTT_BACKEND_USERNAME=vivi-backend`,
`MQTT_SIMULATOR_USERNAME=vehicle-simulator`, cộng hai mật khẩu vừa in.

**Không commit `config/mosquitto/passwd`.**

## 11. File override của Compose — hai việc, cả hai bắt buộc

Đừng sửa `docker-compose.yml` đã commit (có test khoá lại). Tạo file override ở **cùng
thư mục** với nó — Compose chỉ tự đọc `docker-compose.override.yml` nằm cạnh
`docker-compose.yml`. Để bản trong `deploy/vps/` thôi thì Compose không thấy.

```bash
cat > /opt/vivi/docker-compose.override.yml <<'EOF'
services:
  backend:
    ports: !override
      - "127.0.0.1:8000:8000"
    extra_hosts:
      - "host.docker.internal:host-gateway"
EOF
```

### 11.1. Ép backend chỉ bind loopback

`docker-compose.yml:101` publish `"8000:8000"` — **không có địa chỉ bind**, nghĩa là
cổng 8000 mở ra mọi interface. Trên máy dev vô hại; trên VPS đó là API công khai không
HTTPS, đi vòng qua cả Caddy lẫn ufw.

> Thẻ **`!override` là bắt buộc**: Compose **gộp** danh sách `ports` chứ không thay
> thế, nên viết `ports:` thường là được thêm một mapping nữa còn `"8000:8000"` vẫn
> còn nguyên và vẫn hỏng y hệt.

Và **`ufw` không cứu được ở đây**: Docker ghi rule thẳng vào chain `DOCKER` của
iptables, đứng **trước** rule của ufw. Cách duy nhất là ngay từ đầu đừng publish ra
ngoài loopback.

### 11.2. Cho backend gọi được llama-server chạy trên host

`src/config.py:33` khai `slm_endpoint = "http://127.0.0.1:8093"`. Nhưng backend nằm
trong container, và ở đó `127.0.0.1` là **chính container** — không bao giờ chạm tới
llama-server được. `host-gateway` là giá trị đặc biệt Docker hiểu, phân giải thành địa
chỉ máy chủ trên mạng cầu (đo thật: `172.17.0.1`).

Ba mảnh phải khớp nhau, thiếu một là hỏng:

| Nơi | Giá trị |
|---|---|
| override | `extra_hosts: ["host.docker.internal:host-gateway"]` |
| `.env` | `SLM_ENDPOINT=http://host.docker.internal:8093` |
| ufw | `sudo ufw allow from 172.16.0.0/12 to any port 8093 proto tcp` |

Thiếu luật ufw thì lưu lượng container → host bị chặn ở chain `INPUT`, và triệu chứng
**đổi** từ "không phân giải được tên" sang "chờ hết `SLM_TIMEOUT_S` rồi bỏ" — khó đoán
hơn hẳn. Kiểm bằng `sudo ufw status numbered | grep 8093` trước khi nghi ngờ chỗ khác.

### 11.3. `restart` KHÔNG áp dụng file này — phải `up -d --force-recreate`

`extra_hosts` và `ports` là thuộc tính **lúc tạo** container: Docker ghi `/etc/hosts` và
mở cổng đúng một lần, khi dựng. `docker compose restart` chỉ dừng rồi chạy lại tiến
trình bên trong cái vỏ cũ — không đọc lại `docker-compose.yml`, không đọc lại override,
không đọc lại `.env`.

> **Vấp thật, 2026-08-23.** File override tạo lúc 16:00, container backend đã dựng từ
> trước đó, và tới sáng hôm sau nó mới chỉ được `restart`. Kết quả là hai nguồn thông
> tin nói ngược nhau: `docker compose config` in ra `extra_hosts` đầy đủ và
> `host_ip: 127.0.0.1` — vì đó là thứ Compose *sẽ* dùng **nếu** dựng lại — trong khi
> container đang chạy thì `/etc/hosts` không hề có `host.docker.internal` và `ss` báo
> `0.0.0.0:8000`. Cả hai nửa của cùng một file cùng mất tác dụng: `/healthz` báo
> `llm: down` với mã `slm_unreachable`, **và** cổng 8000 mở ra Internet bằng HTTP trần
> suốt quãng đó mà không ai biết.
>
> Mấu chốt để không mất thời gian như lần đó: lỗi thật là
> `[Errno -2] Name or service not known` — lỗi **phân giải tên**, không phải lỗi kết
> nối. Nếu endpoint là `127.0.0.1` thì lỗi phải là `Connection refused`. Phân biệt được
> hai cái đó là loại ngay được giả thuyết "llama-server chết" và "hết RAM". Lưu ý
> `/healthz` **không** cho bạn xem lỗi này: `src/api/health.py:69` cắt chuỗi tại dấu hai
> chấm đầu tiên nên chỉ còn `slm_unreachable`, và vì `llm` được miễn trừ khỏi gate
> readiness (issue #48) nên backend cũng không ghi dòng WARNING nào. Phải tự hỏi thẳng.

Sau **mọi** thay đổi `.env`, `docker-compose.yml` hay file override:

```bash
cd /opt/vivi && docker compose up -d --force-recreate backend
```

Ba lệnh kiểm, phải xanh cả ba:

```bash
cd /opt/vivi && docker compose exec -T backend getent hosts host.docker.internal
```

```bash
ss -tlnp | grep ':8000'
```

```bash
curl -s https://<domain>/healthz | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['components']['llm'])"
```

Lần lượt phải ra `172.17.0.1`, `127.0.0.1:8000` (**không** phải `0.0.0.0:8000`), và
`{'status': 'ready', ...}`.

## 12. Build và khởi động backend

```bash
cd /opt/vivi && docker compose build
```

Lần đầu **tính bằng chục phút** trên 2 vCPU: tải torch CPU-only (528 MB), sherpa-onnx,
piper, rồi `snapshot_download` nạp sẵn E5 (471 MB) vào image. Image ra khoảng **2,6 GB**
(đã đo trên máy dev).

```bash
docker compose up -d --wait mqtt vehicle-simulator backend
```

```bash
docker compose ps
```

> `--wait` quan trọng: cả `backend` lẫn `vehicle-simulator` đều gate trên healthcheck
> của `mqtt`.

Kiểm ngay tại chỗ trước khi đi tiếp:

```bash
curl -s http://127.0.0.1:8000/healthz | python3 -m json.tool
```

Đọc `components`: `mqtt` và `vehicle_simulator` phải `ready`; `stt`, `tts`, `rag_index`
phải `ready` — **ba cái này là bằng chứng image có đủ model**, `down` là build ra image
thiếu, quay lại mục 8. `llm` là `disabled` (vì `slm_enabled=false`) — đúng, không phải lỗi.

---

# PHẦN V — FRONTEND

## 13. Biến môi trường — hai nhóm, hai nơi, hai thời điểm

### 13.1. Sáu biến `NEXT_PUBLIC_*` — **build-time**

Next.js **nướng** chúng vào bundle JS lúc `npm run build`, không đọc lúc chạy. Sửa
xong là phải build lại; `systemctl restart` một mình không đổi được gì.

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

`frontend/.gitignore:34` đã bỏ qua `.env*` nên file này không lọt vào git.

> **Thiếu một trong ba cờ `USE_MOCK_*` là frontend chạy mock**, và nhìn y hệt như đang
> nối backend thật. `frontend/src/lib/services/turn/index.ts:7` so sánh `!== "false"` —
> không khai cũng là mock, khai `"0"` cũng là mock. Ảnh chụp màn hình không chứng minh
> được gì nếu chưa tắt cả ba.

> **Giữ `NEXT_PUBLIC_API_URL` là URL tuyệt đối, đừng rút thành `/api/v1`.** Cùng origin
> rồi thì đường dẫn tương đối nghe gọn hơn, nhưng biến này được đọc ở **hai** nơi:
> trong trình duyệt (`lib/services/{turn,session,engineer}/real.ts` — tương đối chạy
> tốt) **và trong Node** (`app/api/auth/demo-driver/route.ts:3` — Route Handler chạy
> server-side, `fetch("/api/v1/...")` ném `TypeError: Failed to parse URL`). Triệu
> chứng là **nút đăng nhập 1 chạm ở `/login` hỏng trong khi mọi thứ khác xanh**.

### 13.2. Hai biến demo — **runtime**

Cố ý không có prefix `NEXT_PUBLIC_` để không bị bundle vào JS client (PR #11 bắt được
lỗi này). Để riêng, không đưa vào build:

```bash
cat > /opt/vivi/frontend/.env.runtime <<'EOF'
DEMO_DRIVER_EMAIL=driver.demo@example.com
DEMO_DRIVER_PASSWORD=<mật khẩu demo tương ứng trong src/services/auth.py>
EOF
```

```bash
chmod 600 /opt/vivi/frontend/.env.runtime
```

### 13.3. Kiểm một biến `NEXT_PUBLIC_*` đã thật sự vào bundle chưa

`printenv` hay `systemctl show vivi-frontend` **không trả lời được câu này** — biến có
thể đang có trong môi trường mà bundle vẫn là bản build cũ, và ngược lại. Chỉ bundle
mới là sự thật.

Dấu hiệu nhận biết đi ngược trực giác, nên đáng nhớ: **tên biến còn sót lại trong bundle
nghĩa là biến THIẾU lúc build.** Khi biến có giá trị, Next thay nó bằng hằng số và tên
biến biến mất; khi biến không tồn tại, Next để nguyên `process.env.X` thành phép tra cứu
lúc chạy trên một object rỗng — luôn `undefined`, tức luôn false.

Đo trên máy Windows ngày 2026-08-23, hai lần `npm run build` khác nhau đúng một biến:

| Build | Cờ | Tên biến còn trong `.next/static/`? | Code sinh ra |
|---|---|---|---|
| A | thiếu | **có**, 1 chunk | `"true"===a.default.env.NEXT_PUBLIC_WAKE_WORD_ENABLED` |
| B | `=true` | **không** | `useState(!0)` |

Đối chứng: `NEXT_PUBLIC_API_URL` (luôn được set) không xuất hiện ở đâu trong bundle cả.

```bash
grep -rlF "NEXT_PUBLIC_WAKE_WORD_ENABLED" /opt/vivi/frontend/.next/static/ | wc -l
```

`1` là cờ thiếu lúc build → tính năng tắt. `0` là đã inline, xem tiếp giá trị:

```bash
grep -rhoE '.{60}useState\)\("IDLE"\)' /opt/vivi/frontend/.next/static/chunks/*.js
```

`useState)(!0)` ngay trước `useState)("IDLE")` là true, `!1` là false, còn một tên biến
rút gọn (ví dụ `eh`) nghĩa là tra cứu lúc chạy — tức thiếu.

> **`NEXT_PUBLIC_WAKE_WORD_ENABLED` không có trong `.env.production` ở mục 13.1**, và
> tính tới 2026-08-23 VPS đang chạy đúng trạng thái đó (grep ra `1`). Hệ quả phải biết:
> `DriverShellProvider.tsx:954` là `if (!wakeFeatureEnabled) return;` ngay đầu effect
> dựng `WakeWordController`, nên bộ dò **không bao giờ khởi động** — im lặng, không lỗi,
> không cảnh báo. Ai thử gọi "Hey ViVi" sẽ thấy máy không phản ứng và tưởng micro hỏng.
>
> Tệ hơn: **không có tín hiệu giao diện nào để biết cờ đang bật hay tắt.**
> `WakeWordToggle.tsx` (ô "Luôn lắng nghe") **chưa được import ở bất cứ đâu trong
> `src/`** — chuỗi `"Luôn lắng nghe"` vắng mặt trong bundle ở **cả hai** build ở trên,
> kể cả bản bật cờ. Cách kiểm lúc chạy duy nhất là mở tab **Network** rồi tải lại
> `/driver`: bật thì trình duyệt tải `/models/wake-word/manifest.json` cùng ba file
> `.onnx` (~3,6 MB, đều nằm trong git nên VPS có sẵn) và chiếm micro **ngay khi vào
> trang**, chưa cần chạm nút nào.
>
> Hai cái giá phải cân nhắc trước khi bật cho buổi demo: hộp thoại xin quyền micro chắn
> ngang lúc vừa vào trang, và ~3,6 MB tải thêm mỗi lần vào trang.

## 14. Cài và build

```bash
cd /opt/vivi/frontend && npm ci
```

`next build` đỉnh **1 173 MB** (đo 2026-08-19). Trên máy 5 GB có SLM 3B thì lúc chạy
chỉ trống 0,86–1,21 GB, tức **thiếu ~100–300 MB** — phải nhường chỗ. Máy 8 GB bỏ qua
khối này và khối khởi động lại bên dưới.

**Dừng MỘT dịch vụ — cái nào cũng đủ, không cần cả hai.** `vivi-slm` giải phóng nhiều
hơn (2 109 MB so với 1 208 MB), nên nếu nó đang chạy thì dừng nó là gọn nhất:

```bash
sudo systemctl stop vivi-slm
```

```bash
cd /opt/vivi/frontend && npm run build
```

```bash
sudo systemctl start vivi-slm
```

> Chưa dựng SLM (PHẦN VII) thì dùng backend thay thế: `cd /opt/vivi && docker compose
> stop backend`, build, rồi `docker compose start backend`.

## 15. Chạy bằng systemd

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

Phải ra `200`. Chưa ra thì `journalctl -u vivi-frontend -n 50 --no-pager`.

---

# PHẦN VI — HTTPS VÀ KIỂM CHỨNG

## 16. Caddy

Caddy tự xin và gia hạn chứng chỉ Let's Encrypt, và **proxy WebSocket không cần cấu
hình thêm** — đó là lý do chọn nó thay nginx ở đây.

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

```bash
sudo systemctl reload caddy
```

Ba điều phải hiểu trước khi sửa khối này:

1. **Đừng viết `handle /api/*`.** `/api/auth/demo-driver` là **route của Next.js**,
   không phải của backend. Backend chỉ đăng ký `prefix="/api/v1"`
   (`src/main.py:168-176`). Gom cả `/api/*` về cổng 8000 là backend trả 404 cho nó →
   nút đăng nhập 1 chạm chết trong khi mọi thứ khác xanh.
2. **`/docs`, `/redoc`, `/openapi.json` của FastAPI sẽ rơi vào khối `handle` cuối** →
   Next.js trả 404. Đây là **kết quả mong muốn**: Swagger không nên mở công khai. Cần
   xem thì `curl` qua SSH tới `127.0.0.1:8000`.
3. Khối `handle` trong Caddy loại trừ lẫn nhau và xét theo độ cụ thể, nên thứ tự viết
   không đổi kết quả — nhưng cứ để khối `handle` trống ở cuối cho dễ đọc.

Nếu Caddy không xin được chứng chỉ: kiểm A record đã lan chưa (`dig +short <domain>`),
và cổng 80 phải mở — Let's Encrypt cần nó để xác thực.

## 17. Kiểm chứng, theo đúng thứ tự này

```bash
curl -s https://<domain>/healthz | python3 -m json.tool
```

```bash
curl -sI https://<domain>/ | head -1
```

Phải là `200` từ Next, **không phải 404 từ backend**. Ra 404 → khối `handle` cuối
trong Caddyfile sai.

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<domain>/api/v1/status
```

Rồi mở trình duyệt và kiểm **bốn** thứ, không phải một:

1. **`/login`** — bấm nút đăng nhập 1 chạm. Hỏng ở đây = mục 13.1 (URL tuyệt đối)
   hoặc 13.2 (thiếu `.env.runtime`).
2. **`/driver`** — gõ một câu lệnh văn bản, ví dụ *"bật điều hoà"*. Xanh = REST thông.
3. **Tab Network → WS** — kết nối `/ws/ivi` phải **mở**, không phải đóng `4403`.
   Đóng `4403` = `CORS_ORIGINS` ở mục 9 sai.
4. **Bấm micro và nói.** `getUserMedia` chỉ chạy trên secure context — đây vừa là phép
   thử chứng chỉ đã đúng, vừa là chặng duy nhất chứng minh STT/TTS thật sự sống.

### 17.1. Hâm nóng trước khi demo — đừng bỏ qua

`src/main.py` warm sẵn embedder E5 lúc khởi động, **nhưng không warm STT và TTS**.
Đo được trên máy dev: lượt thoại **đầu tiên** sau khi container mới lên mất
`stt` **1 144 ms**, trong khi run đã ấm chỉ **106 ms** — chênh 10 lần
(`tech_stack.md` mục 4b). Nguyên nhân nhiều khả năng là nạp ba file ONNX int8 từ đĩa
nguội; **giả thuyết này chưa được kiểm chứng bằng lượt thứ hai**.

Dù nguyên nhân là gì, cách xử lý đều giống nhau: **trước buổi demo, tự bấm micro nói
một câu**. Lượt đó gánh phần chậm, người xem không phải chịu.

Đo lại RAM thật trên máy đích để thay số ước lượng ở mục 1:

```bash
docker stats --no-stream
```

```bash
systemctl status vivi-frontend --no-pager | grep Memory
```

---

# PHẦN VII — BẬT SLM (QWEN) TRÊN VPS

> Chỉ làm phần này nếu **bắt buộc** phải có `slm_enabled=true`. Đường mặc định
> (`false`) không cần gì ở đây.

## 18. Chọn model — đây là quyết định, không phải tuỳ chọn

> **Quyết định 2026-08-19: model là `qwen2.5-3b-instruct-q4_k_m`, giữ nguyên mặc định
> của `config.py:34`.** Mục này giữ lại số của 0,5B làm điểm tham chiếu, không phải
> khuyến nghị.

SPIKE-003 đo cả CPU lẫn GPU (`eval/results/spike-003/*/manifest.json`). **Đọc cột
`grammar` trước khi dùng bất kỳ dòng nào** — nó là chỗ bộ số này gài bẫy:

| Model | Backend | `grammar` | p50 | p95 | tok/s | RSS đỉnh | n |
|---|---|---|---:|---:|---:|---:|---:|
| **3B** q4_k_m | **cpu6** | **✗** | **17 441 ms** | 17 728 ms | 9,3 | 1 903 MB | 8 |
| 3B q4_k_m | vulkan (RTX) | ✗/✓ | 877–2 708 ms | 999–3 158 ms | 48–63 | 2 184 MB | 16 |
| 0,5B q4_k_m | cpu6 | ✓ | 1 135 ms | 1 616 ms | 44,7 | 645 MB | 64 |
| 0,5B q4_k_m | vulkan (RTX) | ✓ | 317–382 ms | 496–730 ms | 147–156 | 765 MB | 64 |

**Dòng đầu là dòng không dùng được.** `QwenPlanner` thật luôn gửi `json_schema`
(`slm.py:159`), tức luôn có grammar — nên `rungA-cpu6-3b` (`grammar=False`) đo một cấu
hình ứng dụng không chạy. Phần dưới là phép đo thay thế.

### Hai vai, hai độ dài sinh — phải tách ra mới kết luận đúng

Bảng trên đo `n_predict = 160`, tức **vai planner**. Nhưng SLM có **hai** vai trên
đường lượt thoại, chịu chi phí rất khác nhau:

| Vai | Gọi khi nào | `n_predict` | Nguồn |
|---|---|---:|---|
| `QwenPlanner` | chỉ câu router **không khớp luật** | 160 | `slm.py:157`, `graph.py:253` |
| `QwenLeadIn` | **mọi** câu tra sổ tay (`grounded_answer`) | **40** | `slm.py:224`, `graph.py:174` |

Vai thứ hai mới là vai chạy thường xuyên: theo ADR-011 câu không khớp luật **mặc định
về tra sổ tay**, nên câu dẫn nằm trên gần như mọi câu trả lời.

Giải mã chiếm gần hết thời gian (3B cpu6: 160 token ÷ 9,3 tok/s = 17,2 s trên tổng
17,4 s đo được), nên chi phí gần **tỉ lệ thuận với `n_predict`**. Suy ra ba phương án:

### Đo lại 2026-08-19: con số 17 441 ms **không mô tả đường code thật**

Chạy `QwenPlanner` và `QwenLeadIn` **thật** (đúng prompt, đúng `json_schema`) trên
llama-server CPU-only, 3B q4_k_m, `-c 2048`:

| Cấu hình | **Peak WS** | Planner p50 | Planner max | Câu dẫn p50 | Câu dẫn p95 | tok/s |
|---|---:|---:|---:|---:|---:|---:|
| 3B, `-t 2` | **1 995 MB** | **8 561 ms** | 10 943 ms | 4 310 ms | 6 202 ms | 9,2 |
| 3B, `-t 4` | **2 109 MB** | **5 352 ms** | 7 359 ms | 3 043 ms | 5 444 ms | 14,0 |
| 3B, `-t 6` | **1 937 MB** | **4 899 ms** | 7 605 ms | 2 923 ms | 6 343 ms | 13,1 |

*Máy đo: i7-14650HX (16 nhân vật lý), Windows 11, `-ngl 0`, đã bỏ lượt nguội. 8 câu
điều khiển + 8 câu hỏi sổ tay mỗi cấu hình. Đây là **phép đo tại chỗ**, chưa có run id
— muốn thành bằng chứng phải chạy lại qua `scripts/spike3_bench.py`.*

**Vì sao lệch 17 441 ms:** run `rungA-cpu6-3b` đặt **`grammar=False`** và sinh đủ 160
token. Nhưng `QwenPlanner` thật gửi `json_schema` (`slm.py:159`), nên llama-server bật
grammar và **dừng ngay khi JSON hợp lệ đóng** — `predicted_n` trung vị đo được là **49
token**, không phải 160. Con số 17,4 s mô tả một cấu hình mà ứng dụng không dùng.

**Kết luận thay cho kết luận cũ:**

- **3B chạy được với `SLM_TIMEOUT_S=8` mặc định — nhưng biên rất mỏng.** Ở `-t 4` và
  `-t 6`, max đo được là 7,4–7,6 s so với trần 8,0 s. Không có chỗ cho một nhân chậm hơn.
- **Ở `-t 2` thì hỏng:** planner p50 **8 561 ms > 8 000 ms**, tức **quá nửa** số lời gọi
  quá hạn. Đây chính là kịch bản "4 vCPU = 2 nhân vật lý + SMT" — nên mục 1.2 điểm 2
  (đếm nhân vật lý) là bước bắt buộc, không phải bước tuỳ chọn.
- **RAM đỉnh: 1 937–2 109 MB**, dao động là nhiễu working-set của Windows. **Lấy
  2 109 MB làm số quy hoạch.** Khớp với `server_peak_rss_mb = 1 903 MB` của SPIKE-003.

### Đo lại 2026-08-20: thêm cột GPU, và cột `-t 2` mà mục 1.1 cần

Ba cấu hình, cùng một bộ ca (8 câu điều khiển cho planner, 4 câu sổ tay cho câu dẫn),
cùng đường code thật (`QwenPlanner.propose` + `QwenLeadIn.write`, có `json_schema`),
đã bỏ lượt nguội:

| Thiết bị | Planner p50 | Planner max | Câu dẫn p50 | Quá trần 8 s |
|---|---:|---:|---:|---:|
| **GPU RTX 4050** (Vulkan, `-ngl 99`) | **2 215 ms** | 5 841 ms | **1 110 ms** | **0 / 12** |
| CPU `-t 4` | 5 329 ms | 6 540 ms | 3 173 ms | 0 / 12 |
| **CPU `-t 2`** | **7 326 ms** | **11 851 ms** | 4 146 ms | **2 / 12** |

*Máy đo: i7-14650HX + RTX 4050 Laptop, Windows 11, llama.cpp `b10358`, `-c 2048`.
**Phép đo tại chỗ, chưa có run id** — muốn thành bằng chứng phải chạy lại qua
`scripts/spike3_bench.py`.*

Cột `-t 4` (5 329 / 6 540) **tái lập** phép đo 2026-08-19 ở bảng trên (5 352 / 7 359),
nên hai bộ số này đọc chung được.

**Tài nguyên GPU khi chạy**, đo bằng `nvidia-smi` trong lúc gọi planner:

| | Giá trị |
|---|---|
| Util đỉnh | **89%** |
| VRAM | **2 437 MiB** (nghỉ 421 MiB → model chiếm ~2,0 GB) |
| Điện đỉnh | **48,4 W** |

Hai điều rút ra:

- **GPU mua được 2,4 lần tốc độ, và mua được biên an toàn.** 2 215 ms so với 5 329 ms
  không đổi cách demo diễn ra; nhưng khoảng cách tới trần 8 s thì đổi hẳn.
- **GPU chỉ giúp SLM.** `torch` trong image là bản **`+cpu`**, ONNX Runtime chỉ khai
  `CPUExecutionProvider`, và sherpa-onnx cố định một luồng — nên gắn card vào VPS
  cũng **không** làm STT/TTS/RAG nhanh hơn một mili-giây nào. Kiểm lại được bằng
  `python -c "import torch, onnxruntime; print(torch.__version__, torch.cuda.is_available(), onnxruntime.get_available_providers())"`.

### Đối chiếu ngoài: Orange Pi 5 Max (Aleksei Rytikov, Medium)

Một bài đo độc lập cùng lớp phần cứng — RK3588, 4× Cortex-A76 @ 2,4 GHz + 4× A55,
16 GB RAM, faster-whisper-small + Piper + llama.cpp:

| | Bài đó (RK3588) | Đo ở đây (i7, `-t 4`) |
|---|---|---|
| Qwen2.5-3B-Q4_K_M, tok/s | **12–18** | **14,0** |
| Đáp ~30 token | **2,0–3,0 s** | câu dẫn ~19 token: 3,0 s |
| **RAM cho 3B** | **3,0–4,0 GB** | **2,1 GB** |

**Tốc độ khớp rất sát** — điều này quan trọng hơn nó thoạt nghe: nó nói rằng giải mã
llama.cpp bị chặn ở **băng thông bộ nhớ**, nên một SoC ARM 8 nhân và 4 luồng x86 đời mới
cho ra cùng một khoảng. Suy ra nhân VPS cũng sẽ nằm quanh đó, không tệ hơn nhiều lần.

**Nhưng RAM thì lệch 1,5–2×, và phải xử lý bằng cách chọn số lớn hơn.** Bài đó không ghi
`-c`, mà KV cache tỉ lệ thuận với độ dài ngữ cảnh. Cách phòng: **ghim `-c 2048`** như
mục 21 — đó chính là cấu hình đã cho ra 2,1 GB ở đây. Nếu ai nới `-c` lên thì con số RAM
trong runbook này không còn đúng.

> Một chi tiết nữa trong bài đó đáng đọc: tác giả có **16 GB RAM**, thừa sức chạy 3B,
> **vẫn chọn Qwen2.5-1.5B làm model chính**. Lý do là độ trễ, không phải bộ nhớ — cùng
> đúng thứ đánh đổi mục này đang bàn.

> **Nói thẳng về chất lượng:** ADR-005 ghi "Not Yet" cho **cả** 0,5B lẫn 3B — cả hai
> đều trượt gate lựa chọn model. Giữ 3B nghĩa là giữ **đúng model mà prompt trong
> `src/agents/slm.py` được hiệu chỉnh cho** ("BÊ NGUYÊN cấu hình đã đo ở biến thể A"),
> nên không phát sinh rủi ro chất lượng mới — nhưng cũng **không** biến "Not Yet" thành
> "Accepted". Đừng mô tả hệ là "đã chọn xong model".

Một chi tiết ngược trực giác trong cùng bộ số: **cpu12 chậm hơn cpu6** (0,5B rungA:
4 655 ms so với 4 348 ms). SMT gây hại ở đây — đặt `-t` bằng **số nhân vật lý**, đừng
bằng số luồng.

## 19. Cài llama.cpp trên VPS

Repo ghim build **`b10358`** (`tools/llama-vulkan/llama-vulkan.metadata.json`). Dùng
đúng build đó để số đo còn so sánh được — bản Windows trong repo là Vulkan, trên Linux
cần asset CPU riêng.

```bash
mkdir -p /opt/vivi/tools/llama && cd /opt/vivi/tools/llama
```

Vào https://github.com/ggml-org/llama.cpp/releases/tag/b10358, tìm asset Linux x64
CPU (tên thường là `llama-b10358-bin-ubuntu-x64.tar.gz`), rồi:

```bash
curl -fsSLO https://github.com/ggml-org/llama.cpp/releases/download/b10358/llama-b10358-bin-ubuntu-x64.tar.gz
```

```bash
tar -xzf llama-b10358-bin-ubuntu-x64.tar.gz && ls
```

```bash
./llama-server --version
```

> Nếu asset không còn hoặc không chạy được trên Ubuntu 24.04 thì build từ nguồn:
> `sudo apt install -y build-essential cmake libcurl4-openssl-dev`, `git clone`,
> `git checkout b10358`, `cmake -B build -DGGML_NATIVE=ON`, `cmake --build build -j`.
> Ghi lại là đã build từ nguồn — đó là một khác biệt tăng phẩm cần có trong manifest.

## 20. Đưa model 3B lên VPS

Model **nằm ngoài git** — giấy phép **Qwen Research**, phi thương mại. Máy dev đã có sẵn
ở `C:\vivi-models` (2 104 932 768 byte), nên **đẩy lên chứ không tải lại**: tải lại là
thêm một artifact không đối chiếu được với cái đã đo.

> **PowerShell trên máy Windows.**

```powershell
ssh vivi@<IP-VPS> "mkdir -p /opt/vivi/models/slm"
```

```powershell
scp C:\vivi-models\qwen2.5-3b-instruct-q4_k_m.gguf C:\vivi-models\qwen2.5-3b-instruct-q4_k_m.gguf.sha256 vivi@<IP-VPS>:/opt/vivi/models/slm/
```

> Quay lại **bash trên VPS**. Đối chiếu checksum — kỷ luật "no unverified artifacts",
> và cũng là thứ `run_slm_server.ps1` kiểm trước khi load:

```bash
cd /opt/vivi/models/slm && sha256sum -c qwen2.5-3b-instruct-q4_k_m.gguf.sha256
```

Phải in `OK`. Giá trị đúng là
`626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d`.

## 21. Chạy llama-server bằng systemd

Cờ dưới đây **bê nguyên cấu hình đã đo** trong `scripts/run_slm_server.ps1`
(`-c 2048 --cache-reuse 256`), cộng `-ngl 0` vì không có GPU.

**`-c 2048` là con số ràng buộc RAM — đừng nới.** Toàn bộ số 1,9–2,1 GB ở mục 18 đo ở
đúng giá trị này; KV cache tỉ lệ thuận với ngữ cảnh, và bài đo Orange Pi (không ghi `-c`)
báo 3,0–4,0 GB cho cùng model.

**`-t` đặt bằng số nhân *vật lý*** (`lscpu | grep 'Core(s) per socket'`). Mục 18 đo được
`-t 2` cho planner p50 **8 561 ms**, tức **quá trần 8 000 ms** — nếu VPS chỉ có 2 nhân
vật lý thì phải nới `SLM_TIMEOUT_S` ở mục 22, không có cách nào khác.

```bash
sudo tee /etc/systemd/system/vivi-slm.service > /dev/null <<'EOF'
[Unit]
Description=VIVI SLM (llama-server, Qwen2.5-3B-Instruct q4_k_m, CPU)
After=network.target

[Service]
Type=simple
User=vivi
WorkingDirectory=/opt/vivi/tools/llama
ExecStart=/opt/vivi/tools/llama/llama-server   -m /opt/vivi/models/slm/qwen2.5-3b-instruct-q4_k_m.gguf   --host 127.0.0.1 --port 8093   -c 2048 --cache-reuse 256 -ngl 0 -t 4
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

> **Đừng publish cổng 8093 ra ngoài.** Nó không có xác thực. `--host 127.0.0.1` là
> chốt chặn duy nhất, và Caddyfile ở mục 16 cũng không định tuyến tới nó.

> **Trên máy 4–5 GB:** dừng dịch vụ này trước mỗi lần `npm run build` (mục 14), rồi
> bật lại — nó giữ **~2,1 GB** thường trực. Xem mục 1.2.
>
> ```bash
> sudo systemctl stop vivi-slm
> ```
>
> ```bash
> sudo systemctl start vivi-slm
> ```

## 22. Bật cờ trong `.env`

```bash
nano /opt/vivi/.env
```

Dùng 3B thì **`SLM_MODEL_ID` giữ nguyên mặc định** (`config.py:34` đã là
`qwen2.5-3b-instruct-q4_k_m`) — chỉ cần **một** dòng:

```
SLM_ENABLED=true
```

> Nếu bao giờ đổi model thì **bắt buộc** đổi `SLM_MODEL_ID` cho khớp:
> `src/services/health.py:215` đối chiếu chuỗi này với `/props` của llama-server và trả
> `degraded` khi lệch.

**`SLM_TIMEOUT_S` — quyết định sau khi chạy mục 24, không đoán trước.** Số đo ở mục 18:

| Số nhân vật lý của VPS | Planner p50 | Kết luận |
|---|---:|---|
| 4 | 5 352 ms (max 7 359) | Giữ mặc định **8,0** — nhưng biên chỉ ~0,6 s |
| 2 | **8 561 ms** (max 10 943) | **Quá trần.** Đặt `SLM_TIMEOUT_S=15.0` |

Nhớ rằng **mỗi lượt hỏng tốn hai lần timeout** (`graph.py` thử lại đúng một lần), nên
đặt trần quá cao là tự nhân đôi thời gian chờ của ca xấu nhất.

```bash
cd /opt/vivi && docker compose up -d --force-recreate backend
```

### 22.1. `SLM_CLASSIFY_TIMEOUT_S` — đo trên VPS 2026-08-23

Vai classify (ADR-026) có trần **riêng**, mặc định 2,0 s, **không** dùng chung
`SLM_TIMEOUT_S` ở trên. Đo thật bằng chính `QwenClassifier` chạy trong container backend
(đúng prompt `CLASSIFY_SYSTEM`, đúng `json_schema`, đúng `n_predict: 32`, tính cả chặng
mạng container → host), 20 lượt trên 10 câu trượt luật:

| | ms |
|---|---:|
| nhỏ nhất | 1 478 |
| p50 | 1 671 |
| p95 | 2 077 |
| lớn nhất | 2 225 |
| hâm nóng, cache lạnh | 2 241 |

| Trần | Số lượt kịp |
|---:|---|
| **2,0 s (mặc định)** | **17/20 — 85%** |
| 2,5 s | 20/20 |
| 3,0 s | 20/20 |

Phân bố **hẹp**: toàn dải 747 ms, không đuôi dài. Nghĩa là trần 2 000 ms không lọc ca xấu
— nó cắt ngẫu nhiên phần trên của ca bình thường, ngay trên p50 và ngay dưới max.

> **15% ở đây là cận dưới, không phải con số thật.** Bench chạy 20 lượt liên tiếp nên lần
> nào cũng trúng slot đã ấm. Càng gần điều kiện thật, tỷ lệ trượt càng cao:

| Nguồn | Điều kiện | Tỷ lệ trượt |
|---|---|---|
| Bench mục này | 20 lượt liên tiếp, slot luôn ấm | 15% |
| SP-0 §2 (ghi sẵn trong `.env.example`) | có nghỉ giữa các lượt | 22% |
| journal `vivi-slm`, 24 h | lưu lượng thật, thưa | 33% (9/27, trong đó 6 là classify) |

Ba phép đo độc lập, cùng một hướng.

**Chốt: `SLM_CLASSIFY_TIMEOUT_S=3.5`.** Đây là con số `.env.example` đã khuyến nghị sẵn từ
trước ("Nới lên 3.5 khi chỉ chạy MỘT server" — và ta đang chạy đúng một server cho cả bốn
vai). Không lấy 3,0 dù bench nói 20/20: dải đo của SP-0 chạm **3,0 s**, nên đặt trần đúng
3,0 là cắt ngay tại max của họ — lặp lại đúng cái sai của trần 2,0, chỉ dịch lên một nấc.

```
SLM_CLASSIFY_TIMEOUT_S=3.5
```

```bash
cd /opt/vivi && docker compose up -d --force-recreate backend
```

Hai điều làm đánh đổi nhẹ hơn ghi chú trong `config.py` gợi ý:

- **Server không tới được thì KHÔNG tiêu trần.** Lỗi là `ConnectError`, trả về sau ~53 ms
  (đo 2026-08-23, lúc container backend thiếu `extra_hosts` — mục 11.3). Trần chỉ bị tiêu
  khi server *có* mà *chậm*.
- **Vai classify không thử lại** — `graph.py:326-333` gọi đúng một lần. Câu "mỗi lượt hỏng
  tốn hai lần timeout" ở mục 22 chỉ áp cho planner.

> **Đọc `.env.example` trước khi tự đo.** Khối SLM ở đó (dòng 32–50) đã ghi sẵn dải
> 1,9–3,0 s, tỷ lệ trượt 22% và khuyến nghị 3.5 — có từ **trước** phép đo trong mục này.
> Phép đo độc lập vẫn có giá trị (nó cho p50/p95 trên đúng máy này) nhưng lẽ ra phải là
> bước xác nhận, không phải bước khám phá.

**Còn treo, chưa đo — và nó có thể làm mục này thành thừa.** llama-server chạy **4 slot**
(dòng lệnh không truyền `--parallel`, log hiện `id 0..3`), bốn slot chia nhau prefix cache.
Log có `selected slot by LRU, t_last = -1` — yêu cầu rơi vào slot chưa từng dùng nên phải
prefill lại từ đầu thay vì tận dụng `--cache-reuse`. Nếu đúng thì `--parallel 1` sửa
**nguyên nhân** của phần lớn ca hết giờ, thay vì nới hậu quả bằng cách nâng trần. Kiểm
bằng cách chạy lại bench với khoảng nghỉ vài phút giữa các lượt — chạy liên tiếp không bao
giờ tái tạo được ca slot lạnh.

Thêm một chi phí ẩn đo được ngày 2026-08-23: **cắt kết nối không làm llama-server ngừng
tính.** Trong 9 lượt bị cắt của 24 h, ba lượt vẫn giữ slot **19,13 s / 11,45 s / 7,88 s**
sau khi không ai còn đợi (sáu lượt kia nhả trong 0,06–0,88 s). Khi rơi vào ca chậm, câu
nói kế tiếp xếp hàng sau nó và gần như chắc chắn hết giờ theo — timeout tự nuôi timeout.

Hai script đo nằm ở `deploy/vps/`:

```bash
cd /opt/vivi && docker compose exec -T backend python - < ~/slm_classify_bench.py
```

```bash
sudo journalctl -u vivi-slm --since "-24h" --no-pager | python3 ~/slm_timeout_report.py
```

Script thứ hai ghép `launch → cancel → release` theo task id, dùng đồng hồ riêng của
llama-server (dạng `phút.giây.ms.µs`) chứ không dùng dấu thời gian của journald —
journald chỉ có độ phân giải 1 giây, quá thô để phân biệt trần 2 s với trần 4 s.

## 23. Kiểm chứng SLM

```bash
curl -s https://<domain>/healthz | python3 -m json.tool
```

`llm` phải là **`ready`** — không còn `disabled`. Nếu là:

| Giá trị | Nghĩa |
|---|---|
| `disabled` | Cờ chưa vào — backend chưa đọc `.env` mới, recreate lại |
| `down` | `slm_unreachable` — ba nguyên nhân, phân biệt bằng lỗi thật (mục 11.3): `vivi-slm` chưa chạy, sai cổng, hoặc **container backend chưa được recreate** nên thiếu `extra_hosts` |
| `degraded` | `slm_model_mismatch` — `SLM_MODEL_ID` không khớp model llama-server đang load (mục 22) |

Rồi thử một câu **router không khớp luật nào** để ép đi qua planner (câu điều khiển
thông thường sẽ đi đường luật và không chạm SLM):

```bash
sudo journalctl -u vivi-slm -f
```

Mở `/driver` ở tab khác, nói một câu lạ, và xem log có lượt `/completion` không.
Backend cũng ghi cảnh báo `SLM attempt n/2 hỏng` khi có sự cố — dòng đó tồn tại đúng
để phân biệt "hỏng hạ tầng" với "hỏng schema".

## 24. Đo lại trên máy đích — bắt buộc trước khi trích số

Mọi con số ở mục 18 đo trên **máy dev**, không phải VPS này. Kỷ luật evidence của repo
đòi mỗi số phải kèm tầng phần cứng:

```bash
curl -s https://<domain>/api/v1/metrics/summary -H "Authorization: Bearer <token-engineer>" | python3 -m json.tool
```

Đọc `stage_latency_ms.planning_or_retrieval` — chặng đó **gộp cả RAG lẫn SLM**, nên
so với số của bản tắt cờ mới thấy được phần SLM cộng thêm. Ghi lại thành một run mới,
đừng sửa file trong `eval/results/`.

---

# PHẦN VIII — VẬN HÀNH

## 25. Cập nhật về sau

```bash
cd /opt/vivi && git pull
```

```bash
docker compose build && docker compose up -d --wait
```

```bash
cd /opt/vivi/frontend && npm ci && npm run build
```

```bash
sudo systemctl restart vivi-frontend
```

> `git pull` **không** kéo về `models/voice/` và `data/rag/` — chúng nằm ngoài git.
> Chúng cũng hiếm khi đổi; khi đổi thì `scp` lại như mục 8.

> Sửa bất kỳ biến `NEXT_PUBLIC_*` nào là **bắt buộc** `npm run build` lại.

> Hook `pre-push` chạy mỗi lần push, kể cả nếu ai lỡ push **từ** VPS. Trên VPS hook
> vô hại (luôn `exit 0`), nhưng `.env` trên VPS có `AI_LOG_API_KEY`.

**Sao lưu SQLite** trước mỗi lần đổi cấu hình hoặc ingest lại index:

```bash
cp /opt/vivi/data/app.db /opt/vivi/data/app.db.$(date +%F)
```

**Xoay mật khẩu MQTT:** xoá `config/mosquitto/passwd`, chạy lại mục 10, cập nhật `.env`,
rồi `docker compose up -d --force-recreate`.

**Dọn cache build của Docker** — thứ duy nhất trong hệ lớn dần theo thời gian. Mỗi lần
`docker compose build` lại bồi thêm một lớp; trên máy dev cache đã lên **27,61 GB**.
Kiểm rồi dọn sau vài lần cập nhật:

```bash
docker system df
```

```bash
docker builder prune -f
```

> `docker builder prune` chỉ xoá cache build, **không** đụng image đang chạy. Lần build
> kế tiếp sẽ lâu hơn vì mất cache — đừng chạy ngay trước ngày demo.

## 26. Bảy chỗ dễ vấp, xếp theo mức hay gặp

| # | Lỗi | Triệu chứng |
|---|---|---|
| 1 | `handle /api/*` thay vì `/api/v1/*` | Nút đăng nhập 1 chạm chết, mọi thứ khác xanh |
| 2 | `CORS_ORIGINS` thiếu/sai một ký tự | WS đóng `4403`, REST xanh — giống hệt "backend chết" |
| 3 | Quên một cờ `USE_MOCK_*` | Giao diện chạy mock, trông y như thật |
| 4 | Rút `NEXT_PUBLIC_API_URL` thành đường dẫn tương đối | Route Handler ném `Failed to parse URL` |
| 5 | Sửa biến `NEXT_PUBLIC_*` rồi chỉ `restart` | Không có gì thay đổi — kiểm bằng mục 13.3 |
| 5b | Sửa `.env`/override rồi chỉ `docker compose restart` backend | `llm: down` **và** cổng 8000 hở ra Internet, trong khi `docker compose config` vẫn in ra cấu hình đúng (mục 11.3) |
| 6 | `next build` (đỉnh **1 173 MB**) khi cả backend lẫn `vivi-slm` đang chạy trên máy 5 GB | OOM giữa chừng — dừng một trong hai trước |
| 7 | Dùng IP trần thay vì tên miền | Không chứng chỉ → **không có micro**, và trang HTTPS không được gọi `http://` |

Thêm hai cái ít gặp hơn nhưng khó đoán: quên `!override` ở mục 11 (cổng 8000 vẫn mở ra
Internet dù đã tưởng đóng), và quên `chown 1883:1883` ở mục 10 (broker restart vô hạn).

## 27. Runbook này KHÔNG giải quyết

Ghi ra để không ai đọc "deploy xong" thành "mở cho công chúng được":

- **Một chiếc xe ảo dùng chung.** `vehicle_id` là hằng số (`src/config.py:110`) — mọi
  người điều khiển cùng một chiếc xe.
- **Hai tài khoản demo hard-code** (`src/services/auth.py`). Ai đọc source cũng đăng
  nhập được, và `/engineer` lộ trace của mọi lượt.
- **Khoá `threading.Lock` toàn cục trên STT/TTS** (`src/services/voice.py:97`, `:192`).
  Mỗi lúc **một người** nói được. Máy to hơn không gỡ được — khoá nằm trong tiến trình.
- **Không có rate limit** ở bất kỳ tầng nào.
- **Không mở rộng ngang được.** SQLite một kết nối; `InMemorySaver` mất lượt đang chờ
  duyệt khi restart. Chưa từng chạy trên hai worker.
- **License CC-BY-NC-ND của model STT.** Image có nướng model vào → **đừng push lên
  registry công khai**. Build tại chỗ trên VPS như mục 12 là đúng.

Cả sáu đều là **việc code**, không phải việc deploy.

## 28. Cái file này chưa chứng minh được

- **Chưa ai chạy trọn quy trình.** Định tuyến và tên biến đã đối chiếu vào code; hành
  vi đầu-cuối thì chưa.
- ~~RAM của `next start` và RAM lúc `next build`~~ — **đã đo 2026-08-19**: 138 MB và
  1 173 MB. Nhưng đo trên **máy dev 16 nhân, Windows**; trên VPS 4 vCPU Linux số worker
  của `next build` khác nên đỉnh sẽ khác (nhiều khả năng thấp hơn).
- **43 MB asset ở `frontend/public/`** giờ do VPS phục vụ, không có CDN. Ảnh hưởng tới
  thời gian mở trang đầu: **chưa đo**.
- **Hành vi WebSocket sống lâu qua Caddy** (thời gian sống, reconnect): chưa đo. Server
  đã có replay theo ADR-014 nhưng client chưa bao giờ gửi `last_event_id`, nên replay
  vẫn không quan sát được trong demo.
- **Nhiều người dùng đồng thời.** Mọi số RAM ở mục 1 là một phiên, một người.
- **Ba đường thay thế GitHub ở mục 7.1.** `git archive`/`tar` + `scp` là cơ chế chuẩn và
  đã đối chiếu vào `.gitignore`/`.dockerignore`, nhưng chưa chạy trên VPS thật. Riêng
  đường B3 còn một mắt xích suy luận: khoá `image:` + `pull_policy: never` trong file
  override để chặn Compose build lại — suy từ tài liệu Compose, **chưa kiểm**. Thử
  `docker save`/`docker load` cục bộ một lần trước khi dựa vào nó giữa buổi demo.
