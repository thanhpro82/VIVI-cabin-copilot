import { mockPlacesService } from "./mock";
import { realPlacesService } from "./real";
import type { PlacesService } from "./types";

// Mặc định dùng mock nếu chưa cấu hình env (mock-first — xem CODING_STANDARDS.md).
export const placesService: PlacesService =
  process.env.NEXT_PUBLIC_USE_MOCK_PLACES !== "false" ? mockPlacesService : realPlacesService;

export type { Place, PlaceLabel, Places, PlacesService } from "./types";
