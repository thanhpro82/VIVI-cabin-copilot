import { sessionService } from "../session";
import { ServiceError } from "../shared/errors";
import { ROUTINE_TEMPLATE_SEEDS } from "@/lib/fixtures/routineTemplates";
import type { Routine, RoutineDraft, RoutineExecution, RoutinesService } from "./types";

const STORAGE_PREFIX = "vivi.routines.";
const MOCK_LATENCY_MS = 300;
const MAX_STEPS = 4;

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * `usr_driver_demo` khớp `userId` mà `session/mock.ts::loginAsDriver()` gán —
 * chưa đăng nhập (SSR, hoặc test gọi thẳng service) thì coi như khách demo
 * dùng chung 1 không gian tên, KHÔNG throw: RoutinesView phải render được ở
 * mọi thời điểm trong lúc `DriverShellProvider` đang bootstrap phiên.
 */
function currentUserId(): string {
  return sessionService.getStoredSession()?.user.userId ?? "usr_driver_demo";
}

function storageKey(userId: string): string {
  return `${STORAGE_PREFIX}${userId}`;
}

/** Chuẩn hoá tên để so trùng — trim, hạ chữ thường, gộp khoảng trắng liên tiếp (acceptance criteria #271). */
function normalizeName(name: string): string {
  return name.trim().toLowerCase().replace(/\s+/g, " ");
}

/**
 * Xấp xỉ `needs_setup` của backend (#284: thiếu địa điểm Nhà/Cơ quan). Mock
 * không có service địa điểm để hỏi thật, nên dùng cùng phép suy diễn mà
 * `RoutinesView` đang tự làm hôm nay: có bước `navigation` là coi như cần
 * thiết lập. Khi #284/#370 nối đủ, backend mới là nguồn sự thật.
 */
function needsSetupTu(steps: Routine["steps"]): boolean {
  return steps.some((s) => s.action === "navigation");
}

/**
 * Khớp `doi_noi_dung` của `src/services/routines_store.py::update_routine`/
 * `restore_default`: "nội dung" chỉ gồm tên + các bước, so sánh bằng JSON —
 * đổi icon hay lưu lại y hệt nội dung cũ đều KHÔNG tính là đổi. Xác nhận qua
 * gọi API thật (#370): restore một mẫu chưa từng sửa giữ nguyên `version`.
 */
function noiDungDoi(a: { name: string; steps: Routine["steps"] }, b: { name: string; steps: Routine["steps"] }): boolean {
  return a.name !== b.name || JSON.stringify(a.steps) !== JSON.stringify(b.steps);
}

function seedTemplates(userId: string): Routine[] {
  const now = new Date().toISOString();
  return ROUTINE_TEMPLATE_SEEDS.map((seed, index) => {
    const needsSetup = needsSetupTu(seed.steps);
    return {
      id: `rtn_${userId}_${seed.origin}`,
      userId,
      name: seed.name,
      icon: seed.icon,
      enabled: true,
      steps: seed.steps,
      isDefaultTemplate: true,
      templateOrigin: seed.origin,
      // Mẫu mặc định chưa từng bị người dùng chỉnh — không cần ép preview lượt
      // đầu, khác Routine tự tạo/vừa sửa.
      needsPreview: false,
      needsSetup,
      runnable: !needsSetup,
      version: 1,
      createdAt: now,
      updatedAt: new Date(Date.now() + index).toISOString(),
    };
  });
}

function load(userId: string): Routine[] {
  if (typeof window === "undefined") return seedTemplates(userId);
  const raw = window.localStorage.getItem(storageKey(userId));
  if (!raw) {
    const seeded = seedTemplates(userId);
    window.localStorage.setItem(storageKey(userId), JSON.stringify(seeded));
    return seeded;
  }
  try {
    return JSON.parse(raw) as Routine[];
  } catch {
    const seeded = seedTemplates(userId);
    window.localStorage.setItem(storageKey(userId), JSON.stringify(seeded));
    return seeded;
  }
}

function save(userId: string, routines: Routine[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(storageKey(userId), JSON.stringify(routines));
}

/** Validate chung cho tạo mới lẫn sửa — cùng luật, khác chỗ gọi (acceptance criteria #271). */
function validateDraft(draft: RoutineDraft, existing: Routine[], excludeId: string | null): void {
  if (draft.steps.length < 1) {
    throw new ServiceError({
      code: "ROUTINE_EMPTY",
      message: "Routine phải có ít nhất một hành động.",
      retryable: true,
    });
  }
  if (draft.steps.length > MAX_STEPS) {
    throw new ServiceError({
      code: "ROUTINE_TOO_MANY_STEPS",
      message: `Routine chỉ được tối đa ${MAX_STEPS} bước.`,
      retryable: true,
    });
  }
  const normalized = normalizeName(draft.name);
  if (!normalized) {
    throw new ServiceError({
      code: "ROUTINE_NAME_EMPTY",
      message: "Routine phải có tên.",
      retryable: true,
    });
  }
  const trung = existing.some((r) => r.id !== excludeId && normalizeName(r.name) === normalized);
  if (trung) {
    throw new ServiceError({
      code: "ROUTINE_NAME_DUPLICATE",
      message: "Đã có Routine khác trùng tên này.",
      retryable: true,
    });
  }
}

function findOrThrow(routines: Routine[], id: string): Routine {
  const routine = routines.find((r) => r.id === id);
  if (!routine) {
    throw new ServiceError({ code: "ROUTINE_NOT_FOUND", message: "Không tìm thấy Routine.", retryable: false });
  }
  return routine;
}

export const mockRoutinesService: RoutinesService = {
  async listRoutines() {
    await delay(MOCK_LATENCY_MS);
    return [...load(currentUserId())].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  },

  async createRoutine(draft) {
    await delay(MOCK_LATENCY_MS);
    const userId = currentUserId();
    const routines = load(userId);
    validateDraft(draft, routines, null);
    const now = new Date().toISOString();
    const needsSetup = needsSetupTu(draft.steps);
    const routine: Routine = {
      id: `rtn_${userId}_${Date.now()}`,
      userId,
      name: draft.name.trim(),
      icon: draft.icon,
      enabled: true,
      steps: draft.steps,
      isDefaultTemplate: false,
      templateOrigin: null,
      needsPreview: true,
      needsSetup,
      runnable: !needsSetup,
      version: 1,
      createdAt: now,
      updatedAt: now,
    };
    save(userId, [...routines, routine]);
    return routine;
  },

  async updateRoutine(id, draft) {
    await delay(MOCK_LATENCY_MS);
    const userId = currentUserId();
    const routines = load(userId);
    const existing = findOrThrow(routines, id);
    validateDraft(draft, routines, id);
    const needsSetup = needsSetupTu(draft.steps);
    const trimmedName = draft.name.trim();
    const doi = noiDungDoi({ name: trimmedName, steps: draft.steps }, existing);
    const updated: Routine = {
      ...existing,
      name: trimmedName,
      icon: draft.icon,
      steps: draft.steps,
      needsPreview: true,
      needsSetup,
      runnable: existing.enabled && !needsSetup,
      // Khớp hợp đồng backend (#370): chỉ tên/bước đổi mới bump version.
      version: doi ? existing.version + 1 : existing.version,
      updatedAt: new Date().toISOString(),
    };
    save(
      userId,
      routines.map((r) => (r.id === id ? updated : r)),
    );
    return updated;
  },

  async setEnabled(id, enabled) {
    await delay(MOCK_LATENCY_MS);
    const userId = currentUserId();
    const routines = load(userId);
    const existing = findOrThrow(routines, id);
    // Bật/tắt không đổi `version` (khớp hợp đồng backend #370: chỉ tên/bước mới bump).
    const updated: Routine = {
      ...existing,
      enabled,
      runnable: enabled && !existing.needsSetup,
      updatedAt: new Date().toISOString(),
    };
    save(
      userId,
      routines.map((r) => (r.id === id ? updated : r)),
    );
    return updated;
  },

  async deleteRoutine(id) {
    await delay(MOCK_LATENCY_MS);
    const userId = currentUserId();
    const routines = load(userId);
    const existing = findOrThrow(routines, id);
    if (existing.isDefaultTemplate) {
      throw new ServiceError({
        code: "ROUTINE_DEFAULT_NOT_DELETABLE",
        message: "Không thể xoá mẫu mặc định — tắt hoặc khôi phục thay vì xoá.",
        retryable: false,
      });
    }
    save(
      userId,
      routines.filter((r) => r.id !== id),
    );
  },

  async restoreDefault(id) {
    await delay(MOCK_LATENCY_MS);
    const userId = currentUserId();
    const routines = load(userId);
    const existing = findOrThrow(routines, id);
    if (!existing.isDefaultTemplate || !existing.templateOrigin) {
      throw new ServiceError({
        code: "ROUTINE_NOT_DEFAULT_TEMPLATE",
        message: "Chỉ mẫu mặc định mới khôi phục được.",
        retryable: false,
      });
    }
    const seed = ROUTINE_TEMPLATE_SEEDS.find((s) => s.origin === existing.templateOrigin);
    if (!seed) {
      throw new ServiceError({ code: "ROUTINE_TEMPLATE_SEED_MISSING", message: "Không tìm thấy mẫu gốc.", retryable: false });
    }
    const needsSetup = needsSetupTu(seed.steps);
    const doi = noiDungDoi({ name: seed.name, steps: seed.steps }, existing);
    const restored: Routine = {
      ...existing,
      name: seed.name,
      icon: seed.icon,
      steps: seed.steps,
      needsPreview: false,
      needsSetup,
      runnable: existing.enabled && !needsSetup,
      // Khớp hợp đồng backend (#370, xác nhận qua API thật): mẫu chưa từng
      // sửa thì khôi phục không đổi gì -> version giữ nguyên.
      version: doi ? existing.version + 1 : existing.version,
      updatedAt: new Date().toISOString(),
    };
    save(
      userId,
      routines.map((r) => (r.id === id ? restored : r)),
    );
    return restored;
  },

  /**
   * Mock KHÔNG mô phỏng vòng đời chạy thật (không có engine thực thi, không
   * emit sự kiện WS từng bước) — trả về ngay một lần chạy đã "hoàn tất", mọi
   * bước `completed`. Panel tiến độ vẫn hiện đúng (chỉ là không có hoạt ảnh
   * từng bước); hành vi thời gian thực chỉ có ý nghĩa khi test/chạy với
   * backend thật (real.ts, đã xác nhận qua API — xem #292).
   */
  async runRoutine(id, sessionId) {
    await delay(MOCK_LATENCY_MS);
    const userId = currentUserId();
    const routine = findOrThrow(load(userId), id);
    if (!routine.enabled) {
      throw new ServiceError({ code: "ROUTINE_DISABLED", message: "Routine đang tắt.", retryable: false });
    }
    if (routine.needsSetup) {
      throw new ServiceError({ code: "ROUTINE_NEEDS_SETUP", message: "Routine thiếu địa điểm.", retryable: false });
    }
    const now = new Date().toISOString();
    const results = routine.steps.map((step, index) => ({
      index,
      action: step.action,
      status: "completed" as const,
      description: step.action,
      errorCode: null,
    }));
    const execution: RoutineExecution = {
      id: `exec_mock_${Date.now()}`,
      routineId: id,
      sessionId,
      routineVersion: routine.version,
      status: "completed",
      currentIndex: routine.steps.length,
      approvalId: null,
      stepsTotal: routine.steps.length,
      results,
      terminalReason: null,
      createdAt: now,
      updatedAt: now,
    };
    return execution;
  },

  /** Mock không lưu execution nào (xem `runRoutine`) — luôn không thấy. */
  async getExecution(executionId) {
    await delay(MOCK_LATENCY_MS);
    throw new ServiceError({
      code: "ROUTINE_EXECUTION_NOT_FOUND",
      message: `Không tìm thấy lần chạy ${executionId}.`,
      retryable: false,
    });
  },

  /** Cùng lý do với `getExecution`: mock trả execution "đã hoàn tất" ngay lập
   * tức ở `runRoutine`, nên không có gì còn "đang chạy" để dừng. */
  async cancelExecution(executionId) {
    await delay(MOCK_LATENCY_MS);
    throw new ServiceError({
      code: "ROUTINE_EXECUTION_NOT_FOUND",
      message: `Không tìm thấy lần chạy ${executionId}.`,
      retryable: false,
    });
  },
};
