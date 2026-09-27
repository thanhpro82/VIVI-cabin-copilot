// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { __setMockVehiclePool, mockSessionService } from "./mock";

/**
 * Issue #261 Việc 2: mock phải dựng được **cả hai ca** (`can_drive: true` và
 * `false`) để thử UI mà không cần backend chạy.
 */

afterEach(() => {
  __setMockVehiclePool({ canDrive: true, pool: null });
  window.localStorage.clear();
});

describe("mockSessionService — pool xe ảo", () => {
  it("mặc định khớp VEHICLE_POOL_SIZE=1 của repo: lái được, không có trần để hiện", async () => {
    const phien = await mockSessionService.createDriverSession("vehicle-demo-01");

    expect(phien.canDrive).toBe(true);
    // `null` chứ không phải `{total: 1, ...}` — không cấp phát thì không có
    // trần nào để nói, đúng lý lẽ của `suc_chua_xe()` ở backend.
    expect(phien.pool).toBeNull();
  });

  it("dựng được ca hết pool → chỉ xem", async () => {
    __setMockVehiclePool({ canDrive: false, pool: { total: 3, inUse: 3, free: 0 } });

    const phien = await mockSessionService.createDriverSession("vehicle-demo-01");

    expect(phien.canDrive).toBe(false);
    expect(phien.pool).toEqual({ total: 3, inUse: 3, free: 0 });
    // Bẫy backend đã khoá bằng test: phiên chỉ-xem VẪN có vehicle_id
    // (`sessions.vehicle_id` là NOT NULL), nên không được suy quyền lái từ nó.
    expect(phien.vehicleId).toBe("vehicle-demo-01");
  });

  it("dựng được ca pool đang cấp phát nhưng vẫn còn chỗ", async () => {
    __setMockVehiclePool({ canDrive: true, pool: { total: 3, inUse: 2, free: 1 } });

    const phien = await mockSessionService.createDriverSession("vivi-xe-02");

    expect(phien.canDrive).toBe(true);
    expect(phien.pool).toEqual({ total: 3, inUse: 2, free: 1 });
  });

  it("phiên đã lưu giữ nguyên giá trị lúc TẠO, không đổi theo lời gọi sau", async () => {
    __setMockVehiclePool({ canDrive: false, pool: { total: 3, inUse: 3, free: 0 } });
    await mockSessionService.createDriverSession("vehicle-demo-01");

    // Đổi cấu hình mock sau khi phiên đã tạo — phiên cũ phải giữ nguyên, đúng
    // như hợp đồng thật (hai trường này chỉ đến từ `POST /sessions`).
    __setMockVehiclePool({ canDrive: true, pool: null });

    expect(mockSessionService.getCurrentDriverSession()?.canDrive).toBe(false);
  });
});
