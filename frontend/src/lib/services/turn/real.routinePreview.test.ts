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

const VALID_PREVIEW = {
  routine_id: "rtn_ve_nha",
  routine_name: "Về nhà",
  steps: [
    { index: 0, action: "navigation", description: "dẫn đường tới Nhà" },
    { index: 1, action: "hvac_power", description: "bật điều hòa" },
  ],
};

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Routine preview boundary mapping", () => {
  it("map assistant.response từ snake_case sang TurnResult", async () => {
    const { mapServerEvent } = await import("./real");

    const event = mapServerEvent({
      type: "assistant.response",
      turn_id: "turn_1",
      payload: {
        display_text: "Xem trước",
        speak_text: "Xem trước",
        routine_preview: VALID_PREVIEW,
      },
    });

    expect(event?.type === "assistant.response" ? event.result.routinePreview : null).toEqual({
      routineId: "rtn_ve_nha",
      routineName: "Về nhà",
      steps: [
        { index: 0, action: "navigation", description: "dẫn đường tới Nhà" },
        { index: 1, action: "hvac_power", description: "bật điều hòa" },
      ],
    });
  });

  it("payload malformed bị bỏ và ghi cảnh báo contract", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const { mapServerEvent } = await import("./real");

    const event = mapServerEvent({
      type: "assistant.response",
      turn_id: "turn_bad",
      payload: {
        display_text: "Xem trước",
        speak_text: "Xem trước",
        routine_preview: { routine_id: "rtn_1", routine_name: "Về nhà", steps: "bad" },
      },
    });

    expect(event?.type === "assistant.response" ? event.result.routinePreview : undefined).toBeNull();
    expect(warn).toHaveBeenCalledOnce();
  });

  it("sendText map cùng contract từ TextTurnData.routine_preview", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          data: {
            turn_id: "turn_rest",
            routine_preview: VALID_PREVIEW,
          },
        }),
      ),
    );
    const { realTurnService } = await import("./real");

    await expect(realTurnService.sendText("Xem trước Routine Về nhà")).resolves.toEqual({
      turnId: "turn_rest",
      routinePreview: {
        routineId: "rtn_ve_nha",
        routineName: "Về nhà",
        steps: [
          { index: 0, action: "navigation", description: "dẫn đường tới Nhà" },
          { index: 1, action: "hvac_power", description: "bật điều hòa" },
        ],
      },
    });
  });
});
