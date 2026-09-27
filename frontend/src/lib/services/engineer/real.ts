import { sessionService } from "../session";
import { isAuthFailureCode, reportAuthFailure } from "../shared/authFailure";
import { ServiceError } from "../shared/errors";
import { toBase64Url } from "../shared/ws";
import type {
  ComponentStatus,
  EngineerEvent,
  EngineerLogEntry,
  EngineerService,
  EvalSuite,
  HealthStatus,
  MetricsSummary,
  StageLatencyStat,
  VehicleBattery,
  VehicleProfile,
  VehicleProfileUpdate,
  VehicleTrim,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const WS_ENGINEER_URL = process.env.NEXT_PUBLIC_WS_ENGINEER_URL ?? "ws://localhost:8000/ws/engineer";

interface ApiErrorBody {
  error?: { code?: string; message?: string; retryable?: boolean };
}

function authHeaders(): Record<string, string> {
  const stored = sessionService.getStoredSession();
  if (!stored) {
    reportAuthFailure("Phiên đăng nhập đã hết hạn.");
    throw new ServiceError({ code: "AUTH_REQUIRED", message: "Chưa đăng nhập.", retryable: false });
  }
  return { Authorization: `Bearer ${stored.accessToken}` };
}

async function throwIfError(res: Response, fallbackCode: string): Promise<void> {
  if (res.ok) return;
  const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
  const message = body?.error?.message ?? "Yêu cầu thất bại.";
  // Cùng lý do với turn/real.ts: EngineerShellProvider bọc mọi lần trượt bằng
  // `.catch(() => setMetrics(null))`, nên 401 hiện ra y hệt "chưa có dữ liệu".
  //
  // Chỉ 401. Ở màn hình kỹ sư, 403 gần như luôn là `require_engineer`
  // (`src/api/auth_deps.py:82`) từ chối một tài khoản driver đăng nhập hợp lệ —
  // đăng xuất họ vừa sai vừa che mất thông tin duy nhất hữu ích, rằng họ đang dùng
  // nhầm vai trò. Lỗi nổi lên bề mặt qua `ServiceError` bên dưới.
  if (res.status === 401) reportAuthFailure(message);
  throw new ServiceError({
    code: body?.error?.code ?? fallbackCode,
    message,
    retryable: body?.error?.retryable ?? false,
  });
}

interface RawStageStat {
  count: number;
  p50: number | null;
  p95: number | null;
}

function mapMetrics(raw: {
  window: { from: string; to: string };
  turns: { accepted: number; completed: number; failed: number; canceled: number };
  stage_latency_ms: Record<string, RawStageStat>;
  mqtt: { publish_attempts: number; published: number; errors: number; error_rate: number | null };
  rag: {
    answered: number;
    grounded: number;
    abstained: number;
    grounded_rate: number | null;
    abstention_rate: number | null;
  };
  safety: {
    validation_denied: number;
    blocked_s3: number;
    approvals_required: number;
    approved: number;
    rejected: number;
    expired: number;
  };
  action_audit: { attempted: number; completed: number; failed: number; timeout: number };
}): MetricsSummary {
  const stageLatencyMs: Record<string, StageLatencyStat> = {};
  for (const [key, stat] of Object.entries(raw.stage_latency_ms)) {
    stageLatencyMs[key] = { count: stat.count, p50: stat.p50, p95: stat.p95 };
  }
  return {
    window: raw.window,
    turns: raw.turns,
    stageLatencyMs,
    mqtt: {
      publishAttempts: raw.mqtt.publish_attempts,
      published: raw.mqtt.published,
      errors: raw.mqtt.errors,
      errorRate: raw.mqtt.error_rate,
    },
    rag: {
      answered: raw.rag.answered,
      grounded: raw.rag.grounded,
      abstained: raw.rag.abstained,
      groundedRate: raw.rag.grounded_rate,
      abstentionRate: raw.rag.abstention_rate,
    },
    safety: {
      validationDenied: raw.safety.validation_denied,
      blockedS3: raw.safety.blocked_s3,
      approvalsRequired: raw.safety.approvals_required,
      approved: raw.safety.approved,
      rejected: raw.safety.rejected,
      expired: raw.safety.expired,
    },
    actionAudit: raw.action_audit,
  };
}

function mapHealth(raw: {
  status: ComponentStatus;
  checked_at: string;
  components: Record<string, { status: ComponentStatus; latency_ms: number }>;
}): HealthStatus {
  return {
    status: raw.status,
    checkedAt: raw.checked_at,
    components: Object.fromEntries(
      Object.entries(raw.components).map(([k, v]) => [k, { status: v.status, latencyMs: v.latency_ms }]),
    ),
  };
}

/**
 * Nhánh 503 của /healthz có shape KHÁC nhánh 200 (error.details.dependencies,
 * không có checked_at/latency_ms) — cố ý theo api_spec.md:495, xem
 * docs/handoff/BE-to-FE-vehicle-and-mqtt.md mục 4. Đọc cả hai thay vì chỉ
 * throw khi thiếu `data`, để AlertBanner vẫn thấy đúng component nào down.
 */
function mapHealthFromErrorDetails(dependencies: Record<string, { status: ComponentStatus; code?: string }>): HealthStatus {
  return {
    status: "down",
    checkedAt: null,
    components: Object.fromEntries(Object.entries(dependencies).map(([k, v]) => [k, { status: v.status }])),
  };
}

/**
 * Xuất ra để test được, cùng lý do với `mapVehicleProfile`: đây là phép ánh xạ
 * thuần, và chỗ dễ hỏng nhất của nó là những `?? ` nuốt mất `null`.
 */
export function mapTraceEntry(raw: {
  trace_id: string;
  turn_id?: string;
  vehicle_id?: string | null;
  route_source: string | null;
  safe_summary: string;
  answer_text?: string | null;
  status: string;
  safety_summary?: { admission?: string };
  stage_latencies_ms?: { end_to_end?: number };
  approval_wait_ms?: number;
}): EngineerLogEntry {
  return {
    traceId: raw.trace_id,
    turnId: raw.turn_id ?? "",
    time: new Date().toLocaleTimeString("vi-VN", { hour12: false }),
    routeSource: raw.route_source,
    safeSummary: raw.safe_summary,
    // `?? null` chứ không `?? ""`: "chưa từng trả lời" khác "trả lời rỗng", và
    // LogsTable dựa vào đúng phân biệt đó để quyết định có vẽ dòng thứ hai không.
    answerText: raw.answer_text ?? null,
    vehicleId: raw.vehicle_id ?? null,
    approvalStatus: raw.safety_summary?.admission ?? null,
    status: raw.status,
    latencyMs: raw.stage_latencies_ms?.end_to_end ?? raw.approval_wait_ms ?? null,
  };
}

/**
 * `GET/PUT /vehicle/profile` -> `VehicleProfile`. Chỉ đổi tên field sang camelCase.
 *
 * Cố ý KHÔNG có `?? "eco"`, `?? false` hay bất kỳ coalesce nào: `null` là câu trả
 * lời thật của backend ("chưa khai báo"), và `is_complete` là quyết định của
 * backend chứ không phải phép tính FE lặp lại được. Một mặc định lẻn vào đây sẽ
 * hiện cho engineer một cấu hình mà xe không có.
 */
export function mapVehicleProfile(raw: {
  vehicle_id: string;
  trim: VehicleTrim | null;
  battery: VehicleBattery | null;
  is_complete: boolean;
  updated_at: string | null;
}): VehicleProfile {
  return {
    vehicleId: raw.vehicle_id,
    trim: raw.trim,
    battery: raw.battery,
    isComplete: raw.is_complete,
    updatedAt: raw.updated_at,
  };
}

/**
 * Thân PUT. Hai field luôn **có mặt**, kể cả khi giá trị là `null`: backend đòi
 * đủ cặp (`VehicleProfileUpdate`, `extra="forbid"`), và bỏ field khỏi body là 422
 * — "quên gửi" với "cố ý xoá" phải trông khác nhau (src/models/api.py:251).
 */
export function toProfileRequestBody(update: VehicleProfileUpdate): {
  trim: VehicleTrim | null;
  battery: VehicleBattery | null;
} {
  return { trim: update.trim ?? null, battery: update.battery ?? null };
}

export const realEngineerService: EngineerService = {
  async getMetricsSummary() {
    const res = await fetch(`${API_BASE}/metrics/summary`, { headers: authHeaders() });
    await throwIfError(res, "FORBIDDEN");
    const body = (await res.json()) as { data: Parameters<typeof mapMetrics>[0] };
    return mapMetrics(body.data);
  },

  async getEvalSnapshot(suite) {
    const res = await fetch(`${API_BASE}/metrics/eval-snapshot?suite=${suite}`, {
      headers: authHeaders(),
    });
    // 404 KHÔNG phải lỗi: một suite chưa chạy eval lần nào là trạng thái hợp lệ,
    // và UI đã có nhánh hiện `—` cho nó. Ném lỗi ở đây biến "chưa đo" thành
    // "hỏng" — đúng kiểu nhầm mà ô `—` sinh ra để tránh. 401/403 thì vẫn ném,
    // vì sai quyền im lặng thành "chưa có run" là che mất thông tin duy nhất
    // hữu ích cho người đang nhìn màn hình.
    if (res.status === 404) return null;
    await throwIfError(res, "EVAL_SNAPSHOT_FAILED");

    const raw = (await res.json()) as {
      data: {
        suite: EvalSuite;
        run_id: string;
        metrics: Record<string, number | string | null>;
        graded_by: string | null;
        dataset: string | null;
        note: string | null;
      };
    };
    return {
      suite: raw.data.suite,
      runId: raw.data.run_id,
      metrics: raw.data.metrics,
      gradedBy: raw.data.graded_by,
      dataset: raw.data.dataset,
      note: raw.data.note,
    };
  },

  async getHealth() {
    const res = await fetch(`${API_BASE.replace(/\/api\/v1$/, "")}/healthz`, { headers: authHeaders() });
    const body = (await res.json().catch(() => null)) as {
      data?: Parameters<typeof mapHealth>[0];
      error?: { details?: { dependencies?: Parameters<typeof mapHealthFromErrorDetails>[0] } };
    } | null;
    if (body?.data) return mapHealth(body.data);
    if (body?.error?.details?.dependencies) return mapHealthFromErrorDetails(body.error.details.dependencies);
    throw new ServiceError({ code: "HEALTHZ_UNAVAILABLE", message: "Không đọc được /healthz.", retryable: true });
  },

  async getVehicleProfile() {
    const res = await fetch(`${API_BASE}/vehicle/profile`, { headers: authHeaders() });
    await throwIfError(res, "FORBIDDEN");
    const body = (await res.json()) as { data: Parameters<typeof mapVehicleProfile>[0] };
    return mapVehicleProfile(body.data);
  },

  async setVehicleProfile(update) {
    const res = await fetch(`${API_BASE}/vehicle/profile`, {
      method: "PUT",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(toProfileRequestBody(update)),
    });
    // Ghi là engineer-only (require_engineer) nên 403 là ca thường gặp nhất khi
    // đăng nhập nhầm vai — giữ nguyên code của backend để UI nói đúng lý do.
    await throwIfError(res, "FORBIDDEN");
    const body = (await res.json()) as { data: Parameters<typeof mapVehicleProfile>[0] };
    return mapVehicleProfile(body.data);
  },

  subscribe(onEvent) {
    const stored = sessionService.getStoredSession();
    if (!stored) {
      reportAuthFailure("Phiên đăng nhập đã hết hạn.");
      return () => {};
    }

    const ws = new WebSocket(WS_ENGINEER_URL, ["vivi.v1", `bearer.${toBase64Url(stored.accessToken)}`]);

    ws.addEventListener("open", () => {
      ws.send(
        JSON.stringify({
          type: "connection.init",
          client_message_id: `cmsg_${Date.now()}`,
          sent_at: new Date().toISOString(),
          schema_version: "1.0",
        }),
      );
    });

    ws.addEventListener("message", (msg) => {
      try {
        const raw = JSON.parse(msg.data as string);
        const p = raw.payload;
        let mapped: EngineerEvent | null = null;
        switch (raw.type) {
          case "trace":
            mapped = { type: "trace", entry: mapTraceEntry(p) };
            break;
          case "metrics":
            mapped = { type: "metrics", summary: mapMetrics(p) };
            break;
          case "health":
            mapped = { type: "health", health: mapHealth(p) };
            break;
          case "error":
            if (isAuthFailureCode(p.code)) reportAuthFailure(p.message || "Phiên đăng nhập không còn hiệu lực.");
            mapped = { type: "error", code: p.code, message: p.message };
            break;
          default:
            mapped = null;
        }
        if (mapped) onEvent(mapped);
      } catch {
        // Bỏ qua message không parse được.
      }
    });

    // Socket engineer không tự reconnect (khác `/ws/ivi`) — nhưng lỗi xác thực
    // thì vẫn phải nói ra, nếu không màn hình kỹ sư chỉ đơn giản ngừng cập nhật
    // mà không ai biết vì sao.
    //
    // Chỉ 4401 mới đăng xuất. 4403 ở đây là sai role hoặc Origin không hợp lệ
    // (`src/api/ws.py`), token vẫn sống — báo qua event `error` để `AlertBanner`
    // hiện lý do, chứ không xoá phiên (PM/PO review PR #157).
    ws.addEventListener("close", (event) => {
      if (event.code === 4401) {
        reportAuthFailure("Phiên đăng nhập không còn hiệu lực.");
      } else if (event.code === 4403) {
        onEvent({
          type: "error",
          code: "FORBIDDEN",
          message: "Không đủ quyền kết nối (vai trò hoặc Origin không hợp lệ).",
        });
      }
    });

    return () => ws.close();
  },
};
