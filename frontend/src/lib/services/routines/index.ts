import { mockRoutinesService } from "./mock";
import { realRoutinesService } from "./real";
import type { RoutinesService } from "./types";

// Mặc định dùng mock nếu chưa cấu hình env (mock-first — xem CODING_STANDARDS.md).
export const routinesService: RoutinesService =
  process.env.NEXT_PUBLIC_USE_MOCK_ROUTINES !== "false" ? mockRoutinesService : realRoutinesService;

export type {
  FrontSeatKey,
  Routine,
  RoutineDraft,
  RoutineExecution,
  RoutineExecutionStatus,
  RoutineExecutionStepResult,
  RoutineExecutionStepStatus,
  RoutineIcon,
  RoutinesService,
  RoutineStep,
  RoutineTemplateOrigin,
  WindowKey,
} from "./types";
