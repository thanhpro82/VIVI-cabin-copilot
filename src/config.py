from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "AI20K Agent"
    app_env: Literal["development", "production", "test"] = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:3000"

    # LLM
    openai_api_key: str = ""
    model_name: str = "gpt-4o-mini"
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # SLM planner — Qwen2.5-3B q4 là fallback cho câu mơ hồ, KHÔNG phải planner
    # chính. Xem ADR-010 và docs/agent_spec.md. Mặc định tắt: sprint này chưa có
    # bằng chứng chạy weight thật, và test không được phụ thuộc model.
    slm_enabled: bool = False
    slm_endpoint: str = "http://127.0.0.1:8093"  # khop port mac dinh cua scripts/run_slm_server.ps1
    slm_model_id: str = "qwen2.5-3b-instruct-q4_k_m"
    slm_timeout_s: float = Field(default=8.0, gt=0.0)
    #: Timeout RIÊNG cho vai classify (SP-1) — 2 s, chặt hơn hẳn 8 s của planner:
    #: phân loại chỉ sinh ~10 token, chờ lâu hơn nghĩa là server đang ốm, và
    #: fail-safe về manual rẻ hơn bắt tài xế đợi. SP-0 đo lại số này.
    slm_classify_timeout_s: float = Field(default=2.0, gt=0.0)
    #: Timeout vai chitchat (SP-2): p95 sinh đo được 2,2 s (SP-0), 4 s là biên gấp đôi.
    slm_chitchat_timeout_s: float = Field(default=4.0, gt=0.0)

    #: **Sức chứa SLM**: tối đa bao nhiêu lượt được gọi model cùng một lúc.
    #:
    #: Đây là con số PM/PO review PR #257 (2026-08-24) đòi "chốt công khai". Nó là tham
    #: số vì máy khác nhau chịu khác nhau: máy dev có GPU đo 78 tok/s, VPS 5 vCPU đo
    #: 8,44 tok/s — cùng một hằng số cho cả hai là sai ở một trong hai chỗ.
    #:
    #: **2 là số TẠM, chưa phải số đo được.** Hai run `eval/results/slm-dong-thoi/*`
    #: cho kết luận ngược nhau về mức N=2 (một run bảo luồng trộn sạch 0/6, run kia bảo
    #: 6/6 chạm trần), và cả hai đều đo TRƯỚC khi có van lẫn `asyncio.to_thread`. Chốt
    #: lại bằng `scripts/do_luot_that_dong_thoi.py` sau khi #257 lên VPS.
    #:
    #: Ràng buộc thiết kế: phải **nhỏ hơn** trần pool xe (`vehicle_pool_size`, PR #259
    #: đặt trần 3). Bằng nhau thì van không bao giờ đóng — tối đa 3 phiên, mỗi tài xế
    #: nói xong mới nói tiếp, nên nhu cầu đồng thời không bao giờ vượt 3. Xem ADR-030.
    slm_max_concurrent: int = Field(default=2, ge=1)

    # Cau dan cho nhanh so tay: dung SLM viet, hay ghep bang mau tu chinh cau hoi?
    #
    # Mac dinh MAU. Do 19/08 tren 39 cau hoi (eval/results/cau-dan/), cung mot vai tro:
    #
    #   mau                 0 ms      0% cau dan chua so    0,00 tu la/cau
    #   Qwen 0.5B / CPU   683 ms      8% cau dan chua so    6,38 tu la/cau
    #   Qwen 3B  / dGPU   421 ms      0% cau dan chua so    1,51 tu la/cau
    #
    # 8% kia khong phai chuyen tham my. Ba cau dan that cua 0.5B:
    #   "Ap suat lop khuyen nghi cua xe la 200 kPa"  (that: 260/270 kPa)
    #   "Do sau gai lop toi thieu la 10mm"           (that: 2 mm)
    #   "Den ban ngay hoat dong vao khoang 6 gio sang"
    # Cau dan chi nhin thay CAU HOI va TEN MUC, khong doc doan nao — nen moi con so no
    # noi ra deu khong co nguon. Dung ca RAG-130 ma SPIKE-004 goi la "ca dang so nhat".
    #
    # Va tren CPU day la chang dat nhat ca luot: 2316 ms voi 3B, tuc 64% cua mot luot
    # 3600 ms. Bo no di thi ngan sach p50 2500 ms tro lai kha thi ma khong can dGPU.
    #
    # Bat lai bang `CAU_DAN_DUNG_SLM=true` de doi chung; cong chan du kien o
    # `compose.lam_sach_cau_dan` van chay tren duong do.
    cau_dan_dung_slm: bool = False

    # HITL — `safety_and_hitl.md` mục P0 mixed-plan: "expiry mặc định là 30 giây".
    # Ticket SCRUM-18 ghi 5 giây; đó là giá trị cấu hình hợp lệ cho demo IVI, không
    # phải hằng số. Xem ADR-010.
    hitl_timeout_seconds: int = Field(default=30, gt=0)

    # Auth — token demo opaque, in-memory. Xem
    # docs/superpowers/specs/2026-08-10-core-driver-apis-design.md.
    auth_token_ttl_seconds: float = Field(default=43200.0, gt=0.0)
    #: Số vòng PBKDF2-HMAC-SHA256 cho mật khẩu (`src/db.py`). Là biến cấu hình chứ
    #: không phải hằng vì đó chính là **cái giá phải trả** của KDF: bộ test đăng nhập
    #: hàng trăm lần và ở mức mặc định thì riêng việc băm đã cộng ~9 s vào mỗi lần
    #: chạy suite. `tests/conftest.py` hạ nó xuống; production không được hạ.
    auth_pbkdf2_iterations: int = Field(default=200_000, ge=1)

    # Vòng đời session (review PR #89 của Thành). Hai mốc khác nhau, đừng gộp:
    #  - `session_ttl_hours`  : bao lâu thì phiên **hết dùng được**. Đo theo THỜI GIAN
    #    chứ không theo số lượng — trần đếm-theo-số làm phiên của một người chết vì
    #    lưu lượng của người khác, đúng cái 403 oan mà #46 vừa bỏ đi. 24 h > TTL token
    #    (12 h) nên trong thực tế token luôn hết hạn trước, và người dùng đăng nhập lại
    #    chứ không gặp phiên chết giữa chừng.
    #  - `session_retention_days`: bao lâu thì **xoá hẳn hàng**. 30 ngày theo mốc lưu
    #    trữ mà `docs/data_model.md:43` đã chốt cho bảng này. Giữ hàng đã hết hạn thêm
    #    một thời gian là có chủ đích: `status='expired'` + `ended_at` còn đọc được thì
    #    mới truy được "phiên đó kết thúc lúc nào", xoá ngay là mất dấu vết audit.
    session_ttl_hours: float = Field(default=24.0, gt=0.0)
    session_retention_days: float = Field(default=30.0, gt=0.0)

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # RAG — ADR-003 chốt FAISS + SQLite, không dùng Chroma.
    # Hai ngưỡng dưới là kết quả hiệu chỉnh trên eval/datasets/manual/v1,
    # không phải số chọn theo cảm tính. Chạy lại: python -m src.rag.cli calibrate
    rag_index_dir: str = "./data/rag/vf9_2026_vi"
    rag_min_score: float = Field(default=0.848, ge=0.0, le=1.0)
    rag_min_overlap: float = Field(default=0.65, ge=0.0, le=1.0)

    #: Gốc thư mục artifact eval. `GET /metrics/eval-snapshot` chỉ ĐỌC ở đây và
    #: không bao giờ ghi — thư mục run là bất biến.
    eval_results_dir: str = "./eval/results"

    # Thac chon cau (E5 -> cross-encoder bge). Do 18/08 tren
    # eval/datasets/manual/v1/answer_keys.jsonl, 39 ca, CPU:
    #   F1 tap chi so  40,2% -> 54,1%   (+13,9)
    #   F1 phu ky tu   44,1% -> 57,5%   (+13,4)
    #   do tre p50 523 ms, p95 983 ms
    # Chay lai: python scripts/do_thac_chon_cau.py
    #
    # Mac dinh TAT vi trong so nam ngoai git (models/reranker/** trong .gitignore,
    # 2,2 GB) va CI khong co chung. Thieu trong so thi selector tra [] va lo trinh
    # roi ve luat S1 — suy giam em, nhung mot tinh nang mac dinh bat ma im lang
    # khong chay la thu khong ai phat hien ra.
    chon_cau_thac_enabled: bool = False
    chon_cau_thac_model_dir: str = "./models/reranker/bge-reranker-v2-m3"
    chon_cau_thac_pool: int = Field(default=4, ge=1)
    chon_cau_thac_top: int = Field(default=2, ge=1)
    chon_cau_thac_int8: bool = True

    # Voice adapter (STT/TTS) — names match docs/devops.md Environment contract
    stt_provider: str = "sherpa_onnx"
    stt_model_path: str = "./models/voice/zipformer-30m-rnnt-6000h"
    # Descriptive only — Zipformer's int8 quantization is fixed by which ONNX
    # files get_stt_engine() loads, not read as a runtime parameter here.
    stt_compute_type: str = "int8"
    stt_max_audio_seconds: int = Field(default=30, ge=1, le=30)
    #: Bật lớp sửa chính tả theo cụm lệnh trên đường thoại thật.
    #:
    #: **Mặc định `False`, và đó là một quyết định phát hành chứ không phải mặc định
    #: cẩn thận cho vui.** Bằng chứng hiện có là 16 audio Piper **tổng hợp** — giọng
    #: máy, không phải người thật — nên nó không nói được gì về WER thật, và cũng chưa
    #: đo được số câu bị sửa **sai** (`false-correction`), thứ nguy hiểm hơn WER trung
    #: bình vì nó đổi *ý* của một câu hỏi sổ tay.
    #:
    #: Tiêu chí bật mặc định (review #317, điều kiện 3), phải đủ **cả ba**:
    #:
    #: 1. WAV **người thật** cho cả nhóm lệnh ngắn và nhóm câu tự nhiên
    #:    (`scripts/ghi_wav_lenh_ngan.py`), chạy A/B trên đúng cùng bộ audio.
    #: 2. WER corrected < WER raw trên bộ ấy.
    #: 3. `false-correction` trên nhóm câu hỏi sổ tay = **0**. Một câu hỏi bị đổi ý là
    #:    hỏng nặng hơn hẳn một lệnh chép sai: lệnh sai thì tài xế thấy xe làm sai và
    #:    nói lại, còn câu hỏi bị đổi ý trả về một câu trả lời trông hợp lý cho một câu
    #:    hỏi khác.
    #:
    #: Chưa đủ ba thì `scripts/do_wer_sua_chinh_ta.py` và `src/services/sua_chinh_ta_thoai.py`
    #: vẫn ở dạng thử nghiệm — chạy được, đo được, nhưng không nằm trên đường của tài xế.
    stt_correction_enabled: bool = False
    tts_provider: str = "piper"
    tts_model_path: str = "./models/voice/vi_VN-piper.onnx"

    # Health probe — GET /healthz. Timeout bounds every probe individually so
    # one hung dependency can't hang the whole endpoint; TTL caches the STT/TTS
    # smoke-test result so frequent polling doesn't re-run real inference every
    # call. See docs/superpowers/specs/2026-08-09-healthz-endpoint-design.md.
    health_probe_timeout_s: float = Field(default=5.0, gt=0.0)
    health_voice_probe_ttl_s: float = Field(default=10.0, gt=0.0)
    # rag_index probe re-hash checksum + chạy 1 query thật (FAISS/embedder) mỗi
    # lần gọi — cùng loại chi phí với STT/TTS smoke test, cache theo TTL để
    # /healthz không tốn CPU không cần thiết mỗi lần poll (issue #51).
    health_rag_probe_ttl_s: float = Field(default=10.0, gt=0.0)

    # Observability kỹ sư — GET /traces/{id}, GET /metrics/summary, /ws/engineer.
    # `metrics_window_seconds`: api_spec.md chốt cửa sổ nửa mở `[from,to)` UTC nhưng
    # KHÔNG nói rolling hay since-boot, và không định nghĩa query param nào. Chọn
    # rolling để dashboard phản ánh "gần đây" thay vì trung bình cả phiên demo. Xem
    # docs/tasks/TASK-BE-OBS-001 §4.
    metrics_window_seconds: int = Field(default=3600, gt=0)
    trace_store_maxsize: int = Field(default=200, ge=1)
    # Nhịp sampler dùng chung cho MỌI kết nối engineer, không phải mỗi socket một cái.
    engineer_metrics_interval_s: float = Field(default=5.0, gt=0.0)
    engineer_health_interval_s: float = Field(default=10.0, gt=0.0)

    # MQTT — hợp đồng ở docs/mqtt_spec.md, tên biến theo docs/devops.md.
    # Đặt False để chạy backend không cần broker (test, CI).
    mqtt_enabled: bool = True
    mqtt_url: str = "mqtt://localhost:1883"
    #: Nén câu trả lời sổ tay bằng SLM trước khi đọc. **Tắt mặc định**, và tắt mặc
    #: định là hợp đồng chứ không phải sự rụt rè: `slm_enabled` cũng tắt mặc định
    #: (ADR-006/ADR-010), nên mọi checkout vẫn trả lời 100% bằng luật + trích nguyên
    #: văn. Bật cờ này là đổi bề mặt câu trả lời, nên nó phải là một lựa chọn có ý thức.
    #:
    #: Cổng an toàn ở `src/agents/tom_tat.py` không do cờ này điều khiển: bật cờ mà
    #: model vi phạm hợp đồng dãy-con thì `tom()` trả `None` và composer dùng nguyên
    #: văn — ca xấu nhất của tính năng này bằng ca bình thường của tính năng cũ.
    tom_tat_enabled: bool = False
    tom_tat_endpoint: str = "http://127.0.0.1:8093"
    vehicle_id: str = "vehicle-demo-01"

    # Pool xe ảo — mỗi phiên tài xế thuê một xe, thay vì cả hệ dùng chung một chiếc.
    #
    # Vì sao cần: `vehicle_id` một mình nghĩa là mọi người điều khiển CÙNG một xe, nên
    # cơ chế chống ghi đè theo `state_version` bị kích hoạt liên tục — kế hoạch nhiều
    # bước của người này bị cắt giữa chừng và phê duyệt HITL bị vô hiệu chỉ vì người kia
    # vừa bật điều hoà. Xem `src/services/vehicle_pool.py`.
    #
    # MẶC ĐỊNH 1 là có chủ đích: hành vi giống HỆT bản chưa có pool, nên bật nhiều xe là
    # một lựa chọn tường minh của người vận hành chứ không phải thứ tự nhiên xảy ra.
    #
    # Trần thực tế là 3, và đó là **con số đo được**: llama-server bão hoà quanh 3 lượt
    # đồng thời (run `20260823T120422`), còn STT/TTS có khoá toàn cục nên chỉ phục vụ một
    # người một lúc. RAM KHÔNG phải ràng buộc — 13 KB mỗi xe ảo, 512 KB mỗi phiên backend
    # (run `20260823T102102`, `20260823T103405`). Nâng số này quá 3 là mua thêm xe cho một
    # cái cổ chai nằm ở chỗ khác.
    vehicle_pool_size: int = Field(default=1, ge=1)

    # Hợp đồng thuê xe hết hạn sau bao lâu KHÔNG hoạt động. Người dùng đóng tab không báo
    # cho server, nên không có TTL thì mỗi lượt khách ghé qua là một chiếc xe mất vĩnh viễn.
    #
    # 180 s: dài hơn hẳn một lượt hội thoại (kể cả lượt planner chậm nhất đo được ~30 s và
    # một chu kỳ HITL 30 s), nhưng đủ ngắn để người xem demo không phải đợi lâu khi tới
    # lượt mình. Gia hạn xảy ra ở `session_state._touch()`, tức mọi đường vào.
    vehicle_lease_ttl_s: float = Field(default=180.0, gt=0.0)

    mqtt_backend_username: str = ""
    mqtt_backend_password: str = ""
    mqtt_backend_password_file: str = ""
    mqtt_simulator_username: str = ""
    mqtt_simulator_password: str = ""
    mqtt_simulator_password_file: str = ""

    # Executor chờ CommandEvent bao lâu trước khi coi là transient transport
    # failure. Hết hạn thì được retry đúng một lần với cùng command_id.
    mqtt_command_timeout_ms: int = Field(default=3000, ge=100)
    # Nhịp heartbeat 5s; quá 15s (lỡ 3 nhịp) thì vehicle_simulator = down.
    mqtt_heartbeat_interval_s: float = Field(default=5.0, gt=0)
    mqtt_heartbeat_stale_s: float = Field(default=15.0, gt=0)

    # Kênh harness `v1/sim/` — ADR-024, nằm NGOÀI hợp đồng xe.
    #
    # Có mặt vì kịch bản nghiệm thu số 4 của `docs/huong_dan_chay.md` §3.3 (chặn
    # cứng S3 khi xe đang chạy) tới nay chỉ dựng được bằng cách gõ `speed 45` vào
    # stdin của `python -m src.vehicle_sim` — thứ không ai chạm được trên một bản
    # deploy công khai.
    #
    # Mặc định TẮT ở cả hai đầu, và tắt nghĩa là **không tồn tại**: backend trả 404
    # (không phải 403, vì 403 xác nhận route có thật), xe ảo không subscribe. Bật
    # một đầu mà quên đầu kia thì lệnh rơi vào hư không, nên `docs/devops.md` yêu
    # cầu đặt biến này cho **cả hai** service.
    sim_control_enabled: bool = False

    # Chu kỳ tự chạy — ADR-024 mục 7. Xe tự lặp 0 km/h ↔ `sim_drive_cycle_speed_kph`,
    # gọi đúng `set_motion()` mà console stdin gọi, nên không mở thêm bề mặt nào.
    #
    # Tách khỏi cờ trên để dựng được cấu hình "xe tự chạy, không ai đổi được" —
    # đúng cấu hình muốn có cho một link công khai không có người trực.
    sim_drive_cycle: bool = False
    sim_drive_cycle_speed_kph: float = Field(default=45.0, ge=0.0, le=200.0)
    sim_drive_cycle_phase_s: float = Field(default=30.0, gt=0)

    def backend_password(self) -> str:
        return _read_secret(self.mqtt_backend_password, self.mqtt_backend_password_file)

    def simulator_password(self) -> str:
        return _read_secret(self.mqtt_simulator_password, self.mqtt_simulator_password_file)

    def vehicle_pool_ids(self) -> tuple[str, ...]:
        """Id của mọi xe trong pool. `vehicle_id` LUÔN là ô số 0.

        Thứ tự quan trọng, không phải chi tiết trang trí: `VehiclePool` cấp theo đúng thứ
        tự này, nên **một người dùng duy nhất luôn rơi vào `vehicle_id`** — chiếc xe mà
        màn kỹ sư, `probe_vehicle_simulator`, healthcheck của docker-compose, các test và
        toàn bộ tài liệu đang trỏ tới. Đảo thứ tự là làm hỏng tất cả những chỗ đó cùng lúc,
        và hỏng theo kiểu chỉ lộ ra khi có đúng một người dùng.

        Với `vehicle_pool_size = 1` hàm trả về đúng một phần tử, tức hệ chạy y hệt bản
        chưa có pool.
        """
        them = (f"vivi-xe-{i:02d}" for i in range(2, self.vehicle_pool_size + 1))
        return (self.vehicle_id, *them)


def _read_secret(inline: str, path: str) -> str:
    """Ưu tiên biến trực tiếp; nếu trống thì đọc file secret.

    devops.md yêu cầu mount password qua file (`/run/secrets/...`); biến trực
    tiếp chỉ để chạy local cho nhanh.
    """
    if inline:
        return inline
    if path:
        secret = Path(path)
        if secret.is_file():
            return secret.read_text(encoding="utf-8").strip()
    return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
