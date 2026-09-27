import { sessionService } from "../session";
import { isAuthFailureCode, reportAuthFailure } from "../shared/authFailure";
import { ServiceError } from "../shared/errors";
import { toBase64Url } from "../shared/ws";
import { LOCKED_UI_POLICY, SIM_HARNESS_ABSENT_CODE } from "./types";
import type {
  AssistantState,
  Citation,
  DriverEvent,
  HeadlightMode,
  RoutineStepStatus,
  RoutineTerminalStatus,
  RoutinePreview,
  RoutineSetupRequired,
  SimGear,
  SimMotionResult,
  ToolResultStatus,
  TrunkPosition,
  TurnCancelReason,
  TurnService,
  UiPolicy,
  VehicleState,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const WS_IVI_URL = process.env.NEXT_PUBLIC_WS_IVI_URL ?? "ws://localhost:8000/ws/ivi";

interface ApiErrorBody {
  error?: { code?: string; message?: string; retryable?: boolean };
}

function authHeaders(): Record<string, string> {
  const stored = sessionService.getStoredSession();
  if (!stored) {
    // `getStoredSession()` trả null cũng có nghĩa nó vừa tự xoá một session hết
    // hạn — báo lên để trang đưa người dùng về /login thay vì để lời gọi này
    // chết lặng trong một `.catch(() => {})` nào đó.
    reportAuthFailure("Phiên đăng nhập đã hết hạn.");
    throw new ServiceError({ code: "AUTH_REQUIRED", message: "Chưa đăng nhập.", retryable: false });
  }
  return { Authorization: `Bearer ${stored.accessToken}` };
}

function currentSessionId(): string {
  const session = sessionService.getCurrentDriverSession();
  if (!session) {
    throw new ServiceError({
      code: "REQUEST_CONTEXT_INVALID",
      message: "Chưa có session — gọi sessionService.createDriverSession() trước.",
      retryable: false,
    });
  }
  return session.sessionId;
}

/**
 * Chạy một lời gọi gắn session; nếu backend từ chối vì session đã chết thì tạo
 * session mới rồi thử lại **đúng một lần**.
 *
 * Vì sao cần: session hết hạn **không** trả 401. `src/api/session_state.py:155-180`
 * phát hiện hết hạn tại thời điểm đọc, CAS `active → expired` rồi trả `None`, và cả
 * bốn call site dịch `None` thành cùng một `403 FORBIDDEN "session không tồn tại hoặc
 * không thuộc về bạn"` — cố ý gộp với ca "của người khác" để không rò enumeration
 * (review PR #89). Nên ngay khi 403 thôi đăng xuất, ca này mất luôn đường phục hồi:
 * token còn sống nhưng mọi lượt nói đều 403, và tài xế kẹt đúng như bug `W-5` vừa
 * sửa, chỉ khác nguyên nhân. Đường tới nó có thật — token TTL 12 h ngắn hơn session
 * TTL 24 h, còn `DRIVER_SESSION_KEY` không bị xoá khi đăng nhập lại.
 *
 * **Chỉ bọc `/turns/*`.** `/approvals/{id}/decision` và `/citations/{id}` cũng trả 403
 * khi session chết, nhưng session mới không cứu được chúng: approval nằm trong
 * checkpoint của graph cũ, citation gắn phiên cũ, cả hai mồ côi theo. Thử lại ở đó chỉ
 * tốn một vòng để nhận lại đúng 403, và tệ hơn là vứt ngữ cảnh hội thoại đi để đổi lấy
 * không gì cả — đúng nhánh đó phải nổi lỗi lên bề mặt thay vì tự chữa.
 *
 * `run` phải dựng lại request từ đầu mỗi lần gọi: `sendText`/`sendVoice` nhúng
 * `currentSessionId()` vào cả `Idempotency-Key` lẫn body, nên một thunk chụp sẵn
 * request cũ sẽ gửi lại đúng cái session vừa chết.
 */
async function withFreshSession<T>(run: () => Promise<T>): Promise<T> {
  try {
    return await run();
  } catch (error) {
    if (!(error instanceof ServiceError) || error.code !== "FORBIDDEN") throw error;
    const stale = sessionService.getCurrentDriverSession();
    if (!stale) throw error;
    // Cố ý KHÔNG bọc try: `createDriverSession` trượt thì lỗi của chính nó mới là lỗi
    // đáng báo — 401 ở đó tự gọi `reportAuthFailure` và đưa người dùng về `/login`.
    await sessionService.createDriverSession(stale.vehicleId);
    // Đúng một lần, và nằm NGOÀI `try` nên 403 lần hai đi thẳng ra ngoài thay vì
    // vòng lại tạo session lần nữa.
    return run();
  }
}

async function throwIfError(res: Response, fallbackCode: string): Promise<void> {
  if (res.ok) return;
  const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
  const code = body?.error?.code ?? fallbackCode;
  const message = body?.error?.message ?? "Yêu cầu thất bại.";
  // CHỈ 401. Thử lại với cùng token chỉ lặp lại đúng lỗi đó, nên phải báo lên trang
  // để đăng xuất sạch kể cả khi call site nuốt lỗi (poll trạng thái xe ở
  // DriverShellProvider bỏ qua mọi lần trượt — đúng cho lỗi mạng, im lặng chết
  // người cho lỗi xác thực).
  //
  // 403 KHÔNG thuộc nhóm này: token vẫn sống, chỉ là tài nguyên vừa xin bị từ chối
  // (sai role, Origin, hoặc của người khác). Xem `isAuthFailureCode` để biết vì sao
  // gộp hai mã lại là fail-closed quá tay. Ca 403 vì session hết hạn có đường phục
  // hồi riêng ở `withFreshSession` bên dưới.
  if (res.status === 401) reportAuthFailure(message);
  throw new ServiceError({
    code,
    message,
    retryable: body?.error?.retryable ?? false,
  });
}

/** Export để test được trực tiếp: đây đúng là chỗ từng hard-code `lights`/`trunk` (issue #115). */
export function mapVehicleState(raw: {
  vehicle_id: string;
  state_version: number;
  observed_at: string;
  motion: { speed_kph: number; gear: string; ignition: string };
  hvac: { power: boolean; temperature_c: number; fan_level: number };
  windows: { front_left: number; front_right: number; rear_left: number; rear_right: number };
  doors: { front_left: string; front_right: string; rear_left: string; rear_right: string };
  media: { status: string; volume: number; track: string | null };
  navigation: { status: string; destination_id: string | null };
  seat: {
    front_left: { heating: number; fore_aft: number; recline: number; height: number };
    front_right: { heating: number; fore_aft: number; recline: number; height: number };
  };
  lights: { headlight: HeadlightMode; interior: boolean };
  trunk: { position: TrunkPosition };
}): VehicleState {
  return {
    vehicleId: raw.vehicle_id,
    stateVersion: raw.state_version,
    observedAt: raw.observed_at,
    motion: { speedKph: raw.motion.speed_kph, gear: raw.motion.gear, ignition: raw.motion.ignition },
    hvac: { power: raw.hvac.power, temperatureC: raw.hvac.temperature_c, fanLevel: raw.hvac.fan_level },
    windows: {
      frontLeft: raw.windows.front_left,
      frontRight: raw.windows.front_right,
      rearLeft: raw.windows.rear_left,
      rearRight: raw.windows.rear_right,
    },
    doors: {
      frontLeft: raw.doors.front_left,
      frontRight: raw.doors.front_right,
      rearLeft: raw.doors.rear_left,
      rearRight: raw.doors.rear_right,
    },
    media: { status: raw.media.status, volume: raw.media.volume, track: raw.media.track },
    navigation: { status: raw.navigation.status, destinationId: raw.navigation.destination_id },
    seat: {
      frontLeft: {
        heating: raw.seat.front_left.heating,
        foreAft: raw.seat.front_left.fore_aft,
        recline: raw.seat.front_left.recline,
        height: raw.seat.front_left.height,
      },
      frontRight: {
        heating: raw.seat.front_right.heating,
        foreAft: raw.seat.front_right.fore_aft,
        recline: raw.seat.front_right.recline,
        height: raw.seat.front_right.height,
      },
    },
    // Từ PR #92 backend gửi thật cả hai domain này — trước đây chỗ này hard-code
    // `false`/`"closed"`, nên UI KHẲNG ĐỊNH SAI về xe: cốp mở thật mà màn hình
    // vẫn ghi "đóng" (issue #115). Không đặt mặc định phòng hờ ở đây: thiếu field
    // là hợp đồng bị vi phạm, phải vỡ to và sớm chứ không im lặng nói dối.
    lights: { headlight: raw.lights.headlight, interior: raw.lights.interior },
    trunk: { position: raw.trunk.position },
  };
}

/**
 * Mapping sự kiện WS thô (snake_case, đúng docs/api_spec.md) sang DriverEvent
 * đã chuẩn hoá của FE. Chỉ xử lý các type trong "Driver server-event
 * allowlist" — type lạ bị bỏ qua (không throw, để không sập kết nối vì 1
 * field mới BE thêm sau này).
 */
/** Payload WS dùng `snake_case`; `Citation` khai `camelCase`. Phải ánh xạ, không ép kiểu.
 *
 * Bản trước viết `p.citations as Citation[]`. `as` là khẳng định lúc **biên dịch** và
 * không sinh mã, nên lúc chạy mỗi phần tử vẫn mang `citation_id`/`document_title` —
 * `citationId` và `documentTitle` là `undefined`. Ba trường còn lại (`section`, `page`,
 * `excerpt`) trùng tên ở cả hai bên nên vẫn hiện đúng, và chính điều đó làm lỗi khó
 * thấy: danh sách trông gần như bình thường.
 *
 * Ba hệ quả đo được trên máy, không phải suy đoán:
 *
 * 1. `<li key={citation.citationId}>` nhận `undefined` cho mọi phần tử — đây là cảnh
 *    báo "unique key prop" hiện ở góc màn hình.
 * 2. `expandedId === citation.citationId` thành `undefined === undefined`, nên bấm MỘT
 *    trích dẫn sẽ mở bung **cả năm**.
 * 3. `getCitation(citationId)` gọi `GET /citations/undefined`.
 *
 * TypeScript không bắt được lớp lỗi này, nên chỗ duy nhất chặn được là một test chạy
 * trên payload thật của backend — xem `real.citations.test.ts`.
 */
function mapCitations(raw: unknown): Citation[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const c = item as Record<string, unknown>;
    return {
      citationId: (c.citation_id as string) ?? "",
      documentTitle: (c.document_title as string) ?? "",
      section: (c.section as string) ?? "",
      page: (c.page as number) ?? 0,
      excerpt: (c.excerpt as string) ?? "",
    };
  });
}

/** Cùng lỗi ép kiểu với `mapCitations`: payload là `step_id`, type khai `stepId`. */
function mapOutcomes(raw: unknown): { stepId: string; status: string }[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const o = item as Record<string, unknown>;
    return { stepId: (o.step_id as string) ?? "", status: (o.status as string) ?? "" };
  });
}

export function mapRoutinePreview(raw: unknown): RoutinePreview | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw !== "object" || Array.isArray(raw)) {
    console.warn("Bỏ qua routine_preview sai contract.");
    return null;
  }
  const preview = raw as Record<string, unknown>;
  if (
    typeof preview.routine_id !== "string" ||
    preview.routine_id.trim() === "" ||
    typeof preview.routine_name !== "string" ||
    preview.routine_name.trim() === "" ||
    !Array.isArray(preview.steps)
  ) {
    console.warn("Bỏ qua routine_preview sai contract.");
    return null;
  }
  const steps = preview.steps.map((rawStep) => {
    if (typeof rawStep !== "object" || rawStep === null || Array.isArray(rawStep)) return null;
    const step = rawStep as Record<string, unknown>;
    if (
      !Number.isInteger(step.index) ||
      (step.index as number) < 0 ||
      typeof step.action !== "string" ||
      step.action.trim() === "" ||
      typeof step.description !== "string" ||
      step.description.trim() === ""
    ) {
      return null;
    }
    return { index: step.index as number, action: step.action, description: step.description };
  });
  if (steps.some((step) => step === null)) {
    console.warn("Bỏ qua routine_preview sai contract.");
    return null;
  }
  return {
    routineId: preview.routine_id,
    routineName: preview.routine_name,
    steps: steps as RoutinePreview["steps"],
  };
}

/** Cùng khuôn validate-hết-hoặc-vứt với `mapRoutinePreview` — issue #385. */
export function mapRoutineSetupRequired(raw: unknown): RoutineSetupRequired | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw !== "object" || Array.isArray(raw)) {
    console.warn("Bỏ qua routine_setup_required sai contract.");
    return null;
  }
  const setup = raw as Record<string, unknown>;
  if (
    typeof setup.routine_id !== "string" ||
    setup.routine_id.trim() === "" ||
    typeof setup.ma_loi !== "string" ||
    setup.ma_loi.trim() === "" ||
    !Array.isArray(setup.thieu) ||
    setup.thieu.some((label) => typeof label !== "string")
  ) {
    console.warn("Bỏ qua routine_setup_required sai contract.");
    return null;
  }
  return { routineId: setup.routine_id, maLoi: setup.ma_loi, thieu: setup.thieu as string[] };
}

export function mapServerEvent(raw: {
  type: string;
  session_id?: string;
  turn_id?: string;
  payload: Record<string, unknown>;
}): DriverEvent | null {
  const turnId = raw.turn_id ?? "";
  const p = raw.payload;

  switch (raw.type) {
    case "turn.accepted":
      return { type: "turn.accepted", turnId, inputMode: p.input_mode as "voice" | "text" };
    case "transcript.partial":
      return { type: "transcript.partial", turnId, text: p.text as string };
    case "transcript.final":
      return { type: "transcript.final", turnId, text: p.text as string, confidence: p.confidence as number };
    case "assistant.status":
      return {
        type: "assistant.status", turnId, state: p.state as AssistantState
      };
    case "plan.ready":
      return {
        type: "plan.ready",
        turnId,
        routeKind: p.route_kind as "action" | "manual" | "response",
        planId: (p.plan_id as string | null) ?? null,
        summary: p.summary as string,
        requiresApproval: p.requires_approval as boolean,
        // Backend cũ chưa có trường này -> mảng rỗng, client vẫn chạy được, chỉ là
        // không tự chuyển màn. Hỏng vì thiếu một trường mới thì tệ hơn im lặng.
        steps: Array.isArray(p.steps)
          ? (p.steps as Record<string, unknown>[]).map((step) => ({
              stepId: step.step_id as string,
              tool: step.tool as string,
              domain: (step.domain as string | null) ?? null,
              args: (step.args as Record<string, unknown>) ?? {},
            }))
          : [],
      };
    case "approval.required":
      return {
        type: "approval.required",
        turnId,
        approvalId: p.approval_id as string,
        planId: p.plan_id as string,
        approvedVehicleStateVersion: p.approved_vehicle_state_version as number,
        expiresAt: p.expires_at as string,
      };
    case "approval.intent.detected":
      // Ánh xạ tay từng trường, KHÔNG `as`: payload là `snake_case`, type khai
      // `camelCase`, và `as` không sinh mã nên mọi trường sẽ là `undefined` lúc chạy.
      // Đúng lớp lỗi đã sửa ở #136 (`citation_id` -> `citationId`).
      return {
        type: "approval.intent.detected",
        turnId,
        approvalId: p.approval_id as string,
        originalTurnId: p.original_turn_id as string,
        decision: p.decision as "approve" | "reject",
        approvedVehicleStateVersion: p.approved_vehicle_state_version as number,
        // KHÔNG `?? false`: `undefined` (BE cũ, chưa có #207) và `false` (BE cố ý
        // không chốt) phải phân biệt được ở nơi tiêu thụ — gộp chúng lại là biến
        // "chưa biết" thành "chắc chắn chưa chốt", tức bỏ luôn đường lui theo
        // phiên bản. Xem docstring `committed` trong types.ts.
        committed: p.committed as boolean | undefined,
      };
    case "action.blocked":
      return { type: "action.blocked", turnId, reason: p.reason as string };
    case "tool.result":
      return {
        type: "tool.result",
        turnId,
        stepId: p.step_id as string,
        status: p.status as ToolResultStatus,
        // null với "completed", bắt buộc với failed/timeout/skipped (api_spec.md).
        errorCode: (p.error_code as string | null | undefined) ?? null,
      };
    case "assistant.speech":
      return {
        type: "assistant.speech",
        turnId,
        audioBase64: p.audio_base64 as string,
        mimeType: p.mime_type as string,
      };
    case "assistant.response":
      return {
        type: "assistant.response",
        turnId,
        result: {
          displayText: p.display_text as string,
          speakText: p.speak_text as string,
          citations: mapCitations(p.citations),
          outcomes: mapOutcomes(p.outcomes),
          // `=== true` chứ không `as boolean`: backend chưa gửi field này (PR
          // #108 chưa merge) thì `undefined as boolean` lọt qua TypeScript
          // nhưng ra `undefined` lúc chạy, và mọi chỗ đọc nó phải tự phòng.
          // Ép về false ngay tại biên là chỗ rẻ nhất — không có nút thì đúng
          // như hôm nay, còn nút dẫn tới ngõ cụt thì tệ hơn không có.
          hasMoreToRead: p.has_more_to_read === true,
          moMicNgan: p.mo_mic_ngan === true,
          routinePreview: mapRoutinePreview(p.routine_preview),
          routineSetupRequired: mapRoutineSetupRequired(p.routine_setup_required),
        },
      };
    case "turn.completed":
      return { type: "turn.completed", turnId };
    case "turn.failed":
      return { type: "turn.failed", turnId, code: p.code as string };
    case "turn.canceled":
      return { type: "turn.canceled", turnId, reason: p.reason as TurnCancelReason };
    case "error":
      return {
        type: "error",
        code: p.code as string,
        message: p.message as string,
        retryable: p.retryable as boolean,
      };
    case "routine.started":
      return {
        type: "routine.started",
        executionId: turnId,
        routineId: p.routine_id as string,
        routineName: p.routine_name as string,
        routineVersion: p.routine_version as number,
        steps: Array.isArray(p.steps)
          ? (p.steps as Record<string, unknown>[]).map((s) => ({
              index: s.index as number,
              action: s.action as string,
              description: s.description as string,
            }))
          : [],
        startedAt: p.started_at as string,
      };
    case "routine.step":
      return {
        type: "routine.step",
        executionId: turnId,
        index: p.index as number,
        action: p.action as string,
        status: p.status as RoutineStepStatus,
        description: p.description as string,
        errorCode: (p.error_code as string | null | undefined) ?? null,
        approvalId: p.approval_id as string | undefined,
      };
    case "routine.finished":
      return {
        type: "routine.finished",
        executionId: turnId,
        routineId: p.routine_id as string,
        status: p.status as RoutineTerminalStatus,
        terminalReason: (p.terminal_reason as string | null | undefined) ?? null,
        results: Array.isArray(p.results)
          ? (p.results as Record<string, unknown>[]).map((r) => ({
              index: r.index as number,
              action: r.action as string,
              description: r.description as string,
              status: r.status as RoutineStepStatus,
              errorCode: (r.error_code as string | null | undefined) ?? null,
            }))
          : [],
        completedAt: p.completed_at as string,
        audioBase64: (p.audio_base64 as string | null | undefined) ?? null,
        mimeType: (p.mime_type as string | null | undefined) ?? null,
      };
    case "ui.policy": {
      const up = p.ui_policy as Record<string, unknown>;
      const uiPolicy: UiPolicy = {
        allowTextInput: up.allow_text_input as boolean,
        lockSmallControls: up.lock_small_controls as boolean,
        enlargeMicButton: up.enlarge_mic_button as boolean,
        maxVisibleActions: up.max_visible_actions as number,
        preferVoiceConfirmation: up.prefer_voice_confirmation as boolean,
        allowDetailedDocumentBrowsing: up.allow_detailed_document_browsing as boolean,
        // Sự kiện THẬT từ backend nghĩa là WS còn sống — backend không biết
        // khái niệm "mất kết nối" (xem UiPolicy.controlsLocked), nên chỉ có
        // nhánh close/error bên dưới mới được đặt true.
        controlsLocked: false,
      };
      return { type: "ui.policy", uiPolicy };
    }
    default:
      return null;
  }
}

export const realTurnService: TurnService = {
  async getVehicleState() {
    // Bắt buộc từ khi pool xe ảo bật (PR #259): thiếu session_id lúc pool
    // đang cấp phát trả về 400 REQUEST_CONTEXT_INVALID (server không biết trả
    // xe nào). Vô hại khi pool tắt (VEHICLE_POOL_SIZE=1) — tham số dư không
    // đổi gì.
    const res = await fetch(`${API_BASE}/vehicle/state?session_id=${encodeURIComponent(currentSessionId())}`, {
      headers: authHeaders(),
    });
    await throwIfError(res, "REQUEST_CONTEXT_INVALID");
    const body = (await res.json()) as { data: { vehicle_state: Parameters<typeof mapVehicleState>[0] } };
    return mapVehicleState(body.data.vehicle_state);
  },

  async sendText(text) {
    return withFreshSession(async () => {
      const res = await fetch(`${API_BASE}/turns/text`, {
        method: "POST",
        headers: {
          ...authHeaders(),
          "X-Schema-Version": "1.0",
          "Idempotency-Key": `turn:${currentSessionId()}:${Date.now()}`,
          "Content-Type": "application/json; charset=utf-8",
        },
        body: JSON.stringify({ session_id: currentSessionId(), text }),
      });
      await throwIfError(res, "INPUT_INVALID");
      const body = (await res.json()) as {
        data: { turn_id: string; routine_preview?: unknown; routine_setup_required?: unknown };
      };
      return {
        turnId: body.data.turn_id,
        routinePreview:
          body.data.routine_preview === undefined ? undefined : mapRoutinePreview(body.data.routine_preview),
        routineSetupRequired:
          body.data.routine_setup_required === undefined
            ? undefined
            : mapRoutineSetupRequired(body.data.routine_setup_required),
      };
    });
  },

  async sendVoice(audio, opts) {
    return withFreshSession(async () => {
      const res = await fetch(`${API_BASE}/turns/voice?session_id=${currentSessionId()}`, {
        method: "POST",
        headers: {
          ...authHeaders(),
          "X-Schema-Version": "1.0",
          // spec §3.5 — `auto` chỉ khiến xe IM hơn, không bao giờ dễ dãi hơn.
          "X-Capture-Mode": opts?.auto ? "auto" : "manual",
          "Idempotency-Key": `voice:${currentSessionId()}:${Date.now()}`,
          "Content-Type": audio.type || "audio/wav",
        },
        body: audio,
      });
      await throwIfError(res, "INPUT_INVALID");
      const body = (await res.json()) as { data: { turn_id: string } };
      return { turnId: body.data.turn_id };
    });
  },

  async decideApproval(approvalId, decision, approvedVehicleStateVersion) {
    const res = await fetch(`${API_BASE}/approvals/${approvalId}/decision`, {
      method: "POST",
      headers: {
        ...authHeaders(),
        "X-Schema-Version": "1.0",
        "Idempotency-Key": `approval:${approvalId}:${decision}`,
        "Content-Type": "application/json; charset=utf-8",
      },
      body: JSON.stringify({ decision, approved_vehicle_state_version: approvedVehicleStateVersion }),
    });
    await throwIfError(res, "APPROVAL_INVALIDATED_STATE");
  },

  async getCitation(citationId) {
    const res = await fetch(`${API_BASE}/citations/${citationId}`, { headers: authHeaders() });
    await throwIfError(res, "REQUEST_CONTEXT_INVALID");
    const body = (await res.json()) as {
      data: { citation_id: string; document_title: string; section: string; page: number; excerpt: string };
    };
    return {
      citationId: body.data.citation_id,
      documentTitle: body.data.document_title,
      section: body.data.section,
      page: body.data.page,
      excerpt: body.data.excerpt,
    };
  },

  async setSimSpeed(speedKph, gear) {
    // KHÔNG bọc `withFreshSession`: route harness không nhận `session_id` và
    // không đụng tới graph, nên 403 ở đây chỉ có thể là sai role/Origin — tạo
    // session mới không cứu được gì, chỉ tốn thêm một vòng để nhận lại đúng 403.
    //
    // Cũng không gửi `Idempotency-Key`: route không đọc header đó, và gửi thừa
    // là hứa một ngữ nghĩa không ai thực thi. Kéo thanh trượt hai lần cùng giá
    // trị vốn đã vô hại — `SimulatorRuntime.set_motion()` trả False và không
    // tăng `state_version` khi giá trị không đổi.
    const res = await fetch(`${API_BASE}/sim/motion`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json; charset=utf-8" },
      // Bỏ hẳn khoá `gear` khi người gọi không truyền, thay vì gửi `null`.
      // `SimMotionSet` là `extra="forbid"` nhưng chấp nhận `gear: null`, nên cả
      // hai cách đều chạy — chọn cách này để body khớp đúng ví dụ trong PR #206
      // và để "không nói gì về số" khác hẳn "nói rằng số là null".
      body: JSON.stringify(gear === undefined ? { speed_kph: speedKph } : { speed_kph: speedKph, gear }),
    });
    // fallbackCode là NOT_FOUND, không phải INPUT_INVALID: ca hay gặp nhất ở
    // route này là 404 *không có* envelope lỗi — backend chưa có kênh harness
    // thì FastAPI trả `{"detail":"Not Found"}`. Gán nhầm mã ở đây sẽ khiến UI
    // hiện toast lỗi cho một cấu hình hoàn toàn bình thường.
    await throwIfError(res, SIM_HARNESS_ABSENT_CODE);
    const body = (await res.json()) as { accepted: boolean; speed_kph: number; gear: SimGear | null };
    // Thân trả về THÔ, không có `{data:...}` — route nằm ngoài 14 interface P0
    // nên không đi qua khuôn envelope. Đọc như envelope sẽ ra undefined lặng lẽ.
    const result: SimMotionResult = {
      accepted: body.accepted,
      speedKph: body.speed_kph,
      gear: body.gear ?? null,
    };
    return result;
  },

  subscribe(onEvent) {
    // Trước đây mở đúng 1 lần lúc mount, không bao giờ kết nối lại. `/ws/ivi`
    // rớt sau một khoảng idle (trình duyệt/hệ điều hành ngủ tab, proxy đóng
    // kết nối rảnh...) là chuyện bình thường — nhưng không reconnect nghĩa là
    // MỌI sự kiện turn sau đó (kể cả turn.completed) rơi vào hư vô, StatusBar
    // kẹt "Đang xử lý…" vĩnh viễn, người dùng phải bấm lại nhiều lần hoặc
    // reload mới hết. Backend đã hỗ trợ sẵn replay cursor (ADR-014, ring buffer
    // 200 event / TTL 30 phút) — chỉ cần FE thật sự dùng nó.
    let stopped = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let lastEventId: string | null = null;
    let lastSequence: number | null = null;
    let attempt = 0;

    function scheduleReconnect() {
      if (stopped) return;
      attempt += 1;
      const delayMs = Math.min(1000 * attempt, 8000);
      reconnectTimer = setTimeout(connect, delayMs);
    }

    function connect() {
      if (stopped) return;
      const stored = sessionService.getStoredSession();
      const session = sessionService.getCurrentDriverSession();
      if (!stored) {
        // Không còn token: mở socket cũng chỉ để bị đóng bằng 4401. Trước đây
        // nhánh này `return` câm — socket chết vĩnh viễn, không reconnect, không
        // báo ai, UI đứng nguyên trạng thái cuối cùng. Fail-closed rồi báo lên.
        onEvent({ type: "ui.policy", uiPolicy: LOCKED_UI_POLICY });
        reportAuthFailure("Phiên đăng nhập đã hết hạn.");
        stopped = true;
        return;
      }
      // Thiếu `session` (chưa createDriverSession xong) KHÁC hẳn: đó là trạng
      // thái khởi động bình thường, `bootstrap()` sẽ subscribe lại sau khi có.
      if (!session) return;

      ws = new WebSocket(WS_IVI_URL, ["vivi.v1", `bearer.${toBase64Url(stored.accessToken)}`]);

      ws.addEventListener("open", () => {
        attempt = 0;
        ws?.send(
          JSON.stringify({
            type: "connection.init",
            client_message_id: `cmsg_${Date.now()}`,
            sent_at: new Date().toISOString(),
            schema_version: "1.0",
            session_id: session.sessionId,
            // Kèm cursor lần reconnect trở đi — server replay đúng những event
            // đã phát trong lúc mất kết nối trước khi bơm live event tiếp.
            ...(lastEventId ? { last_event_id: lastEventId, last_sequence: lastSequence } : {}),
          }),
        );
      });

      ws.addEventListener("message", (msg) => {
        try {
          const raw = JSON.parse(msg.data as string);
          if (raw.type === "error" && raw.payload?.terminal) {
            const code = raw.payload.code as string;
            if (code === "REPLAY_CURSOR_INVALID" || code === "REPLAY_WINDOW_EXPIRED") {
              // Cursor hỏng/hết cửa sổ replay — bỏ cursor, để nhánh "close" bên
              // dưới tự reconnect lại từ đầu (server đã tự đóng socket này rồi).
              lastEventId = null;
              lastSequence = null;
              return;
            }
            // AUTH_REQUIRED/FORBIDDEN: token/quyền không còn hợp lệ, retry mù
            // chỉ tổ lặp lại đúng lỗi — báo cho UI (case "error" bên dưới) và
            // dừng hẳn, chờ người dùng đăng nhập lại (remount sẽ subscribe mới).
            //
            // Fail-closed (PM/PO review PR #100, 2026-08-14, blocker thứ 2):
            // phải phát LOCKED_UI_POLICY ở ĐÂY, TRƯỚC khi set stopped = true —
            // handler "close" bên dưới tự return sớm khi stopped đã true (đúng
            // ý, không được reconnect sau lỗi xác thực), nên nếu đợi tới đó
            // mới khoá thì sẽ không bao giờ khoá: socket đóng ngay sau message
            // này (server tự đóng kèm terminal error), rơi thẳng vào nhánh
            // "đã stopped, return" mà không phát sự kiện nào cả.
            onEvent({ type: "ui.policy", uiPolicy: LOCKED_UI_POLICY });
            if (isAuthFailureCode(code)) {
              reportAuthFailure((raw.payload.message as string) || "Phiên đăng nhập không còn hiệu lực.");
            }
            stopped = true;
          }
          if (typeof raw.event_id === "string") lastEventId = raw.event_id;
          if (typeof raw.sequence === "number") lastSequence = raw.sequence;
          const mapped = mapServerEvent(raw);
          if (mapped) onEvent(mapped);
        } catch {
          // Bỏ qua message không parse được — không được để 1 message lỗi làm sập subscriber.
        }
      });

      ws.addEventListener("close", (event) => {
        if (stopped) return;
        // 4401/4403 (api_spec.md mục "WebSocket contracts") đều là lỗi xác thực chứ
        // không phải mạng rớt, nên cả hai đều dừng hẳn: reconnect chỉ lặp lại đúng
        // lỗi đó mỗi 8 giây. Trước đây close handler không nhận `event` nên mọi lý do
        // đóng bị gộp làm một, và nhánh dừng-hẳn duy nhất là frame `error` terminal —
        // chỉ tới nơi khi server kịp gửi nó. Đọc close code là phòng thủ không phụ
        // thuộc điều đó.
        //
        // Nhưng chỉ 4401 mới đăng xuất. 4403 là sai role hoặc Origin không nằm trong
        // `cors_origins` (`src/api/ws.py`) — token vẫn sống nguyên, và cả hai ca đó
        // đều là lỗi cấu hình/triển khai chứ không phải phiên chết. Xoá phiên đăng
        // nhập ở đây vừa không sửa được gì, vừa giấu mất nguyên nhân thật (PM/PO
        // review PR #157).
        if (event.code === 4401 || event.code === 4403) {
          onEvent({ type: "ui.policy", uiPolicy: LOCKED_UI_POLICY });
          if (event.code === 4401) reportAuthFailure("Phiên đăng nhập không còn hiệu lực.");
          stopped = true;
          return;
        }
        // Fail-closed khi mất WS (PM/PO review PR #100, 2026-08-14): trước đây
        // rớt socket chỉ âm thầm tự reconnect, `uiPolicy` ở Provider giữ
        // nguyên giá trị cuối cùng nhận được (có thể đang MỞ, vd lúc xe đứng
        // yên) suốt thời gian mất kết nối — sai với chủ đích "không tự suy
        // luận UI policy, luôn siết chặt khi không chắc chắn". Phát thẳng
        // LOCKED_UI_POLICY qua đúng path "ui.policy" đã có ở
        // DriverShellProvider, không cần thêm case/state mới; chỉ event
        // `ui.policy` THẬT từ backend sau khi reconnect xong mới mở lại.
        onEvent({ type: "ui.policy", uiPolicy: LOCKED_UI_POLICY });
        scheduleReconnect();
      });
    }

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  },
};
