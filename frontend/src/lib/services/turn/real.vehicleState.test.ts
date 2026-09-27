import { describe, expect, it } from "vitest";
import { mapVehicleState } from "./real";

/**
 * Payload thật lấy từ `GET /vehicle/state` trên backend đang chạy (2026-08-15),
 * rút gọn đúng những field cần cho bài test. Giữ nguyên snake_case như wire
 * format — mục đích của bài test là chốt phép ánh xạ, không phải kiểu FE.
 */
const RAW = {
  vehicle_id: "vehicle-demo-01",
  state_version: 28,
  observed_at: "2026-08-15T05:00:17Z",
  motion: { speed_kph: 0, gear: "P", ignition: "ON" },
  hvac: { power: true, temperature_c: 23, fan_level: 3 },
  windows: { front_left: 0, front_right: 50, rear_left: 0, rear_right: 0 },
  doors: { front_left: "closed", front_right: "closed", rear_left: "closed", rear_right: "closed" },
  media: { status: "playing", volume: 55, track: null },
  navigation: { status: "idle", destination_id: null },
  seat: {
    front_left: { heating: 0, fore_aft: 50, recline: 50, height: 50 },
    front_right: { heating: 0, fore_aft: 50, recline: 50, height: 50 },
  },
  lights: { headlight: "high_beam" as const, interior: true },
  trunk: { position: "open" as const },
};

describe("mapVehicleState", () => {
  /**
   * Regression cho issue #115. Trước đây hai field này bị hard-code
   * `lights: false` / `trunk: "closed"` kèm comment "BE chưa gửi" — comment đó
   * đã sai kể từ PR #92. Hậu quả không phải là thiếu thông tin mà là UI
   * **khẳng định một điều sai** về xe: cốp mở thật, màn hình vẫn ghi "đóng".
   */
  it("đọc lights/trunk từ payload thật, không trả mặc định hard-code", () => {
    const state = mapVehicleState(RAW);

    expect(state.lights).toEqual({ headlight: "high_beam", interior: true });
    expect(state.trunk).toEqual({ position: "open" });
  });

  it("giữ nguyên giá trị chứ không tự suy diễn — cốp đóng thì phải là đóng", () => {
    const state = mapVehicleState({ ...RAW, trunk: { position: "closed" as const } });

    expect(state.trunk.position).toBe("closed");
  });

  it("ánh xạ đủ các domain còn lại sang camelCase", () => {
    const state = mapVehicleState(RAW);

    expect(state.vehicleId).toBe("vehicle-demo-01");
    expect(state.hvac).toEqual({ power: true, temperatureC: 23, fanLevel: 3 });
    expect(state.windows.frontRight).toBe(50);
    expect(state.seat.frontLeft.foreAft).toBe(50);
  });
});
