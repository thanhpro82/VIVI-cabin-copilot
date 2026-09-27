import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ServiceError } from "../shared/errors";
import { SIM_HARNESS_ABSENT_CODE } from "./types";

/**
 * `setSimSpeed` — kênh harness `v1/sim` (issue #183, ADR-024).
 *
 * Bốn thứ đáng khoá lại ở đây, và cả bốn đều là chỗ hợp đồng của route này
 * **khác** phần còn lại của `turn/real.ts`, nên rất dễ bị "sửa cho giống anh em"
 * mà hỏng:
 *
 * 1. Thân trả về là JSON **thô**, không bọc `{data:...}` — route nằm ngoài bảng
 *    14 interface P0.
 * 2. 404 phải ra `SIM_HARNESS_ABSENT_CODE` **cả khi** backend trả 404 mặc định
 *    của FastAPI (không có `error.code`) — đó là ca backend chưa có PR #206.
 * 3. Không gửi `session_id`, không `Idempotency-Key`, không `X-Schema-Version`:
 *    route không đọc cái nào, và không có nhánh tạo lại session.
 * 4. Bỏ trống `gear` thì **không có khoá `gear`** trong body, chứ không phải
 *    `gear: null`.
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

function bodyOf(fetchMock: { mock: { calls: unknown[][] } }): Record<string, unknown> {
  const init = fetchMock.mock.calls.at(-1)?.[1] as RequestInit;
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

describe("turn/real.ts — setSimSpeed", () => {
  beforeEach(() => {
    reportAuthFailure.mockClear();
    createDriverSession.mockClear();
    getStoredSession.mockReturnValue(STORED_SESSION);
    getCurrentDriverSession.mockReturnValue(DRIVER_SESSION);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POST /sim/motion với body snake_case và bearer token", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(202, { accepted: true, speed_kph: 45.0, gear: "D" }));
    vi.stubGlobal("fetch", fetchMock);
    const service = await freshRealTurnService();

    const result = await service.setSimSpeed(45, "D");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/sim/motion");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-abc");
    expect(bodyOf(fetchMock)).toEqual({ speed_kph: 45, gear: "D" });
    // Thô, không envelope. Đọc `body.data.*` ở đây sẽ ra undefined lặng lẽ.
    expect(result).toEqual({ accepted: true, speedKph: 45, gear: "D" });
  });

  it("bỏ trống gear thì KHÔNG gửi khoá gear (để xe ảo tự chọn D/P)", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(202, { accepted: true, speed_kph: 0, gear: null }));
    vi.stubGlobal("fetch", fetchMock);
    const service = await freshRealTurnService();

    const result = await service.setSimSpeed(0);

    const body = bodyOf(fetchMock);
    expect(body).toEqual({ speed_kph: 0 });
    expect("gear" in body).toBe(false);
    // `gear: null` là "tôi không nói gì về số", KHÔNG phải "số hiện tại là null".
    expect(result.gear).toBeNull();
  });

  it("không gửi Idempotency-Key/X-Schema-Version và không kèm session_id", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(202, { accepted: true, speed_kph: 10, gear: null }));
    vi.stubGlobal("fetch", fetchMock);
    const service = await freshRealTurnService();

    await service.setSimSpeed(10);

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBeUndefined();
    expect(headers["X-Schema-Version"]).toBeUndefined();
    expect(bodyOf(fetchMock)).not.toHaveProperty("session_id");
  });

  it("404 có envelope (cờ SIM_CONTROL_ENABLED tắt) → NOT_FOUND, không phải lỗi xác thực", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(404, { error: { code: "NOT_FOUND", message: "Not Found", retryable: false } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const service = await freshRealTurnService();

    await expect(service.setSimSpeed(45)).rejects.toMatchObject({ code: SIM_HARNESS_ABSENT_CODE });
    expect(reportAuthFailure).not.toHaveBeenCalled();
  });

  it("404 mặc định của FastAPI (backend chưa có route) → cùng một mã NOT_FOUND", async () => {
    // Ca này là hiện trạng của `develop` trước khi PR #206 merge: route không
    // tồn tại nên không có envelope `{error:{...}}` nào để đọc. UI phải rơi vào
    // đúng nhánh "không có tính năng", không được hiện toast lỗi lạ.
    const fetchMock = vi.fn(async () => jsonResponse(404, { detail: "Not Found" }));
    vi.stubGlobal("fetch", fetchMock);
    const service = await freshRealTurnService();

    await expect(service.setSimSpeed(45)).rejects.toMatchObject({ code: SIM_HARNESS_ABSENT_CODE });
  });

  it("503 MQTT_UNAVAILABLE nổi lên nguyên mã và giữ retryable", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(503, {
        error: {
          code: "MQTT_UNAVAILABLE",
          message: "chưa nối được broker MQTT — không gửi được lệnh tới xe ảo",
          retryable: true,
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const service = await freshRealTurnService();

    const error = await service.setSimSpeed(45).catch((e: unknown) => e);

    // Không dùng `toBeInstanceOf(ServiceError)`: `vi.resetModules()` khiến
    // `real.ts` nạp một bản `shared/errors` KHÁC với bản file test import, nên
    // hai lớp `ServiceError` không cùng identity dù cùng mã nguồn. Kiểm theo
    // `name` là thứ thật sự đi qua được ranh giới module đó.
    expect((error as ServiceError).name).toBe("ServiceError");
    expect((error as ServiceError).code).toBe("MQTT_UNAVAILABLE");
    expect((error as ServiceError).retryable).toBe(true);
  });

  it("403 KHÔNG kéo theo tạo session mới — route harness không gắn session nào", async () => {
    // `withFreshSession` chỉ bọc `/turns/*`. Nếu ai đó bọc nhầm route này, một
    // lần 403 vì sai role sẽ vứt luôn session hội thoại đang chạy để đổi lấy
    // đúng cái 403 đó lần thứ hai.
    const fetchMock = vi.fn(async () =>
      jsonResponse(403, { error: { code: "FORBIDDEN", message: "không đủ quyền", retryable: false } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const service = await freshRealTurnService();

    await expect(service.setSimSpeed(45)).rejects.toMatchObject({ code: "FORBIDDEN" });
    expect(createDriverSession).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("chưa đăng nhập thì ném AUTH_REQUIRED trước khi chạm mạng", async () => {
    getStoredSession.mockReturnValue(null);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const service = await freshRealTurnService();

    await expect(service.setSimSpeed(45)).rejects.toMatchObject({ code: "AUTH_REQUIRED" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
