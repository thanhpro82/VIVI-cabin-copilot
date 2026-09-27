// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { VehicleState } from "@/lib/services/turn/types";
import { OPEN_UI_POLICY } from "@/lib/services/turn/types";
import { DriverShellProvider, useDriverShell } from "./DriverShellProvider";
import { VoiceOverlay } from "./VoiceOverlay";

/** Thay cho nút mic ở HomeView — VoiceOverlay tự nó không mở được. */
function OverlayOpener() {
  const { openVoice } = useDriverShell();
  return <button type="button" data-testid="open" onClick={openVoice} />;
}

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

/**
 * Issue #342: 5 vạch sóng lúc đang nghe từng chạy bằng CSS keyframes cố định,
 * nhảy y hệt nhau dù có tiếng nói hay không. Giờ `VoiceOverlay` đăng ký nhận
 * mức mic thật qua `subscribeMicLevel` (DriverShellProvider) và ghi thẳng vào
 * CSS custom property `--mic-level` trên container — test này khoá đúng cái
 * dây nối đó, không phải khoá con số RMS (đã có test riêng ở
 * WakeWordController.test.ts/wavRecorder.test.ts).
 */
describe("VoiceOverlay — vạch sóng đọc mức mic thật qua subscribeMicLevel (issue #342)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue({
      sessionId: "ses_1",
      vehicleId: "vehicle-demo-01",
      status: "active",
      startedAt: "2026-01-01T00:00:00Z",
      canDrive: true,
      pool: null,
    });
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(startWavRecording).mockResolvedValue({
      stop: vi.fn().mockResolvedValue(new Blob()),
      cancel: vi.fn(),
      hadSpeech: () => true,
    });
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      // Xem docstring tương đương ở VoiceOverlay.nghetiep.test.tsx: phải phát
      // ui.policy ngay, không thì Provider ở trạng thái "connecting" và chặn
      // gửi lệnh.
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.resetAllMocks();
  });

  /** Mở overlay bằng đường thật rồi trả về container vạch sóng đang gắn `ref`. */
  async function moOverlayDangGhi(): Promise<HTMLElement> {
    render(
      <DriverShellProvider>
        <OverlayOpener />
        <VoiceOverlay />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() => screen.getByTestId("open").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    return screen.getByTestId("voice-wave-bars");
  }

  it("mức mic thật đẩy vào CSS custom property --mic-level trên container vạch sóng", async () => {
    const bars = await moOverlayDangGhi();

    // `onLevel` truyền cho startWavRecording chính là publishMicLevel của
    // Provider — gọi thẳng nó để giả lập một khung âm thanh to.
    const { onLevel } = vi.mocked(startWavRecording).mock.calls[0][0]!;
    act(() => onLevel?.(0.73));

    expect(bars.style.getPropertyValue("--mic-level")).toBe("0.730");
  });

  it("mic im lặng (level 0) ⇒ --mic-level về 0, không giữ mức cũ", async () => {
    const bars = await moOverlayDangGhi();
    const { onLevel } = vi.mocked(startWavRecording).mock.calls[0][0]!;

    act(() => onLevel?.(0.9));
    expect(bars.style.getPropertyValue("--mic-level")).toBe("0.900");

    // Provider throttle mức mic ~20Hz (MIC_LEVEL_THROTTLE_MS) — phải qua đủ
    // thời gian thì lần gọi thứ hai mới không bị nuốt.
    act(() => vi.advanceTimersByTime(60));
    act(() => onLevel?.(0));
    expect(bars.style.getPropertyValue("--mic-level")).toBe("0.000");
  });
});
