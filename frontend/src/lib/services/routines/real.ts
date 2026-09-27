import { sessionService } from "../session";
import { reportAuthFailure } from "../shared/authFailure";
import { ServiceError } from "../shared/errors";
import type { Routine, RoutineDraft, RoutineExecution, RoutinesService } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface ApiErrorBody {
  error?: { code?: string; message?: string; retryable?: boolean; details?: Record<string, unknown> };
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
  // Cùng lý do với turn/real.ts và engineer/real.ts: bọc lời gọi bằng
  // `.catch()` im lặng biến 401 thành "chưa có dữ liệu" nếu không báo ở đây.
  if (res.status === 401) reportAuthFailure(message);
  throw new ServiceError({
    code: body?.error?.code ?? fallbackCode,
    message,
    retryable: body?.error?.retryable ?? false,
    // ROUTINE_RUNNING mang `{execution_id}` (#298) — nối "xoá thất bại vì
    // đang chạy" sang nút Dừng mà không phải domain nào cũng cần đọc field
    // này, nên chỉ pass-through, không gán tên riêng.
    details: body?.error?.details,
  });
}

/**
 * `RoutineData` (`src/models/api.py`) -> `Routine`. Mọi field khác `steps` đổi
 * `snake_case` -> `camelCase`; `steps` giữ NGUYÊN — backend cố ý không đổi
 * dạng nó (đọc docstring `RoutineData.steps`), nên khác với `mapCitations`/
 * `mapVehicleState` ở `turn/real.ts`, `as` ở đây không che một lệch tên field
 * nào: khoá của mỗi step đã đúng camelCase của `RoutineStep` từ phía backend.
 */
export function mapRoutine(raw: {
  id: string;
  user_id: string;
  name: string;
  icon: Routine["icon"];
  enabled: boolean;
  steps: unknown;
  is_default_template: boolean;
  template_origin: Routine["templateOrigin"];
  version: number;
  needs_preview: boolean;
  needs_setup: boolean;
  runnable: boolean;
  created_at: string;
  updated_at: string;
}): Routine {
  return {
    id: raw.id,
    userId: raw.user_id,
    name: raw.name,
    icon: raw.icon,
    enabled: raw.enabled,
    steps: raw.steps as Routine["steps"],
    isDefaultTemplate: raw.is_default_template,
    templateOrigin: raw.template_origin,
    needsPreview: raw.needs_preview,
    needsSetup: raw.needs_setup,
    runnable: raw.runnable,
    version: raw.version,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

/** Thân `POST/PUT /routines` — đã đúng hình dạng backend cần, không phải dịch gì thêm. */
function draftBody(draft: RoutineDraft): { name: string; icon: string; steps: unknown } {
  return { name: draft.name, icon: draft.icon, steps: draft.steps };
}

/** `RoutineExecutionData` (`src/models/api.py`) -> `RoutineExecution`. Toàn bộ field snake_case -> camelCase. */
export function mapExecution(raw: {
  id: string;
  routine_id: string;
  session_id: string;
  routine_version: number;
  status: RoutineExecution["status"];
  current_index: number;
  approval_id: string | null;
  steps_total: number;
  results: { index: number; action: string; status: RoutineExecution["results"][number]["status"]; description: string; error_code: string | null }[];
  terminal_reason: string | null;
  created_at: string;
  updated_at: string;
}): RoutineExecution {
  return {
    id: raw.id,
    routineId: raw.routine_id,
    sessionId: raw.session_id,
    routineVersion: raw.routine_version,
    status: raw.status,
    currentIndex: raw.current_index,
    approvalId: raw.approval_id,
    stepsTotal: raw.steps_total,
    results: raw.results.map((r) => ({
      index: r.index,
      action: r.action,
      status: r.status,
      description: r.description,
      errorCode: r.error_code,
    })),
    terminalReason: raw.terminal_reason,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

export const realRoutinesService: RoutinesService = {
  async listRoutines() {
    const res = await fetch(`${API_BASE}/routines`, { headers: authHeaders() });
    await throwIfError(res, "FORBIDDEN");
    const body = (await res.json()) as { data: { items: Parameters<typeof mapRoutine>[0][] } };
    return body.data.items.map(mapRoutine);
  },

  async createRoutine(draft) {
    const res = await fetch(`${API_BASE}/routines`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify(draftBody(draft)),
    });
    await throwIfError(res, "ROUTINE_NAME_INVALID");
    const body = (await res.json()) as { data: Parameters<typeof mapRoutine>[0] };
    return mapRoutine(body.data);
  },

  async updateRoutine(id, draft) {
    const res = await fetch(`${API_BASE}/routines/${id}`, {
      method: "PUT",
      headers: { ...authHeaders(), "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify(draftBody(draft)),
    });
    await throwIfError(res, "ROUTINE_NOT_FOUND");
    const body = (await res.json()) as { data: Parameters<typeof mapRoutine>[0] };
    return mapRoutine(body.data);
  },

  async setEnabled(id, enabled) {
    const res = await fetch(`${API_BASE}/routines/${id}/enabled`, {
      method: "PUT",
      headers: { ...authHeaders(), "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ enabled }),
    });
    await throwIfError(res, "ROUTINE_NOT_FOUND");
    const body = (await res.json()) as { data: Parameters<typeof mapRoutine>[0] };
    return mapRoutine(body.data);
  },

  async deleteRoutine(id) {
    const res = await fetch(`${API_BASE}/routines/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    // 204 không có thân — `throwIfError` chỉ đọc body khi !res.ok, an toàn ở đây.
    await throwIfError(res, "ROUTINE_NOT_FOUND");
  },

  async restoreDefault(id) {
    const res = await fetch(`${API_BASE}/routines/${id}/restore-default`, {
      method: "POST",
      headers: authHeaders(),
    });
    await throwIfError(res, "ROUTINE_NOT_FOUND");
    const body = (await res.json()) as { data: Parameters<typeof mapRoutine>[0] };
    return mapRoutine(body.data);
  },

  async runRoutine(id, sessionId) {
    const res = await fetch(`${API_BASE}/routines/${id}/run`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    // 202: lần chạy chưa xong khi trả về (docstring route backend) — vẫn map
    // như bình thường, `throwIfError` chỉ nhìn `res.ok` (2xx), không riêng 200.
    await throwIfError(res, "ROUTINE_NOT_RUNNABLE");
    const body = (await res.json()) as { data: Parameters<typeof mapExecution>[0] };
    return mapExecution(body.data);
  },

  async getExecution(executionId) {
    const res = await fetch(`${API_BASE}/routine-executions/${executionId}`, { headers: authHeaders() });
    await throwIfError(res, "ROUTINE_EXECUTION_NOT_FOUND");
    const body = (await res.json()) as { data: Parameters<typeof mapExecution>[0] };
    return mapExecution(body.data);
  },

  async cancelExecution(executionId) {
    const res = await fetch(`${API_BASE}/routine-executions/${executionId}/cancel`, {
      method: "POST",
      headers: authHeaders(),
    });
    // 200 (không phải 204): thân trả về là RoutineExecutionEnvelope, xem docstring interface.
    await throwIfError(res, "ROUTINE_EXECUTION_NOT_FOUND");
    const body = (await res.json()) as { data: Parameters<typeof mapExecution>[0] };
    return mapExecution(body.data);
  },
};
