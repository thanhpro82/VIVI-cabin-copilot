// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ServiceError } from "@/lib/services/shared/errors";
import { SpeedDebugDrawer } from "./SpeedDebugDrawer";

/**
 * Hành vi đáng khoá của bảng đạo diễn (issue #183):
 *
 * - Thanh trượt hiện **mặc định** ở cả hai chế độ — nhánh "chỉ-xem" cũ đã đi.
 * - Chỉ khi backend trả 404 (`SIM_CONTROL_ENABLED` tắt, hoặc backend chưa có
 *   kênh harness) mới lùi về hướng dẫn gõ console. Đó là ca **bình thường**,
 *   không được hiện như lỗi.
 * - Kéo thanh trượt gộp thành **một** request, không phải mỗi bước một cái.
 * - Giá trị đang kéo không bị state xe (chậm ~1 s vì 202 + MQTT) kéo ngược.
 */

const setSimSpeed = vi.fn<(kph: number, gear?: string) => Promise<unknown>>(async () => ({
  accepted: true,
  speedKph: 0,
  gear: null,
}));

vi.mock("@/lib/services/turn", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/services/turn")>()),
  turnService: { setSimSpeed: (kph: number, gear?: string) => setSimSpeed(kph, gear) },
}));

const refreshVehicleState = vi.fn();
let speedKph = 0;

vi.mock("./DriverShellProvider", () => ({
  useDriverShell: () => ({
    vehicleState: { motion: { speedKph, gear: speedKph > 0 ? "D" : "P" } },
    refreshVehicleState,
  }),
}));

function openDrawer() {
  render(<SpeedDebugDrawer />);
  fireEvent.click(screen.getByRole("button"));
}

function drag(value: number) {
  fireEvent.change(screen.getByLabelText("Tốc độ xe ảo"), { target: { value: String(value) } });
}

describe("SpeedDebugDrawer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setSimSpeed.mockClear();
    setSimSpeed.mockResolvedValue({ accepted: true, speedKph: 0, gear: null });
    refreshVehicleState.mockClear();
    speedKph = 0;
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it("mở ra là có thanh trượt ngay, không cần biết đang mock hay real", () => {
    openDrawer();

    expect(screen.getByLabelText("Tốc độ xe ảo")).toBeDefined();
    // Yêu cầu của issue #183: nói thẳng chuyện xe dùng chung, ngay trên bảng.
    expect(screen.getByText(/dùng chung/i)).toBeDefined();
  });

  it("kéo thanh trượt gửi đúng MỘT request, mang giá trị cuối, không kèm gear", async () => {
    openDrawer();

    drag(20);
    drag(35);
    drag(45);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });

    expect(setSimSpeed).toHaveBeenCalledTimes(1);
    // `gear` bỏ trống có chủ đích: xe ảo tự chọn D/P đúng như `speed 45` gõ console.
    expect(setSimSpeed).toHaveBeenCalledWith(45, undefined);
  });

  it("giữ giá trị đang kéo cho tới khi state xe thật sự đuổi kịp", async () => {
    openDrawer();

    drag(45);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });

    // `vehicleState` vẫn 0 (route trả 202, xe chưa kịp phát state mới) — thanh
    // trượt KHÔNG được bật ngược về 0 giữa lúc người dùng đang kéo.
    expect((screen.getByLabelText("Tốc độ xe ảo") as HTMLInputElement).value).toBe("45");
  });

  it("404 → lùi về hướng dẫn gõ console, KHÔNG hiện như lỗi", async () => {
    setSimSpeed.mockRejectedValue(
      new ServiceError({ code: "NOT_FOUND", message: "Not Found", retryable: false }),
    );
    openDrawer();

    drag(45);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });

    expect(screen.getByText(/python -m src\.vehicle_sim/)).toBeDefined();
    expect(screen.queryByLabelText("Tốc độ xe ảo")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("503 broker chết thì báo lỗi nhưng GIỮ thanh trượt — thử lại được", async () => {
    setSimSpeed.mockRejectedValue(
      new ServiceError({
        code: "MQTT_UNAVAILABLE",
        message: "chưa nối được broker MQTT — không gửi được lệnh tới xe ảo",
        retryable: true,
      }),
    );
    openDrawer();

    drag(45);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });

    expect(screen.getByRole("alert").textContent).toContain("broker MQTT");
    expect(screen.getByLabelText("Tốc độ xe ảo")).toBeDefined();
  });

  it("đang mở thì tự đọc lại state xe mỗi giây — tốc độ người khác đặt cũng hiện ra", async () => {
    openDrawer();

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    expect(refreshVehicleState.mock.calls.length).toBeGreaterThanOrEqual(3);
  });
});
