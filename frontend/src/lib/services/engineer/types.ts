export interface StageLatencyStat {
  count: number;
  p50: number | null;
  p95: number | null;
}

export interface MetricsSummary {
  window: { from: string; to: string };
  turns: { accepted: number; completed: number; failed: number; canceled: number };
  stageLatencyMs: Record<string, StageLatencyStat>;
  mqtt: { publishAttempts: number; published: number; errors: number; errorRate: number | null };
  rag: {
    answered: number;
    grounded: number;
    abstained: number;
    groundedRate: number | null;
    abstentionRate: number | null;
  };
  safety: {
    validationDenied: number;
    blockedS3: number;
    approvalsRequired: number;
    approved: number;
    rejected: number;
    expired: number;
  };
  actionAudit: { attempted: number; completed: number; failed: number; timeout: number };
}

export type ComponentStatus = "ready" | "degraded" | "down";

export interface HealthStatus {
  status: ComponentStatus;
  /** Rỗng khi đọc từ nhánh 503 — nhánh đó không có checked_at (xem docs/handoff/BE-to-FE-vehicle-and-mqtt.md mục 4). */
  checkedAt: string | null;
  /** latencyMs vắng mặt ở nhánh 503 — error.details.dependencies chỉ có {status, code}. */
  components: Record<string, { status: ComponentStatus; latencyMs?: number }>;
}

/**
 * Map từ trace schema thật (GET /traces/{id} và sự kiện WS "trace" —
 * xem docs/api_spec.md).
 *
 * Đường biên redact, chốt ở ADR-029: Engineer thấy `safe_summary` (mô tả sinh
 * từ outcome + tên tool) VÀ `answer_text` (câu VIVI trả lời, do server sinh).
 * Engineer vẫn KHÔNG thấy câu nói nguyên văn của tài xế hay nội dung trích dẫn
 * thô — backend không lưu chúng ngay từ đầu. Nên cột "Câu nói" trong wireframe
 * Dashboard Kỹ sư vẫn không có field tương ứng; cột "Trả lời" thì từ nay có.
 */
export interface EngineerLogEntry {
  traceId: string;
  turnId: string;
  time: string;
  routeSource: string | null;
  safeSummary: string;
  /** Câu VIVI trả lời. `null` khi lượt hỏng trước lúc compose. */
  answerText: string | null;
  /**
   * Xe mà lượt này tác động lên. Hôm nay cả hệ chỉ có một xe nên nó là hằng;
   * nó phân biệt được các xe sau khi ADR-028 (pool xe ảo theo phiên) vào, và đó
   * là lúc bảng đội xe dùng tới.
   */
  vehicleId: string | null;
  approvalStatus: string | null;
  status: string;
  latencyMs: number | null;
}

export type EngineerEvent =
  | { type: "trace"; entry: EngineerLogEntry }
  | { type: "metrics"; summary: MetricsSummary }
  | { type: "health"; health: HealthStatus }
  | { type: "error"; code: string; message: string };

export type VehicleTrim = "eco" | "plus";
export type VehicleBattery = "sdi" | "catl";

/**
 * Cấu hình xe tĩnh (`GET/PUT /api/v1/vehicle/profile`, issue #123) — KHÁC
 * `VehicleState`: trim/pin không đổi khi xe chạy, không đi qua MQTT, không có
 * `state_version` (xem src/services/vehicle_profile.py).
 *
 * `null` ở đây **có nghĩa** là "chưa khai báo", không phải "dùng mặc định":
 * sổ tay VF9 cho bốn giá trị áp suất lốp khác nhau theo trim × pin, nên tự điền
 * một giá trị là nói cho tài xế một con số của chiếc xe khác. FE không được
 * coalesce về bất kỳ giá trị nào.
 */
export interface VehicleProfile {
  vehicleId: string;
  trim: VehicleTrim | null;
  battery: VehicleBattery | null;
  /**
   * Do **backend** quyết, FE không tự tính lại `trim != null && battery != null`.
   * Đây là cổng fail-closed của cả nhánh áp suất lốp; để mỗi client tự suy là
   * mời mỗi client tự nghĩ ra một luật riêng (src/models/api.py:219).
   */
  isComplete: boolean;
  updatedAt: string | null;
}

/** Thân `PUT /vehicle/profile`: ghi đè cả cặp, `null` tường minh là **xoá**. */
export interface VehicleProfileUpdate {
  trim: VehicleTrim | null;
  battery: VehicleBattery | null;
}

export type EvalSuite = "rag" | "agent-intent";

/**
 * Ảnh chụp một run eval (`GET /metrics/eval-snapshot`) — **không** phải số đo
 * trực tiếp từ hệ thống đang chạy, nên không được trộn vào khối Live.
 * `MetricsSummary` fold traffic vừa xảy ra; cái này phát lại một phép đo đã đóng
 * gói trên bộ đề có đáp án khoá. Hai loại số đó không cộng được.
 *
 * `metrics` để mở vì mỗi suite có bộ chỉ số riêng và run cũ có bộ chỉ số cũ —
 * khai cứng ở đây thì thêm một phép đo ở backend sẽ làm vỡ việc đọc run đã đóng băng.
 *
 * `gradedBy` là `null` với run ghi trước khi manifest tồn tại. UI hiện `—`;
 * không được đoán, vì trộn nhầm nguồn chấm là đúng thứ trường này chặn.
 */
export interface EvalSnapshot {
  suite: EvalSuite;
  runId: string;
  metrics: Record<string, number | string | null>;
  gradedBy: string | null;
  dataset: string | null;
  note: string | null;
}

export interface EngineerService {
  getMetricsSummary(): Promise<MetricsSummary>;
  /** `null` = suite chưa có run nào. Đó là trạng thái bình thường, không phải lỗi. */
  getEvalSnapshot(suite: EvalSuite): Promise<EvalSnapshot | null>;
  getHealth(): Promise<HealthStatus>;
  getVehicleProfile(): Promise<VehicleProfile>;
  setVehicleProfile(update: VehicleProfileUpdate): Promise<VehicleProfile>;
  /** Trả về hàm unsubscribe. Consumer tự giữ ring buffer (~200 dòng), xem ARCHITECTURE.md mục 6.1. */
  subscribe(onEvent: (event: EngineerEvent) => void): () => void;
}
