import { mockEngineerService } from "./mock";
import { realEngineerService } from "./real";
import type { EngineerService } from "./types";

// Mặc định dùng mock nếu chưa cấu hình env (mock-first — xem CODING_STANDARDS.md).
export const engineerService: EngineerService =
  process.env.NEXT_PUBLIC_USE_MOCK_ENGINEER !== "false" ? mockEngineerService : realEngineerService;

export type {
  ComponentStatus,
  EngineerEvent,
  EngineerLogEntry,
  EngineerService,
  EvalSnapshot,
  EvalSuite,
  HealthStatus,
  MetricsSummary,
  StageLatencyStat,
  VehicleBattery,
  VehicleProfile,
  VehicleProfileUpdate,
  VehicleTrim,
} from "./types";
