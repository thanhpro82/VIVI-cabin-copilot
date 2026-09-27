// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent, VehicleState } from "@/lib/services/turn/types";
import { OPEN_UI_POLICY } from "@/lib/services/turn/types";
import { DriverShellProvider, useDriverShell } from "./DriverShellProvider";

/**
 * Issue #261, Việc 4: lệnh điều khiển từ phiên chỉ-xem trả về `tool.result`
 * với `error_code = "vehicle_pool_exhausted"` và không có `VehicleCommand`
 * nào được publish. FE phải dịch mã này sang câu tiếng Việt của mục 3b thay
 * vì hiện `displayText` kỹ thuật thô mà backend có thể gửi kèm.
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

const DRIVER_SESSION = {
  sessionId: "ses_test_pool",
  vehicleId: "vehicle-demo-01",
  status: "active" as const,
  startedAt: "2026-01-01T00:00:00Z",
  canDrive: false,
  pool: { total: 3, inUse: 3, free: 0 },
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
  const { send, toast, canDrive } = useDriverShell();
  return (
    <div>
      <button type="button" onClick={() => send("bật điều hòa")} data-testid="send">
        send
      </button>
      <span data-testid="toast">{toast ?? ""}</span>
      <span data-testid="can-drive">{String(canDrive)}</span>
    </div>
  );
}

describe("DriverShellProvider — dịch mã lỗi hết pool xe ảo (issue #261, Việc 4)", () => {
  let emit: (event: DriverEvent) => void = () => {};

  beforeEach(() => {
    emit = () => {};
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.sendText).mockResolvedValue({ turnId: "t1" });
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      return () => {};
    });
  });

  afterEach(() => {
    cleanup();
    vi.resetAllMocks();
  });

  it("tool.result error_code=vehicle_pool_exhausted → toast hiện câu dịch tiếng Việt, KHÔNG hiện displayText kỹ thuật thô", async () => {
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

    // Phiên chỉ-xem vẫn được PHÉP gửi lệnh (khác controlsLocked) — backend mới
    // là nơi từ chối, qua tool.result.error_code. Client-side chỉ ngăn nút bấm
    // trên VehicleControlView (xem VehicleControlView.pool.test.tsx), không
    // ngăn send() ở tầng provider.
    screen.getByTestId("send").click();
    await waitFor(() => expect(turnService.sendText).toHaveBeenCalledWith("bật điều hòa"));

    act(() =>
      emit({
        type: "tool.result",
        turnId: "t1",
        stepId: "step_1",
        status: "failed",
        errorCode: "vehicle_pool_exhausted",
      }),
    );
    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t1",
        result: {
          // Giả lập compose.py CHƯA có câu soạn riêng cho ca này — đúng rủi ro
          // nêu trong PR: hợp đồng #259 chỉ đóng băng error_code, không đóng
          // băng chữ compose.py sinh ra.
          displayText: "Lệnh thất bại: vehicle_pool_exhausted",
          speakText: "Lệnh thất bại",
          citations: [],
          outcomes: [{ stepId: "step_1", status: "failed" }],
          hasMoreToRead: false,
          moMicNgan: false,
        },
      }),
    );
    act(() => emit({ type: "turn.completed", turnId: "t1" }));

    await waitFor(() =>
      expect(screen.getByTestId("toast").textContent).toBe(
        "Hết xe mô phỏng khả dụng — bạn đang ở chế độ chỉ xem, không thể gửi lệnh điều khiển.",
      ),
    );
    expect(screen.queryByText(/vehicle_pool_exhausted/i)).toBeNull();
  });

  it("tool.result completed (errorCode null) → toast dùng nguyên displayText backend, không bị ghi đè", async () => {
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

    screen.getByTestId("send").click();
    await waitFor(() => expect(turnService.sendText).toHaveBeenCalledWith("bật điều hòa"));

    act(() => emit({ type: "tool.result", turnId: "t1", stepId: "step_1", status: "completed", errorCode: null }));
    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t1",
        result: {
          displayText: "Đã bật điều hoà.",
          speakText: "Đã bật điều hoà.",
          citations: [],
          outcomes: [{ stepId: "step_1", status: "completed" }],
          hasMoreToRead: false,
          moMicNgan: false,
        },
      }),
    );
    act(() => emit({ type: "turn.completed", turnId: "t1" }));

    await waitFor(() => expect(screen.getByTestId("toast").textContent).toBe("Đã bật điều hoà."));
  });
});

/**
 * Issue #351: mất quyền lái GIỮA CHỪNG (lease hết hạn, không phải hết pool
 * ngay từ đầu như bộ test trên) — `canDrive` chỉ được set một lần lúc bootstrap
 * (DriverShellProvider.tsx:650), nên phải bám event `error` mã VEHICLE_LEASE_EXPIRED
 * để lật nó, chứ không tự bật lại theo thời gian hay theo tool.result.
 */
describe("DriverShellProvider — mất xe giữa chừng qua error/VEHICLE_LEASE_EXPIRED (issue #351)", () => {
  let emit: (event: DriverEvent) => void = () => {};

  const SESSION_CON_XE = { ...DRIVER_SESSION, canDrive: true, pool: { total: 3, inUse: 1, free: 2 } };

  beforeEach(() => {
    emit = () => {};
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(SESSION_CON_XE);
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

  it("error code=VEHICLE_LEASE_EXPIRED → canDrive chuyển false", async () => {
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

    expect(screen.getByTestId("can-drive").textContent).toBe("true");

    act(() =>
      emit({
        type: "error",
        code: "VEHICLE_LEASE_EXPIRED",
        message: "Hết hạn thuê xe — xe đã được cấp cho người khác. Bạn đang ở chế độ chỉ xem.",
        retryable: true,
      }),
    );

    await waitFor(() => expect(screen.getByTestId("can-drive").textContent).toBe("false"));
    expect(screen.getByTestId("toast").textContent).toBe(
      "Hết hạn thuê xe — xe đã được cấp cho người khác. Bạn đang ở chế độ chỉ xem.",
    );
  });

  it("ca âm tính: error mã khác (APPROVAL_INTENT_AMBIGUOUS) KHÔNG lật canDrive", async () => {
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

    expect(screen.getByTestId("can-drive").textContent).toBe("true");

    act(() =>
      emit({
        type: "error",
        code: "APPROVAL_INTENT_AMBIGUOUS",
        message: "Tôi chưa rõ",
        retryable: true,
      }),
    );

    await waitFor(() => expect(screen.getByTestId("toast").textContent).toBe("Tôi chưa rõ"));
    expect(screen.getByTestId("can-drive").textContent).toBe("true");
  });
});
