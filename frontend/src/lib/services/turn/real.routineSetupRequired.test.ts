import { afterEach, describe, expect, it, vi } from "vitest";

const STORED_SESSION = {
  accessToken: "tok-abc",
  tokenType: "Bearer",
  expiresAt: "2099-01-01T00:00:00Z",
  user: { userId: "usr_driver_01", role: "driver" as const, displayName: "Demo Driver" },
};

vi.mock("../session", () => ({
  sessionService: {
    getStoredSession: () => STORED_SESSION,
    getCurrentDriverSession: () => ({ sessionId: "ses_1", vehicleId: "vehicle-demo-01" }),
    createDriverSession: vi.fn(),
  },
}));

const VALID_SETUP_REQUIRED = {
  routine_id: "rtn_di_lam",
  ma_loi: "chua_dat_dia_diem",
  thieu: ["office"],
};

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Routine setup-required boundary mapping (#385)", () => {
  it("map assistant.response từ snake_case sang TurnResult", async () => {
    const { mapServerEvent } = await import("./real");

    const event = mapServerEvent({
      type: "assistant.response",
      turn_id: "turn_1",
      payload: {
        display_text: "Chưa đặt địa điểm Cơ quan nên chưa chạy được Routine này.",
        speak_text: "Chưa đặt địa điểm Cơ quan nên chưa chạy được Routine này.",
        routine_setup_required: VALID_SETUP_REQUIRED,
      },
    });

    expect(event?.type === "assistant.response" ? event.result.routineSetupRequired : null).toEqual({
      routineId: "rtn_di_lam",
      maLoi: "chua_dat_dia_diem",
      thieu: ["office"],
    });
  });

  it("vắng field thì map ra null, không phải throw", async () => {
    const { mapServerEvent } = await import("./real");

    const event = mapServerEvent({
      type: "assistant.response",
      turn_id: "turn_1",
      payload: { display_text: "Đang chạy Routine cho bạn.", speak_text: "Đang chạy Routine cho bạn." },
    });

    expect(event?.type === "assistant.response" ? event.result.routineSetupRequired : undefined).toBeNull();
  });

  it("payload malformed (thieu không phải mảng chuỗi) bị bỏ và ghi cảnh báo contract", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const { mapServerEvent } = await import("./real");

    const event = mapServerEvent({
      type: "assistant.response",
      turn_id: "turn_bad",
      payload: {
        display_text: "x",
        speak_text: "x",
        routine_setup_required: { routine_id: "rtn_1", ma_loi: "chua_dat_dia_diem", thieu: "office" },
      },
    });

    expect(event?.type === "assistant.response" ? event.result.routineSetupRequired : undefined).toBeNull();
    expect(warn).toHaveBeenCalledOnce();
  });

  it("sendText map cùng contract từ TextTurnData.routine_setup_required", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          data: {
            turn_id: "turn_rest",
            routine_setup_required: VALID_SETUP_REQUIRED,
          },
        }),
      ),
    );
    const { realTurnService } = await import("./real");

    await expect(realTurnService.sendText("Chạy Routine Đi làm")).resolves.toEqual({
      turnId: "turn_rest",
      routineSetupRequired: {
        routineId: "rtn_di_lam",
        maLoi: "chua_dat_dia_diem",
        thieu: ["office"],
      },
    });
  });

  it("sendText không có field thì không có routineSetupRequired trong kết quả", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ data: { turn_id: "turn_rest_2" } })));
    const { realTurnService } = await import("./real");

    await expect(realTurnService.sendText("Bật điều hòa")).resolves.toEqual({ turnId: "turn_rest_2" });
  });
});
