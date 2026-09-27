import { mockTurnService } from "./mock";
import { realTurnService } from "./real";
import type { TurnService } from "./types";

// Mặc định dùng mock nếu chưa cấu hình env (mock-first — xem CODING_STANDARDS.md).
export const turnService: TurnService =
  process.env.NEXT_PUBLIC_USE_MOCK_TURN !== "false" ? mockTurnService : realTurnService;

export type {
  ActionPlan,
  ActionPlanStep,
  AssistantState,
  Citation,
  DriverEvent,
  SafetyLevel,
  SimGear,
  SimMotionResult,
  ToolResultStatus,
  TurnCancelReason,
  TurnResult,
  TurnService,
  VehicleState,
} from "./types";

export { SIM_HARNESS_ABSENT_CODE, SIM_SPEED_MAX_KPH } from "./types";
