import { reportAuthFailure } from "../shared/authFailure";
import { ServiceError } from "../shared/errors";
import type { AuthUser, DriverSession, LoginResult, SessionService } from "./types";

const STORAGE_KEY = "vivi.session";
const DRIVER_SESSION_KEY = "vivi.driver_session";
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface SessionApiResponse {
  data: {
    session_id: string;
    vehicle_id: string;
    status: string;
    started_at: string;
    // Thêm 2026-08-23 cùng pool xe ảo (PR #259). Additive: `can_drive` mặc
    // định true, `pool` mặc định null khi backend cũ/pool chưa bật.
    can_drive?: boolean;
    pool?: { total: number; in_use: number; free: number } | null;
  };
}

interface LoginApiResponse {
  data: {
    access_token: string;
    token_type: string;
    expires_at: string;
    user: { user_id: string; role: "driver" | "engineer"; display_name: string };
  };
}

interface ApiErrorBody {
  error?: { code?: string; message?: string; retryable?: boolean };
}

function persist(result: LoginResult) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(result));
}

function readStoredSession(): LoginResult | null {
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
}

async function parseLoginResponse(res: Response): Promise<LoginResult> {
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
    throw new ServiceError({
      code: body?.error?.code ?? "AUTH_REQUIRED",
      message: body?.error?.message ?? "Đăng nhập thất bại.",
      retryable: body?.error?.retryable ?? false,
    });
  }

  const body = (await res.json()) as LoginApiResponse;
  const user: AuthUser = {
    userId: body.data.user.user_id,
    role: body.data.user.role,
    displayName: body.data.user.display_name,
  };
  const result: LoginResult = {
    accessToken: body.data.access_token,
    tokenType: body.data.token_type,
    expiresAt: body.data.expires_at,
    user,
  };
  persist(result);
  return result;
}

async function callLogin(email: string, password: string): Promise<LoginResult> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json; charset=utf-8; version=1.0",
    },
    body: JSON.stringify({ email, password }),
  });
  return parseLoginResponse(res);
}

export const realSessionService: SessionService = {
  async loginAsDriver() {
    // Credential demo KHÔNG bao giờ đọc ở client — DEMO_DRIVER_EMAIL/_PASSWORD
    // (server-only, không có prefix NEXT_PUBLIC_) chỉ tồn tại trong Route
    // Handler `/api/auth/demo-driver`, tránh bị bundle vào JS gửi cho trình
    // duyệt. Xem ARCHITECTURE.md mục 3.1.
    const res = await fetch("/api/auth/demo-driver", { method: "POST" });
    return parseLoginResponse(res);
  },

  async login(email, password) {
    return callLogin(email, password);
  },

  getStoredSession() {
    return readStoredSession();
  },

  logout() {
    if (typeof window === "undefined") return;
    window.localStorage.removeItem(STORAGE_KEY);
    window.localStorage.removeItem(DRIVER_SESSION_KEY);
  },

  async createDriverSession(vehicleId) {
    const stored = readStoredSession();
    if (!stored) {
      reportAuthFailure("Phiên đăng nhập đã hết hạn.");
      throw new ServiceError({
        code: "AUTH_REQUIRED",
        message: "Chưa đăng nhập, không thể tạo session.",
        retryable: false,
      });
    }

    const res = await fetch(`${API_BASE}/sessions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${stored.accessToken}`,
        "X-Schema-Version": "1.0",
        "Idempotency-Key": `session:${vehicleId}:${Date.now()}`,
        "Content-Type": "application/json; charset=utf-8",
      },
      body: JSON.stringify({ vehicle_id: vehicleId, input_mode: "voice" }),
    });

    if (!res.ok) {
      const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
      const message = body?.error?.message ?? "Không tạo được session.";
      // Chỉ ở đây, KHÔNG ở `parseLoginResponse` — 401 lúc đăng nhập nghĩa là sai
      // mật khẩu, và người dùng đang đứng sẵn ở /login; đá họ về đó lần nữa chỉ
      // xoá mất thông báo của chính màn hình đăng nhập.
      //
      // Và chỉ 401. `POST /sessions` trả 403 khi tài khoản không phải vai trò driver
      // (`require_driver`, `src/api/auth_deps.py:58`) — token vẫn hợp lệ, đăng xuất
      // không sửa được gì. Đáng nói hơn: `withFreshSession` ở `turn/real.ts` gọi
      // chính hàm này để phục hồi sau 403, nên một `reportAuthFailure` ở đây sẽ đá
      // người dùng về `/login` giữa chừng đúng lúc đang tự chữa.
      if (res.status === 401) reportAuthFailure(message);
      throw new ServiceError({
        code: body?.error?.code ?? "REQUEST_CONTEXT_INVALID",
        message,
        retryable: body?.error?.retryable ?? false,
      });
    }

    const body = (await res.json()) as SessionApiResponse;
    const session: DriverSession = {
      sessionId: body.data.session_id,
      vehicleId: body.data.vehicle_id,
      status: body.data.status,
      startedAt: body.data.started_at,
      canDrive: body.data.can_drive ?? true,
      pool: body.data.pool
        ? { total: body.data.pool.total, inUse: body.data.pool.in_use, free: body.data.pool.free }
        : null,
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
