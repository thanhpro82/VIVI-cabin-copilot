// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent, VehicleState } from "@/lib/services/turn/types";
import { LOCKED_UI_POLICY, OPEN_UI_POLICY } from "@/lib/services/turn/types";
import { DriverShellProvider } from "./DriverShellProvider";
import { VehicleControlView } from "./VehicleControlView";

/**
 * UAT-007 (issue #241): sau khi mất kết nối WS/backend, control surface (khoá
 * cửa/cốp, điều hoà, đèn, sưởi ghế) phải khoá lại và panel "An toàn" phải nói
 * rõ lý do — không được để trông như vẫn điều khiển được trong khi lệnh gửi
 * lên sẽ chỉ ra `ERR_CONNECTION_REFUSED` (UAT-008, xem
 * DriverShellProvider.failClosed.test.tsx).
 */

// Tránh render @google/model-viewer thật trong jsdom (không có WebGL) — Car3DViewer
// chỉ presentational, không liên quan gì tới hành vi đang test ở đây.
vi.mock("./Car3DViewer", () => ({ Car3DViewer: () => null }));

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

describe("VehicleControlView — fail-closed khi mất kết nối (issue #241, UAT-007)", () => {
  let emit: (event: DriverEvent) => void = () => {};

  beforeEach(() => {
    emit = () => {};
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      return () => {};
    });
  });

  afterEach(() => {
    cleanup();
    vi.resetAllMocks();
  });

  it("UAT-007 (cold start): chưa nhận ui.policy nào — control surface đã khoá sẵn, panel An toàn báo 'Đang kết nối'", async () => {
    // Mở app khi backend đã chết: không có `ui.policy` nào để biết là hỏng.
    // Bản đầu của PR #246 chỉ khoá khi ĐÃ nhận LOCKED_UI_POLICY, nên ở đúng ca
    // này nút vẫn bấm được và lệnh vẫn bay ra network (PM/PO review 2026-08-23).
    render(
      <DriverShellProvider>
        <VehicleControlView />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByRole("button", { name: /mở khoá tất cả/i })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Bật điều hoà" })).toHaveProperty("disabled", true);
    expect(screen.getByText(/đang kết nối với hệ thống/i)).toBeDefined();
  });

  it("kết nối khoẻ (policy MỞ): nút mở khoá cửa và bật điều hoà đều bấm được", async () => {
    render(
      <DriverShellProvider>
        <VehicleControlView />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));

    expect(screen.getByRole("button", { name: /mở khoá tất cả/i })).not.toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Bật điều hoà" })).not.toHaveProperty("disabled", true);
  });

  it("mất kết nối (LOCKED_UI_POLICY): khoá cửa/cốp, điều hoà, đèn đều bị disable và panel An toàn báo đúng lý do", async () => {
    render(
      <DriverShellProvider>
        <VehicleControlView />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));
    act(() => emit({ type: "ui.policy", uiPolicy: LOCKED_UI_POLICY }));

    expect(screen.getByRole("button", { name: /mở khoá tất cả/i })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Bật điều hoà" })).toHaveProperty("disabled", true);
    expect(screen.getByText(/mất kết nối với hệ thống/i)).toBeDefined();
  });
});
