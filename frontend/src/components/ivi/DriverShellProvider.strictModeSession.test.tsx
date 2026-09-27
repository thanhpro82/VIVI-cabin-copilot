// @vitest-environment jsdom
import { StrictMode } from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { VehicleState } from "@/lib/services/turn/types";
import { DriverShellProvider } from "./DriverShellProvider";

/**
 * Phát hiện trong lúc nghiệm thu real-mode issue #261 (pool xe ảo có trần):
 * React StrictMode double-invoke effect lúc dev khiến `bootstrap()` chạy 2
 * lần trên cùng 1 lượt mount. Cờ `cancelled` cũ chỉ chặn CẬP NHẬT STATE sau
 * khi hủy, không chặn được REQUEST đã bắn — cả 2 lần đều thấy
 * `getCurrentDriverSession()` là `null` (lần đầu chưa kịp lưu) nên cả hai đều
 * gọi `createDriverSession()`. Vô hại khi pool không có trần (mọi phiên đều
 * có xe), nhưng khi pool có trần thì mỗi lần MỘT người mở app lại âm thầm
 * chiếm 2 slot thay vì 1 — bắt được nhờ nghiệm thu real mode, không nhờ unit
 * test nào trước đó vì trước #261 hiện tượng này không có hậu quả quan sát
 * được.
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

describe("DriverShellProvider — bootstrap() không tạo trùng session dưới StrictMode", () => {
  beforeEach(() => {
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.subscribe).mockReturnValue(() => {});
  });

  afterEach(() => {
    cleanup();
    vi.resetAllMocks();
  });

  it("chưa có session sẵn, mount dưới React.StrictMode — createDriverSession() chỉ gọi ĐÚNG 1 LẦN", async () => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(null);
    let resolveCreate!: (session: Awaited<ReturnType<typeof sessionService.createDriverSession>>) => void;
    vi.mocked(sessionService.createDriverSession).mockReturnValue(
      new Promise((resolve) => {
        resolveCreate = resolve;
      }),
    );

    render(
      <StrictMode>
        <DriverShellProvider>
          <div />
        </DriverShellProvider>
      </StrictMode>,
    );

    // StrictMode chạy effect 2 lần trước khi Promise đầu tiên kịp resolve —
    // đúng khe hở gây trùng session. Xác nhận CHỈ 1 request đã bắn ra trong
    // lúc còn đang chờ.
    await act(async () => {
      await Promise.resolve();
    });
    expect(sessionService.createDriverSession).toHaveBeenCalledTimes(1);

    act(() => {
      resolveCreate({
        sessionId: "ses_strict_1",
        vehicleId: "vehicle-demo-01",
        status: "active",
        startedAt: "2026-01-01T00:00:00Z",
        canDrive: true,
        pool: { total: 3, inUse: 1, free: 2 },
      });
    });
    await waitFor(() => expect(turnService.subscribe).toHaveBeenCalled());

    // Vẫn đúng 1 lần sau khi mọi thứ ổn định — không có lần gọi trễ nào khác.
    expect(sessionService.createDriverSession).toHaveBeenCalledTimes(1);
  });

  it("createDriverSession() thất bại — Promise được nhả ra để lần mount sau thử lại được, không kẹt mãi", async () => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValueOnce(null).mockReturnValue({
      sessionId: "ses_retry",
      vehicleId: "vehicle-demo-01",
      status: "active",
      startedAt: "2026-01-01T00:00:00Z",
      canDrive: true,
      pool: null,
    });
    vi.mocked(sessionService.createDriverSession)
      .mockRejectedValueOnce(new Error("Không tạo được session."))
      .mockResolvedValue({
        sessionId: "ses_retry",
        vehicleId: "vehicle-demo-01",
        status: "active",
        startedAt: "2026-01-01T00:00:00Z",
        canDrive: true,
        pool: null,
      });

    const { unmount } = render(
      <DriverShellProvider>
        <div />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(sessionService.createDriverSession).toHaveBeenCalledTimes(1);
    unmount();

    // Mount MỚI (không phải StrictMode double-invoke) sau khi lần trước thất
    // bại — phải thử lại được, không bị Promise cũ (đã reject) chặn vĩnh viễn.
    render(
      <DriverShellProvider>
        <div />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    // getCurrentDriverSession() giờ trả về session thật (giả lập đã lưu từ
    // nơi khác) nên KHÔNG gọi thêm createDriverSession — đúng đường tái sử
    // dụng session hiện có, không phải retry mù.
    expect(sessionService.createDriverSession).toHaveBeenCalledTimes(1);
  });
});
