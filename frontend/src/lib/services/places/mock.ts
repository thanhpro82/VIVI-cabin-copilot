import { sessionService } from "../session";
import { ServiceError } from "../shared/errors";
import { findPoi } from "@/lib/fixtures/poi";
import type { Place, PlaceLabel, PlacesService } from "./types";

const STORAGE_PREFIX = "vivi.places.";
const MOCK_LATENCY_MS = 300;

interface RawAssignment {
  destinationId: string;
  updatedAt: string;
}

type RawPlaces = Record<PlaceLabel, RawAssignment | null>;

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Cùng lý do với `routines/mock.ts::currentUserId` — không throw khi chưa đăng nhập. */
function currentUserId(): string {
  return sessionService.getStoredSession()?.user.userId ?? "usr_driver_demo";
}

function storageKey(userId: string): string {
  return `${STORAGE_PREFIX}${userId}`;
}

function load(userId: string): RawPlaces {
  if (typeof window === "undefined") return { home: null, office: null };
  const raw = window.localStorage.getItem(storageKey(userId));
  if (!raw) return { home: null, office: null };
  try {
    return JSON.parse(raw) as RawPlaces;
  } catch {
    return { home: null, office: null };
  }
}

function save(userId: string, places: RawPlaces): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(storageKey(userId), JSON.stringify(places));
}

/**
 * Dịch một assignment thô sang `Place` — tra `destinationId` trong fixture
 * POI hiện tại mỗi lần đọc, khớp cách backend tính `valid` lại từ đầu thay vì
 * lưu sẵn (đọc docstring `place_routes.py` §Ba trạng thái).
 */
function resolve(label: PlaceLabel, raw: RawAssignment | null): Place | null {
  if (!raw) return null;
  const poi = findPoi(raw.destinationId);
  return {
    label,
    destinationId: raw.destinationId,
    name: poi?.name ?? null,
    valid: poi !== undefined,
    updatedAt: raw.updatedAt,
  };
}

export const mockPlacesService: PlacesService = {
  async getPlaces() {
    await delay(MOCK_LATENCY_MS);
    const raw = load(currentUserId());
    return { home: resolve("home", raw.home), office: resolve("office", raw.office) };
  },

  async setPlace(label, destinationId) {
    await delay(MOCK_LATENCY_MS);
    if (!findPoi(destinationId)) {
      throw new ServiceError({
        code: "PLACE_DESTINATION_INVALID",
        message: "Điểm đến không nằm trong danh sách offline.",
        retryable: true,
      });
    }
    const userId = currentUserId();
    const raw = load(userId);
    const next: RawPlaces = { ...raw, [label]: { destinationId, updatedAt: new Date().toISOString() } };
    save(userId, next);
    return { home: resolve("home", next.home), office: resolve("office", next.office) };
  },

  async clearPlace(label) {
    await delay(MOCK_LATENCY_MS);
    const userId = currentUserId();
    const raw = load(userId);
    save(userId, { ...raw, [label]: null });
  },
};
