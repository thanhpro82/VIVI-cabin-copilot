import { mockSessionService } from "./mock";
import { realSessionService } from "./real";
import type { SessionService } from "./types";

// Mặc định dùng mock nếu chưa cấu hình env (mock-first — xem CODING_STANDARDS.md).
export const sessionService: SessionService =
  process.env.NEXT_PUBLIC_USE_MOCK_SESSION !== "false" ? mockSessionService : realSessionService;

export type { AuthUser, DriverSession, LoginResult, SessionService, UserRole, VehiclePoolStatus } from "./types";
