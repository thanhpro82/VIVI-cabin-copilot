// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent, VehicleState } from "@/lib/services/turn/types";
import { LOCKED_UI_POLICY, OPEN_UI_POLICY } from "@/lib/services/turn/types";
import { DriverShellProvider, useDriverShell } from "./DriverShellProvider";

/**
 * Fail-closed khi mất WS/backend (issue #241, UAT-007/UAT-008).
 *
 * `send()`/voice chỉ được gọi `turnService.sendText()`/`sendVoice()` khi đã
 * **xác nhận** kênh sự kiện còn sống — tức đã nhận `ui.policy` hợp lệ đầu tiên
 * (`connectionState === "online"`, xem docstring ConnectionState).
 *
 * Hai ca hỏng khác nhau, và ca thứ hai mới là thứ PM/PO bắt bổ sung ở review PR
 * #246:
 *
 * 1. **Mất kết nối giữa chừng** — đã online rồi socket đóng, real.ts phát
 *    `LOCKED_UI_POLICY`.
 * 2. **Cold-start offline** — mở app khi backend đã chết sẵn, nên KHÔNG có
 *    `ui.policy` nào cả. Bản đầu của PR coi ca này là "cho gửi" (cờ
 *    `hasReceivedUiPolicyRef`) nên `POST /turns/text` vẫn bay ra network và ăn
 *    `ERR_CONNECTION_REFUSED` — trái UAT-008.
 */

vi.mock("@/lib/audio/wavRecorder", () => ({ startWavRecording: vi.fn() }));
vi.mock("@/lib/services/session", () => ({
  sessionService: {
    getCurrentDriverSession: vi.fn(),
    createDriverSession: vi.fn(),
    getStoredSession: vi.fn(),
    logout: vi.fn(),
  },
}));
vi.mock("@/lib/services/turn", () => ({
  turnService: {
    getVehicleState: vi.fn(),
    sendText: vi.fn(),
    sendVoice: vi.fn(),
    decideApproval: vi.fn(),
    getCitation: vi.fn(),
    subscribe: vi.fn(),
  },
}));

const { startWavRecording } = await import("@/lib/audio/wavRecorder");
const { sessionService } = await import("@/lib/services/session");
const { turnService } = await import("@/lib/services/turn");

const DRIVER_SESSION = {
  sessionId: "ses_test_1",
  vehicleId: "vehicle-demo-01",
  status: "active" as const,
  startedAt: "2026-01-01T00:00:00Z",
  canDrive: true,
  pool: null,
};

const VEHICLE_STATE: VehicleState = {
  vehicleId: "vehicle-demo-01",
  stateVersion: 1,
  observedAt: "2026-01-01T00:00:00Z",
  motion: { speedKph: 0, gear: "P", ignition: "ON" },
  hvac: { power: false, temperatureC: 24, fanLevel: 0 },
  windows: { frontLeft: 0, frontRight: 0, rearLeft: 0, rearRight: 0 },
  doors: { frontLeft: "closed", frontRight: "closed", rearLeft: "closed", rearRight: "closed" },
  media: { status: "stopped", volume: 30, track: null },
  navigation: { status: "idle", destinationId: null },
  seat: {
    frontLeft: { heating: 0, foreAft: 50, recline: 50, height: 50 },
    frontRight: { heating: 0, foreAft: 50, recline: 50, height: 50 },
  },
  lights: { headlight: "auto", interior: false },
  trunk: { position: "closed" },
};

function TestConsumer() {
  const { send, toast, openVoice, stopVoice, connectionState } = useDriverShell();
  return (
    <div>
      <span data-testid="connection">{connectionState}</span>
      <button type="button" onClick={() => send("bật điều hòa")} data-testid="send">
        send
      </button>
      <button type="button" onClick={openVoice} data-testid="open-voice">
        open
      </button>
      <button type="button" onClick={stopVoice} data-testid="stop-voice">
        stop
      </button>
      <span data-testid="toast">{toast ?? ""}</span>
    </div>
  );
}

describe("DriverShellProvider — fail-closed khi mất kết nối (issue #241)", () => {
  let emit: (event: DriverEvent) => void = () => {};

  beforeEach(() => {
    emit = () => {};
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.sendText).mockResolvedValue({ turnId: "t1" });
    vi.mocked(turnService.sendVoice).mockResolvedValue({ turnId: "t1" });
    vi.mocked(startWavRecording).mockResolvedValue({
      stop: vi.fn().mockResolvedValue(new Blob()),
      cancel: vi.fn(),
      hadSpeech: () => true,
    });
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      return () => {};
    });
  });

  afterEach(() => {
    cleanup();
    vi.resetAllMocks();
  });

  it("UAT-008: sau khi nhận policy MỞ rồi mất kết nối (LOCKED_UI_POLICY) — send() KHÔNG gọi sendText(), báo toast", async () => {
    render(
      <DriverShellProvider>
        <TestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // Kết nối thật sự đã sống — server gửi policy MỞ trước.
    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));

    // Rớt kết nối — real.ts phát LOCKED_UI_POLICY qua đúng path "ui.policy".
    act(() => emit({ type: "ui.policy", uiPolicy: LOCKED_UI_POLICY }));

    act(() => screen.getByTestId("send").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(turnService.sendText).not.toHaveBeenCalled();
    expect(screen.getByTestId("toast").textContent).toMatch(/mất kết nối/i);
  });

  it("kết nối vẫn khoẻ (policy MỞ) thì send() vẫn gọi sendText() bình thường", async () => {
    render(
      <DriverShellProvider>
        <TestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));

    act(() => screen.getByTestId("send").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(turnService.sendText).toHaveBeenCalledWith("bật điều hòa");
  });

  it("UAT-008 (voice): mất kết nối lúc đang ghi — dừng ghi KHÔNG gọi sendVoice(), huỷ recorder, đóng overlay", async () => {
    render(
      <DriverShellProvider>
        <TestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));

    act(() => screen.getByTestId("open-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // Mất kết nối NGAY TRONG lúc đang ghi.
    act(() => emit({ type: "ui.policy", uiPolicy: LOCKED_UI_POLICY }));

    act(() => screen.getByTestId("stop-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(turnService.sendVoice).not.toHaveBeenCalled();
    expect(screen.getByTestId("toast").textContent).toMatch(/mất kết nối/i);
  });

  it("UAT-008 (cold start): có session sẵn nhưng WS không kết nối/không có ui.policy — send() KHÔNG gọi sendText()", async () => {
    // Backend chết ngay từ lúc mở app: `subscribe()` được gọi (session đã có
    // trong localStorage từ lần trước) nhưng không sự kiện nào tới cả — không
    // `ui.policy` mở, cũng không LOCKED_UI_POLICY, vì socket còn chưa mở nổi.
    // Đây là ca PM/PO bắt bổ sung ở review PR #246, và trước đó nó GỬI THẬT.
    render(
      <DriverShellProvider>
        <TestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByTestId("connection").textContent).toBe("connecting");

    act(() => screen.getByTestId("send").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(turnService.sendText).not.toHaveBeenCalled();
    expect(screen.getByTestId("toast").textContent).toMatch(/đang kết nối/i);
  });

  it("UAT-008 (cold start, voice): chưa có ui.policy — không mở mic, không gọi sendVoice()", async () => {
    render(
      <DriverShellProvider>
        <TestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => screen.getByTestId("open-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    // Chặn ngay ở cửa: không xin quyền mic, nên cũng không có gì để dừng/gửi.
    expect(startWavRecording).not.toHaveBeenCalled();

    act(() => screen.getByTestId("stop-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(turnService.sendVoice).not.toHaveBeenCalled();
    expect(screen.getByTestId("toast").textContent).toMatch(/đang kết nối/i);
  });

  it("chỉ MỞ sau ui.policy hợp lệ đầu tiên: cùng một lượt bấm, trước thì chặn, sau thì gửi", async () => {
    render(
      <DriverShellProvider>
        <TestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => screen.getByTestId("send").click());
    await act(async () => {
      await Promise.resolve();
    });
    expect(turnService.sendText).not.toHaveBeenCalled();

    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));
    expect(screen.getByTestId("connection").textContent).toBe("online");

    act(() => screen.getByTestId("send").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(turnService.sendText).toHaveBeenCalledWith("bật điều hòa");
  });
});
