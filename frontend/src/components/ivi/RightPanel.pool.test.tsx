// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent, VehicleState } from "@/lib/services/turn/types";
import { OPEN_UI_POLICY } from "@/lib/services/turn/types";
import { DriverShellProvider } from "./DriverShellProvider";
import { RightPanel } from "./RightPanel";
import { StatusBar } from "./StatusBar";

/**
 * Issue #261 mục 3b: chế độ chỉ-xem phải khoá **mọi** mặt điều khiển và nói rõ
 * vì sao — không chỉ màn "Điều khiển xe".
 *
 * `RightPanel` (ba nút cửa/điều hoà/đèn ở Trang chính) từng chỉ khoá theo
 * `connectionState`. Chính comment trong file đó đã lập luận sẵn cho ca này:
 * "ba nút này cũng là mặt điều khiển, chỉ khác chỗ đặt" — để chúng bấm được
 * trong khi màn Điều khiển xe đã khoá là vừa mâu thuẫn vừa vẫn bắn request đi.
 *
 * `StatusBar` mang lý do, vì nó hiện trên MỌI màn: tài xế đang ở Nhạc/Bản đồ mà
 * chỉ thấy nút xám thì đúng vào cảnh "bấm rồi mới biết" mà issue muốn tránh.
 */

vi.mock("./Car3DViewer", () => ({ Car3DViewer: () => null }));
vi.mock("@/lib/audio/wavRecorder", () => ({ startWavRecording: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
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

function phien(canDrive: boolean) {
  return {
    sessionId: "ses_rp",
    vehicleId: "vehicle-demo-01",
    status: "active" as const,
    startedAt: "2026-01-01T00:00:00Z",
    canDrive,
    pool: { total: 3, inUse: canDrive ? 2 : 3, free: canDrive ? 1 : 0 },
  };
}

describe("Chế độ chỉ xem lan ra ngoài màn Điều khiển xe (issue #261)", () => {
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

  async function dungMan(canDrive: boolean) {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(phien(canDrive));
    render(
      <DriverShellProvider>
        <StatusBar />
        <RightPanel />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    // Kết nối KHOẺ — tách bạch hẳn với ca mất kết nối của issue #241.
    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));
  }

  it("canDrive: false — ba nút của RightPanel khoá dù kênh sự kiện vẫn sống", async () => {
    await dungMan(false);

    expect(screen.getByRole("button", { name: /mở khoá cửa/i })).toHaveProperty("disabled", true);
    // Nút điều hoà và đèn cũng là mặt điều khiển, khoá cùng một vế.
    const nut = screen.getAllByRole("button").filter((b) => (b as HTMLButtonElement).disabled);
    expect(nut.length).toBeGreaterThanOrEqual(3);
  });

  it("canDrive: false — StatusBar nói RÕ lý do, và không nói nhầm là mất kết nối", async () => {
    await dungMan(false);

    expect(screen.getByText(/chế độ chỉ xem/i)).toBeDefined();
    expect(screen.queryByText(/mất kết nối/i)).toBeNull();
    expect(screen.queryByText(/đang kết nối/i)).toBeNull();
  });

  it("canDrive: true — không khoá gì, và KHÔNG hiện huy hiệu chỉ xem", async () => {
    await dungMan(true);

    expect(screen.getByRole("button", { name: /mở khoá cửa/i })).not.toHaveProperty("disabled", true);
    expect(screen.queryByText(/chế độ chỉ xem/i)).toBeNull();
  });
});
