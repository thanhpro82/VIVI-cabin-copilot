// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent, VehicleState } from "@/lib/services/turn/types";
import { OPEN_UI_POLICY } from "@/lib/services/turn/types";
import { ServiceError } from "@/lib/services/shared/errors";
import { DriverShellProvider } from "./DriverShellProvider";
import { VehicleControlView } from "./VehicleControlView";

/**
 * Issue #261 (ADR-028): phiên chỉ-xem (hết pool xe ảo) phải khoá control
 * surface và nói rõ lý do — LÝ DO KHÁC mất kết nối (issue #241,
 * VehicleControlView.failClosed.test.tsx): kết nối vẫn tốt, chỉ là không còn
 * xe nào để cấp cho phiên này.
 */

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

async function renderOnline() {
  render(
    <DriverShellProvider>
      <VehicleControlView />
    </DriverShellProvider>,
  );
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("VehicleControlView — chế độ chỉ xem khi hết pool xe ảo (issue #261)", () => {
  let emit: (event: DriverEvent) => void = () => {};

  beforeEach(() => {
    emit = () => {};
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

  it("canDrive: false — control bị khoá dù kết nối vẫn tốt, thông điệp KHÁC 'mất kết nối'", async () => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue({
      sessionId: "ses_test_2",
      vehicleId: "vehicle-demo-01",
      status: "active",
      startedAt: "2026-01-01T00:00:00Z",
      canDrive: false,
      pool: { total: 3, inUse: 3, free: 0 },
    });

    await renderOnline();
    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));

    expect(screen.getByRole("button", { name: /mở khoá tất cả/i })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Bật điều hoà" })).toHaveProperty("disabled", true);
    expect(screen.getByText(/hết xe mô phỏng khả dụng/i)).toBeDefined();
    expect(screen.getByText(/chỉ xem/i)).toBeDefined();
    // Không được lẫn với thông điệp mất kết nối của issue #241.
    expect(screen.queryByText(/mất kết nối với hệ thống/i)).toBeNull();
    // Trần pool ("Lúc vào phiên: N/3 xe") cố tình ẩn khỏi UI cho demo — dữ liệu
    // pool vẫn tồn tại và vẫn khoá control qua `canDrive` (assertions ở trên),
    // chỉ phần hiển thị con số bị ẩn.
    expect(screen.queryByText(/lúc vào phiên/i)).toBeNull();
    expect(screen.queryByText(/xe đang dùng/i)).toBeNull();
  });

  it("mất lease khi đọc state — khoá control và không giữ state của xe đã chuyển chủ", async () => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue({
      sessionId: "ses_lease_het_han",
      vehicleId: "vivi-xe-01",
      status: "active",
      startedAt: "2026-01-01T00:00:00Z",
      canDrive: true,
      pool: { total: 2, inUse: 1, free: 1 },
    });
    vi.mocked(turnService.getVehicleState).mockRejectedValue(
      new ServiceError({
        code: "VEHICLE_LEASE_EXPIRED",
        message: "Phiên không còn xe điều khiển khả dụng.",
        retryable: true,
      }),
    );

    await renderOnline();
    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));

    expect(screen.getByRole("button", { name: /mở khoá tất cả/i })).toHaveProperty("disabled", true);
    expect(screen.getByText(/hết xe mô phỏng khả dụng/i)).toBeDefined();
  });

  it("canDrive: true, pool cấp phát — control vẫn dùng được, vẫn hiện trần pool", async () => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue({
      sessionId: "ses_test_3",
      vehicleId: "vivi-xe-02",
      status: "active",
      startedAt: "2026-01-01T00:00:00Z",
      canDrive: true,
      pool: { total: 3, inUse: 2, free: 1 },
    });

    await renderOnline();
    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));

    expect(screen.getByRole("button", { name: /mở khoá tất cả/i })).not.toHaveProperty("disabled", true);
    // Trần pool ("Lúc vào phiên: N/3 xe") cố tình ẩn khỏi UI cho demo — xem
    // test đầu tiên ở trên.
    expect(screen.queryByText(/lúc vào phiên/i)).toBeNull();
    expect(screen.queryByText(/hết xe mô phỏng khả dụng/i)).toBeNull();
  });

  it("pool: null (VEHICLE_POOL_SIZE=1) — không hiện trần pool nào, hành vi y hệt hôm nay", async () => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue({
      sessionId: "ses_test_4",
      vehicleId: "vehicle-demo-01",
      status: "active",
      startedAt: "2026-01-01T00:00:00Z",
      canDrive: true,
      pool: null,
    });

    await renderOnline();
    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));

    expect(screen.getByRole("button", { name: /mở khoá tất cả/i })).not.toHaveProperty("disabled", true);
    expect(screen.queryByText(/lúc vào phiên/i)).toBeNull();
    expect(screen.queryByText(/xe đang dùng/i)).toBeNull();
  });
});
