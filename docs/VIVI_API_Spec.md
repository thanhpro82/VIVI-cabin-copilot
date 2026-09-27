# 🔌 OpenAPI Specification: VIVI Cabin Copilot

> ⚠️ **LƯU Ý (PRODUCT VISION / HIGH-LEVEL PRD — HỌ A)**:
> Đây là tài liệu ý tưởng & yêu cầu sản phẩm tầng trên (BMAD Product Docs). **KHÔNG dùng file này làm spec kỹ thuật để lập trình/implement.**
> Khi viết code, dựng API/DB hay tạo Task, vui lòng tham chiếu bộ **Canonical Engineering Specs (Họ B)** tại [`technical_spec.md`](technical_spec.md), [`api_spec.md`](api_spec.md) và [`data_model.md`](data_model.md).
>
> Riêng `GET /api/v1/vehicle/state` ở mục 2.5: bản mẫu cũ dùng `ac` / `music` / `windows: {driver, passenger}` / `speed_kmh` / `driving_mode` — **toàn bộ đều lệch canonical**. Đã thay bằng shape thật đang chạy; hợp đồng transport tương ứng ở [`mqtt_spec.md`](mqtt_spec.md).

**Tác giả:** Winston (System Architect)  
**Dự án:** VIVI Cabin Copilot — Trợ lý ảo đa phương thức trong xe hơi  
**Phiên bản:** 1.1 | **Ngày:** 2026-08-03  

---

## 1. Overview (Tổng quan REST APIs)

Tài liệu đặc tả toàn bộ giao diện lập trình ứng dụng REST APIs và WebSockets của VIVI Cabin Copilot Backend (FastAPI).

- **Base URL:** `http://localhost:8000/api/v1`
- **WebSocket URL:** `ws://localhost:8000/ws`
- **Authentication:** Bearer Session Token / Role Header (`X-Role: driver` | `X-Role: engineer`)

---

## 2. API Endpoints Chi tiết

### 2.1. Authentication APIs
#### `POST /api/v1/auth/login`
- **Description:** Đăng nhập vào hệ thống IVI theo vai trò.
- **Request Body:**
  ```json
  {
    "username": "driver_minh",
    "role": "driver"
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "status": "SUCCESS",
    "access_token": "token_abc123_session",
    "role": "driver",
    "redirect_url": "/ivi"
  }
  ```

---

### 2.2. Voice & Speech Processing APIs
#### `POST /api/v1/voice/transcribe`
- **Description:** Tải file âm thanh giọng nói (Audio Blob) từ Web Mic để chuyển thành văn bản bằng Faster-Whisper.
- **Request (Multipart Form-Data):** `file: audio/wav`
- **Response (200 OK):**
  ```json
  {
    "transcript": "Bật điều hòa 22 độ",
    "confidence": 0.94,
    "latency_ms": 380
  }
  ```

---

### 2.3. Agent Execution APIs
#### `POST /api/v1/agent/process`
- **Description:** Gửi câu hỏi hoặc lệnh tiếng Việt tới LangGraph Agent Pipeline.
- **Request Body:**
  ```json
  {
    "query": "Bật điều hòa 22 độ",
    "vehicle_speed_kmh": 45.0,
    "user_role": "driver"
  }
  ```
- **Response Case 1: Lệnh điều khiển xe bình thường (200 OK)**
  ```json
  {
    "status": "SUCCESS",
    "intent": "CONTROL_AC",
    "response_text": "Đã chỉnh điều hòa xuống 22 độ C.",
    "tool_calls": [
      {
        "tool_name": "control_ac",
        "parameters": { "target_temp": 22, "fan_speed": 3 }
      }
    ],
    "hitl_pending": false,
    "latency_ms": 1420
  }
  ```
- **Response Case 2: Kích hoạt Xác nhận HITL (200 OK)**
  ```json
  {
    "status": "PENDING_HITL",
    "intent": "CONTROL_WINDOW",
    "response_text": "Xe đang chạy 75 km/h. Bạn có chắc chắn muốn mở hết cửa kính không?",
    "hitl_pending": true,
    "hitl_action_id": "act_win_9921",
    "timeout_seconds": 5
  }
  ```

---

### 2.4. HITL Safety Confirmation API
#### `POST /api/v1/hitl/confirm`
- **Description:** Phê duyệt hoặc từ chối lệnh nhạy cảm từ Modal Popup trên IVI Screen.
- **Request Body:**
  ```json
  {
    "hitl_action_id": "act_win_9921",
    "confirmed": true
  }
  ```
- **Response (200 OK):**
  ```json
  {
    "status": "EXECUTED",
    "message": "Lệnh mở cửa kính đã được gửi tới hệ thống xe thành công."
  }
  ```

---

### 2.5. Vehicle Control & Virtual State APIs
#### `GET /api/v1/vehicle/state`
- **Description:** Lấy trạng thái hiện tại của xe ảo — 7 domain: chuyển động, điều hòa, cửa sổ, cửa, media, dẫn đường, ghế.
- **Response (200 OK):** shape canonical, xem [`api_spec.md`](api_spec.md) và [`data_model.md`](data_model.md).
  ```json
  {
    "data": {
      "vehicle_state": {
        "vehicle_id": "vehicle-demo-01",
        "state_version": 42,
        "observed_at": "2026-08-03T02:00:12Z",
        "motion": { "speed_kph": 0, "gear": "P", "ignition": "ON" },
        "hvac": { "power": true, "temperature_c": 24, "fan_level": 3 },
        "windows": { "front_left": 0, "front_right": 0, "rear_left": 0, "rear_right": 0 },
        "doors": { "front_left": "closed", "front_right": "closed", "rear_left": "closed", "rear_right": "closed" },
        "media": { "status": "paused", "volume": 35, "track": null },
        "navigation": { "status": "idle", "destination_id": null },
        "seat": {
          "front_left":  { "heating": 0, "fore_aft": 50, "recline": 50, "height": 50 },
          "front_right": { "heating": 0, "fore_aft": 50, "recline": 50, "height": 50 }
        }
      }
    },
    "meta": { "request_id": "req_state_001" },
    "trace_id": "tr_state_001",
    "schema_version": "1.0"
  }
  ```
  Bốn điểm khác bản mẫu cũ: `ac` → `hvac` (`temp` → `temperature_c`), `music` → `media`, `speed_kmh` → `motion.speed_kph`, và `windows` dùng **4 cửa** `front_left`/`front_right`/`rear_left`/`rear_right` chứ không phải `driver`/`passenger`. Không còn `driving_mode` — chính sách UI do backend phát qua `ui_policy`, FE không tự suy ra từ tốc độ.

---

### 2.6. Engineer Diagnostics & Admin APIs
#### `GET /api/v1/admin/metrics`
- **Description:** Lấy danh sách thống kê thời gian thực cho Engineer Dashboard.
- **Response (200 OK):**
  ```json
  {
    "system_status": "ONLINE",
    "metrics": {
      "avg_latency_ms": 2150,
      "intent_accuracy_percent": 88.2,
      "grounded_rate_percent": 94.5,
      "hallucination_rate_percent": 3.1,
      "ram_usage_gb": 3.18,
      "total_queries": 540
    }
  }
  ```

---

### 2.7. WebSocket Realtime Channels
- **`WS /ws/ivi`**: Push thông báo trạng thái xe ảo realtime, Popup HITL và âm thanh TTS streaming.
- **`WS /ws/dashboard`**: Push biểu đồ thống kê chỉ số Latency, Intent Accuracy và Audit Logs realtime cho Kỹ sư.
