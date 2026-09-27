import { beforeEach, describe, expect, it, vi } from "vitest";
import { realPlacesService } from "./real";
import { sessionService } from "../session";

function stubFetchOnce(response: { ok: boolean; status: number; json: () => Promise<unknown> }) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
}

describe("places real.ts", () => {
  beforeEach(() => {
    vi.spyOn(sessionService, "getStoredSession").mockReturnValue({ accessToken: "t", role: "driver" } as never);
  });

  describe("getPlaces", () => {
    it("map cả ba trạng thái đúng — null, valid=true, valid=false", async () => {
      stubFetchOnce({
        ok: true,
        status: 200,
        json: async () => ({
          data: {
            home: null,
            office: { destination_id: "poi-work-01", name: "Cơ quan", valid: true, updated_at: "2026-08-29T00:00:00Z" },
          },
        }),
      });
      const places = await realPlacesService.getPlaces();
      expect(places.home).toBeNull();
      expect(places.office).toEqual({
        label: "office",
        destinationId: "poi-work-01",
        name: "Cơ quan",
        valid: true,
        updatedAt: "2026-08-29T00:00:00Z",
      });
    });

    it("valid=false: name null, destinationId vẫn giữ — KHÔNG gộp về null", async () => {
      stubFetchOnce({
        ok: true,
        status: 200,
        json: async () => ({
          data: {
            home: { destination_id: "poi-cu-da-mat", name: null, valid: false, updated_at: "2026-08-29T00:00:00Z" },
            office: null,
          },
        }),
      });
      const places = await realPlacesService.getPlaces();
      expect(places.home).toEqual({
        label: "home",
        destinationId: "poi-cu-da-mat",
        name: null,
        valid: false,
        updatedAt: "2026-08-29T00:00:00Z",
      });
    });
  });

  describe("setPlace", () => {
    it("PUT đúng body snake_case, trả về cả hai nhãn", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          data: {
            home: { destination_id: "poi-home-01", name: "Nhà", valid: true, updated_at: "2026-08-29T00:00:00Z" },
            office: null,
          },
        }),
      });
      vi.stubGlobal("fetch", fetchMock);

      const places = await realPlacesService.setPlace("home", "poi-home-01");

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/places\/home$/),
        expect.objectContaining({ method: "PUT", body: JSON.stringify({ destination_id: "poi-home-01" }) }),
      );
      expect(places.home?.name).toBe("Nhà");
    });

    it("422 PLACE_DESTINATION_INVALID đi qua ServiceError", async () => {
      stubFetchOnce({
        ok: false,
        status: 422,
        json: async () => ({
          error: { code: "PLACE_DESTINATION_INVALID", message: "không nằm trong fixture", retryable: true },
        }),
      });
      await expect(realPlacesService.setPlace("home", "poi-la")).rejects.toMatchObject({
        code: "PLACE_DESTINATION_INVALID",
      });
    });
  });

  describe("clearPlace", () => {
    it("DELETE 204 không có thân, không throw", async () => {
      const jsonSpy = vi.fn();
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204, json: jsonSpy });
      vi.stubGlobal("fetch", fetchMock);

      await expect(realPlacesService.clearPlace("office")).resolves.toBeUndefined();
      expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/places\/office$/), expect.objectContaining({ method: "DELETE" }));
      expect(jsonSpy).not.toHaveBeenCalled();
    });
  });
});
