import { describe, expect, it } from "vitest";
import { mapVehicleProfile, toProfileRequestBody } from "./real";

/**
 * Payload thật của `GET /api/v1/vehicle/profile` (src/models/api.py:212), giữ
 * nguyên snake_case như wire format — bài test chốt phép ánh xạ, không phải kiểu FE.
 */
const RAW_COMPLETE = {
  vehicle_id: "vehicle-demo-01",
  trim: "plus" as const,
  battery: "catl" as const,
  is_complete: true,
  updated_at: "2026-08-16T04:12:00+00:00",
};

const RAW_UNSET = {
  vehicle_id: "vehicle-demo-01",
  trim: null,
  battery: null,
  is_complete: false,
  updated_at: null,
};

describe("mapVehicleProfile", () => {
  it("ánh xạ đủ cấu hình sang camelCase", () => {
    expect(mapVehicleProfile(RAW_COMPLETE)).toEqual({
      vehicleId: "vehicle-demo-01",
      trim: "plus",
      battery: "catl",
      isComplete: true,
      updatedAt: "2026-08-16T04:12:00+00:00",
    });
  });

  /**
   * Hạt nhân của acceptance "không có profile, FE không tự điền default". `null`
   * phải sống sót nguyên vẹn qua lớp map: một `?? "eco"` ở đây đủ để biến nhánh
   * fail-closed của backend thành một câu trả lời số sai.
   */
  it("chưa khai báo thì giữ nguyên null, không thay bằng mặc định nào", () => {
    const profile = mapVehicleProfile(RAW_UNSET);

    expect(profile.trim).toBeNull();
    expect(profile.battery).toBeNull();
    expect(profile.isComplete).toBe(false);
    expect(profile.updatedAt).toBeNull();
  });

  /**
   * `is_complete` là quyết định của backend. Kể cả khi nó mâu thuẫn với phép suy
   * "đủ hai field" của FE, FE vẫn phải chép lại chứ không sửa — nếu luật đổi
   * (sổ tay bản sau), chỉ backend đổi.
   */
  it("chép nguyên is_complete của backend, không tự tính lại", () => {
    const odd = mapVehicleProfile({ ...RAW_COMPLETE, is_complete: false });
    expect(odd.isComplete).toBe(false);
  });
});

describe("toProfileRequestBody", () => {
  it("gửi đúng cặp trim/battery đã chọn", () => {
    expect(toProfileRequestBody({ trim: "eco", battery: "sdi" })).toEqual({ trim: "eco", battery: "sdi" });
  });

  /**
   * Backend đòi hai field **có mặt** kể cả khi null (`extra="forbid"`, thiếu field
   * là 422): "quên gửi" và "cố ý xoá" phải trông khác nhau. Vì thế kiểm cả key
   * chứ không chỉ giá trị.
   */
  it("xoá cấu hình gửi null tường minh, không bỏ field khỏi body", () => {
    const body = toProfileRequestBody({ trim: null, battery: null });

    expect(Object.keys(body).sort()).toEqual(["battery", "trim"]);
    expect(JSON.parse(JSON.stringify(body))).toEqual({ trim: null, battery: null });
  });

  it("chọn nửa cặp vẫn gửi nửa còn lại là null", () => {
    expect(toProfileRequestBody({ trim: "plus", battery: null })).toEqual({ trim: "plus", battery: null });
  });
});
