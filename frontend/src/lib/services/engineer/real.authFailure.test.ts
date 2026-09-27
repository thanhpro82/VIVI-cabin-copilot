import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EngineerEvent } from "./types";

/**
 * Nhánh xác thực của `engineer/real.ts` — REST và WebSocket.
 *
 * Vì sao file này tồn tại: màn hình kỹ sư là nơi 403 xảy ra thường xuyên nhất và ít
 * giống "token chết" nhất. `require_engineer` (`src/api/auth_deps.py:82`) từ chối một
 * tài khoản driver đăng nhập hoàn toàn hợp lệ, và `/ws/engineer` đóng 4403 khi sai
 * role **hoặc** khi Origin không nằm trong `cors_origins` (`src/api/ws.py`). Đăng xuất
 * ở cả ba ca đó vừa không sửa được gì, vừa xoá mất thông tin duy nhất có ích — rằng
 * người dùng đang sai vai, hoặc triển khai đang sai cấu hình CORS.
 *
 * Trước PR #157 hai nhánh này không có test nào, nên bản sửa của chính PR đó (gộp
 * 403 vào đường đăng xuất) đi qua CI mà không ai thấy.
 */

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readonly protocols: string[];
  private listeners: Record<string, ((ev: { data?: string; code?: number }) => void)[]> = {};

  constructor(url: string, protocols: string[]) {
    this.url = url;
    this.protocols = protocols;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, cb: (ev: { data?: string; code?: number }) => void) {
    (this.listeners[type] ??= []).push(cb);
  }

  send() {}

  close() {
    this.emitClose();
  }

  emitOpen() {
    for (const cb of this.listeners.open ?? []) cb({});
  }

  emitClose(code?: number) {
    for (const cb of this.listeners.close ?? []) cb({ code });
  }
}

const STORED_SESSION = {
  accessToken: "tok-eng",
  tokenType: "Bearer",
  expiresAt: "2099-01-01T00:00:00Z",
  user: { userId: "usr_engineer_01", role: "engineer" as const, displayName: "Demo Engineer" },
};

vi.mock("../session", () => ({
  sessionService: {
    getStoredSession: vi.fn(() => STORED_SESSION),
  },
}));

// Giữ `isAuthFailureCode` thật — nó chỉ so mã lỗi, và chính nó là thứ đang được chốt.
const reportAuthFailure = vi.fn();
vi.mock("../shared/authFailure", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../shared/authFailure")>()),
  reportAuthFailure: (message: string) => reportAuthFailure(message),
}));

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

async function freshRealEngineerService() {
  vi.resetModules();
  const mod = await import("./real");
  return mod.realEngineerService;
}

describe("engineer/real.ts — lỗi xác thực", () => {
  beforeEach(() => {
    reportAuthFailure.mockClear();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("401 ở /metrics/summary báo hết phiên — token chết thì đúng là phải đăng nhập lại", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(401, {
          error: { code: "AUTH_REQUIRED", message: "token đã hết hạn, vui lòng đăng nhập lại", retryable: false },
        }),
      ),
    );
    const service = await freshRealEngineerService();

    await expect(service.getMetricsSummary()).rejects.toThrow("token đã hết hạn, vui lòng đăng nhập lại");
    expect(reportAuthFailure).toHaveBeenCalledWith("token đã hết hạn, vui lòng đăng nhập lại");
  });

  it("403 ở /metrics/summary KHÔNG đăng xuất — sai vai, không phải hết phiên", async () => {
    // Một tài khoản driver mở `/engineer`: token hợp lệ, phiên tốt, chỉ là không đủ
    // quyền. Đá họ về `/login` sẽ khiến họ đăng nhập lại bằng đúng tài khoản đó và
    // gặp lại đúng lỗi ấy, mãi mãi.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(403, { error: { code: "FORBIDDEN", message: "yêu cầu vai trò 'engineer'", retryable: false } }),
      ),
    );
    const service = await freshRealEngineerService();

    await expect(service.getMetricsSummary()).rejects.toThrow("yêu cầu vai trò 'engineer'");
    expect(reportAuthFailure).not.toHaveBeenCalled();
  });

  it("close 4401 báo hết phiên", async () => {
    const service = await freshRealEngineerService();
    service.subscribe(() => {});

    FakeWebSocket.instances[0].emitOpen();
    FakeWebSocket.instances[0].emitClose(4401);

    expect(reportAuthFailure).toHaveBeenCalled();
  });

  it("close 4403 KHÔNG đăng xuất mà phát event error để banner nêu lý do", async () => {
    // Socket kỹ sư không tự reconnect, nên nếu im lặng thì màn hình chỉ đơn giản
    // ngừng cập nhật — đúng ca `EngineerShellProvider` từng nuốt bằng `default: break`.
    const service = await freshRealEngineerService();
    const events: EngineerEvent[] = [];
    service.subscribe((e) => events.push(e));

    FakeWebSocket.instances[0].emitOpen();
    FakeWebSocket.instances[0].emitClose(4403);

    expect(reportAuthFailure).not.toHaveBeenCalled();
    expect(events.at(-1)).toEqual({
      type: "error",
      code: "FORBIDDEN",
      message: "Không đủ quyền kết nối (vai trò hoặc Origin không hợp lệ).",
    });
  });
});
