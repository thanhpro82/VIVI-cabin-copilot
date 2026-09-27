import { ServiceError } from "../shared/errors";
import type { AuthUser, DriverSession, LoginResult, SessionService } from "./types";

const STORAGE_KEY = "vivi.session";
const DRIVER_SESSION_KEY = "vivi.driver_session";
const MOCK_LATENCY_MS = 500;

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buildResult(user: AuthUser): LoginResult {
  const expiresAt = new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString();
  return {
    accessToken: `mock_token_${user.role}_${Date.now()}`,
    tokenType: "Bearer",
    expiresAt,
    user,
  };
}

function persist(result: LoginResult) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(result));
}

/**
 * Quyền lái + sức chứa pool mà mock trả về (issue #261).
 *
 * Mặc định khớp `VEHICLE_POOL_SIZE=1` của backend: không cấp phát, nên không
 * có trần nào để hiện (`pool: null`) và ai cũng lái được — mock phải giống
 * mặc định của repo, không giống cấu hình demo.
 */
let mockPoolOverride: Pick<DriverSession, "canDrive" | "pool"> = { canDrive: true, pool: null };

/**
 * Dựng ca "hết pool → chỉ xem" mà **không cần backend** — yêu cầu tường minh
 * của issue #261 ("dựng được cả hai ca `can_drive: true` và `false` để test UI").
 *
 * Cùng khuôn với `__setMockSpeedKph` của `turn/mock.ts`: helper để test import,
 * không gắn lên `window`.
 *
 * ```ts
 * __setMockVehiclePool({ canDrive: false, pool: { total: 3, inUse: 3, free: 0 } });
 * __setMockVehiclePool({ canDrive: true, pool: { total: 3, inUse: 2, free: 1 } });
 * __setMockVehiclePool({ canDrive: true, pool: null }); // mặc định repo
 * ```
 *
 * Chỉ có hiệu lực cho phiên TẠO SAU lời gọi này — `canDrive`/`pool` được chốt
 * lúc tạo phiên, đúng như hợp đồng thật (`POST /sessions` là chỗ duy nhất phơi
 * hai trường này), nên phiên đang lưu sẵn không đổi theo.
 */
export function __setMockVehiclePool(next: Pick<DriverSession, "canDrive" | "pool">): void {
  mockPoolOverride = next;
}

export const mockSessionService: SessionService = {
  async loginAsDriver() {
    await delay(MOCK_LATENCY_MS);
    const result = buildResult({
      userId: "usr_driver_demo",
      role: "driver",
      displayName: "Minh",
    });
    persist(result);
    return result;
  },

  async login(email, password) {
    await delay(MOCK_LATENCY_MS);
    if (!email.includes("@") || password.length < 6) {
      throw new ServiceError({
        code: "INPUT_INVALID",
        message: "Email hoặc mật khẩu không hợp lệ.",
        retryable: true,
      });
    }
    const result = buildResult({
      userId: "usr_engineer_demo",
      role: "engineer",
      displayName: email.split("@")[0],
    });
    persist(result);
    return result;
  },

  getStoredSession() {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as LoginResult;
      if (new Date(parsed.expiresAt).getTime() < Date.now()) {
        window.localStorage.removeItem(STORAGE_KEY);
        return null;
      }
      return parsed;
    } catch {
      return null;
    }
  },

  logout() {
    if (typeof window === "undefined") return;
    window.localStorage.removeItem(STORAGE_KEY);
    window.localStorage.removeItem(DRIVER_SESSION_KEY);
  },

  async createDriverSession(vehicleId) {
    await delay(300);
    const session: DriverSession = {
      sessionId: `ses_mock_${Date.now()}`,
      vehicleId,
      status: "active",
      startedAt: new Date().toISOString(),
      ...mockPoolOverride,
    };
    if (typeof window !== "undefined") {
      window.localStorage.setItem(DRIVER_SESSION_KEY, JSON.stringify(session));
    }
    return session;
  },

  getCurrentDriverSession() {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem(DRIVER_SESSION_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as DriverSession;
    } catch {
      return null;
    }
  },
};
