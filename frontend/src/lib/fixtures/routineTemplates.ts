import type { RoutineStep, RoutineTemplateOrigin } from "@/lib/services/routines/types";

/**
 * 3 mẫu Routine mặc định do PM/PO chốt ở epic #270 — Đi làm, Về nhà, Thư giãn.
 *
 * KHÔNG sync với backend như `poi.ts`/`media.ts`: chưa có API nào cho Routine
 * (#272 còn mở), nên đây là dữ liệu tự chứa, chỉ dùng để `routines/mock.ts`
 * gieo bản riêng cho từng user lúc đầu. Sửa trực tiếp file này khi cần đổi
 * nội dung mẫu.
 */
export interface RoutineTemplateSeed {
  origin: RoutineTemplateOrigin;
  name: string;
  icon: "briefcase" | "home" | "moon";
  steps: RoutineStep[];
}

export const ROUTINE_TEMPLATE_SEEDS: readonly RoutineTemplateSeed[] = [
  {
    origin: "di_lam",
    name: "Đi làm",
    icon: "briefcase",
    steps: [
      { action: "hvac_power", enabled: true },
      { action: "hvac_temperature", temperatureC: 24 },
      { action: "navigation", destination: "office" },
    ],
  },
  {
    origin: "ve_nha",
    name: "Về nhà",
    icon: "home",
    steps: [
      { action: "navigation", destination: "home" },
      { action: "hvac_power", enabled: true },
      { action: "hvac_temperature", temperatureC: 26 },
    ],
  },
  {
    origin: "thu_gian",
    name: "Thư giãn",
    icon: "moon",
    steps: [
      { action: "interior_light", enabled: true },
      { action: "media_control", controlAction: "play" },
    ],
  },
];
