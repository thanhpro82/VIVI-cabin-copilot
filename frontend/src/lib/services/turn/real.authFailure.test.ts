import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Nhánh 401/403 của các lời gọi REST trong `turn/real.ts`.
 *
 * Vì sao đáng một file riêng: đây là đường mà bug "token không hợp lệ hoặc đã
 * hết hạn" đi qua nhiều nhất trong thực tế — poll `GET /vehicle/state` mỗi 2
 * giây ở real mode, và call site của nó (`DriverShellProvider.refreshVehicleState`)
 * cố ý nuốt mọi lỗi. Nếu service không báo ra ngoài thì 401 lặp vô hạn trong im
 * lặng tuyệt đối, đúng như hiện trạng trước bản sửa này.
 */

const STORED_SESSION = {
  accessToken: "tok-abc",
  tokenType: "Bearer",
  expiresAt: "2099-01-01T00:00:00Z",
  user: { userId: "usr_driver_01", role: "driver" as const, displayName: "Demo Driver" },
};

const DRIVER_SESSION = {
  sessionId: "ses_test_1",
  vehicleId: "vehicle-demo-01",
  status: "active",
  startedAt: "2026-01-01T00:00:00Z",
};

const getStoredSession = vi.fn<() => typeof STORED_SESSION | null>(() => STORED_SESSION);
const getCurrentDriverSession = vi.fn<() => typeof DRIVER_SESSION | null>(() => DRIVER_SESSION);
const createDriverSession = vi.fn(async (_vehicleId: string) => DRIVER_SESSION);

vi.mock("../session", () => ({
  sessionService: {
    getStoredSession: () => getStoredSession(),
    getCurrentDriverSession: () => getCurrentDriverSession(),
    createDriverSession: (vehicleId: string) => createDriverSession(vehicleId),
  },
}));

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

async function freshRealTurnService() {
  vi.resetModules();
  const mod = await import("./real");
  return mod.realTurnService;
}

describe("turn/real.ts — lỗi xác thực ở tầng REST", () => {
  beforeEach(() => {
    reportAuthFailure.mockClear();
    createDriverSession.mockClear();
    getStoredSession.mockReturnValue(STORED_SESSION);
    getCurrentDriverSession.mockReturnValue(DRIVER_SESSION);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("401 từ GET /vehicle/state báo hết phiên kèm nguyên văn thông điệp của backend", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(401, {
          error: { code: "AUTH_REQUIRED", message: "token đã hết hạn, vui lòng đăng nhập lại", retryable: false },
        }),
      ),
    );
    const service = await freshRealTurnService();

    await expect(service.getVehicleState()).rejects.toThrow("token đã hết hạn, vui lòng đăng nhập lại");
    expect(reportAuthFailure).toHaveBeenCalledWith("token đã hết hạn, vui lòng đăng nhập lại");
  });

  it("403 KHÔNG đăng xuất — token vẫn sống, chỉ tài nguyên vừa xin bị từ chối", async () => {
    // Ca sai vai: `require_driver` (`src/api/auth_deps.py:58`). Session mới không sửa
    // được gì nên `withFreshSession` thử lại đúng một lần rồi để lỗi nổi lên, còn
    // phiên đăng nhập thì giữ nguyên (PM/PO review PR #157).
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(403, { error: { code: "FORBIDDEN", message: "yêu cầu vai trò 'driver'", retryable: false } }),
      ),
    );
    const service = await freshRealTurnService();

    await expect(service.sendText("bật điều hoà")).rejects.toThrow("yêu cầu vai trò 'driver'");
    expect(reportAuthFailure).not.toHaveBeenCalled();
  });

  it("403 vì session hết hạn: tạo session mới rồi gửi lại, không đá về /login", async () => {
    // Session hết hạn KHÔNG trả 401 — `src/api/session_state.py:155-180` trả `None`
    // và call site dịch thành 403 FORBIDDEN, cố ý gộp với "của người khác" để không
    // rò enumeration (review PR #89). Đây là ca mà bỏ 403 khỏi nhánh đăng xuất sẽ
    // để tài xế kẹt nếu không có đường phục hồi.
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(403, {
          error: { code: "FORBIDDEN", message: "session không tồn tại hoặc không thuộc về bạn", retryable: false },
        }),
      )
      .mockResolvedValueOnce(jsonResponse(202, { data: { turn_id: "turn_2" } }));
    vi.stubGlobal("fetch", fetchMock);
    const service = await freshRealTurnService();

    await expect(service.sendText("bật điều hoà")).resolves.toEqual({ turnId: "turn_2" });
    expect(createDriverSession).toHaveBeenCalledWith("vehicle-demo-01");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(reportAuthFailure).not.toHaveBeenCalled();
  });

  it("chỉ thử lại ĐÚNG một lần — 403 lần hai đi thẳng ra ngoài, không vòng lại", async () => {
    // Không có chốt này thì một session chết mà `POST /sessions` vẫn 200 sẽ thành
    // vòng lặp tạo-session-rồi-403 vô hạn, tệ hơn hẳn bug ban đầu.
    const fetchMock = vi.fn(async () =>
      jsonResponse(403, {
        error: { code: "FORBIDDEN", message: "session không tồn tại hoặc không thuộc về bạn", retryable: false },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const service = await freshRealTurnService();

    await expect(service.sendText("bật điều hoà")).rejects.toThrow("session không tồn tại");
    expect(createDriverSession).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(reportAuthFailure).not.toHaveBeenCalled();
  });

  it("403 ở /citations KHÔNG tạo lại session — citation của phiên cũ mồ côi, thử lại vô nghĩa", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(403, { error: { code: "FORBIDDEN", message: "citation của phiên khác", retryable: false } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const service = await freshRealTurnService();

    await expect(service.getCitation("cit_1")).rejects.toThrow("citation của phiên khác");
    expect(createDriverSession).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(reportAuthFailure).not.toHaveBeenCalled();
  });

  it("lỗi KHÔNG phải xác thực thì không đá người dùng ra ngoài", async () => {
    // 503 MQTT_UNAVAILABLE là lỗi hạ tầng của một lượt, phiên vẫn tốt — đăng
    // xuất ở đây sẽ biến một sự cố tạm thời thành mất luôn màn hình.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(503, { error: { code: "MQTT_UNAVAILABLE", message: "chưa nối broker", retryable: true } }),
      ),
    );
    const service = await freshRealTurnService();

    await expect(service.getVehicleState()).rejects.toThrow("chưa nối broker");
    expect(reportAuthFailure).not.toHaveBeenCalled();
  });

  it("session đã bị xoá khỏi localStorage (hết hạn theo đồng hồ client) cũng báo, không chỉ throw", async () => {
    getStoredSession.mockReturnValue(null);
    vi.stubGlobal("fetch", vi.fn());
    const service = await freshRealTurnService();

    await expect(service.getVehicleState()).rejects.toThrow("Chưa đăng nhập.");
    expect(reportAuthFailure).toHaveBeenCalled();
  });
});
