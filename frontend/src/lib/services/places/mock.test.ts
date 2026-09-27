// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { mockPlacesService } from "./mock";
import { ServiceError } from "../shared/errors";

beforeEach(() => {
  window.localStorage.clear();
});

describe("mockPlacesService", () => {
  it("chưa gán -> cả hai khoá null", async () => {
    const places = await mockPlacesService.getPlaces();
    expect(places).toEqual({ home: null, office: null });
  });

  it("gán Nhà vào một POI hợp lệ -> valid=true, có tên", async () => {
    const places = await mockPlacesService.setPlace("home", "poi-home-01");
    expect(places.home).toMatchObject({ label: "home", destinationId: "poi-home-01", valid: true, name: "Nhà" });
    expect(places.office).toBeNull();
  });

  it("gán quán cà phê vào Nhà cũng hợp lệ — không giới hạn theo hai POI gợi ý", async () => {
    const places = await mockPlacesService.setPlace("home", "poi-cafe-01");
    expect(places.home?.valid).toBe(true);
  });

  it("destination_id không có trong fixture -> ném ServiceError PLACE_DESTINATION_INVALID", async () => {
    await expect(mockPlacesService.setPlace("home", "poi-khong-ton-tai")).rejects.toBeInstanceOf(ServiceError);
    await expect(mockPlacesService.setPlace("home", "poi-khong-ton-tai")).rejects.toMatchObject({
      code: "PLACE_DESTINATION_INVALID",
    });
  });

  it("bỏ gán rồi đọc lại -> về null", async () => {
    await mockPlacesService.setPlace("office", "poi-work-01");
    await mockPlacesService.clearPlace("office");
    const places = await mockPlacesService.getPlaces();
    expect(places.office).toBeNull();
  });

  it("bỏ gán một nhãn vốn chưa gán -> không lỗi (idempotent)", async () => {
    await expect(mockPlacesService.clearPlace("home")).resolves.toBeUndefined();
  });

  it("gán Nhà không ảnh hưởng Cơ quan và ngược lại", async () => {
    await mockPlacesService.setPlace("home", "poi-home-01");
    const places = await mockPlacesService.setPlace("office", "poi-work-01");
    expect(places.home?.destinationId).toBe("poi-home-01");
    expect(places.office?.destinationId).toBe("poi-work-01");
  });
});
