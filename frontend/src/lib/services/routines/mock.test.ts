// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RoutineDraft, RoutinesService } from "./types";

/**
 * mock.ts giữ state trong localStorage khoá theo userId — không phải
 * module-singleton trong bộ nhớ như turn/session, nhưng vẫn reset module +
 * clear localStorage mỗi test để không ăn seed/side effect của test trước
 * (cùng khuôn với turn/mock.test.ts).
 */
async function freshService(): Promise<RoutinesService> {
  vi.resetModules();
  window.localStorage.clear();
  const mod = await import("./mock");
  return mod.mockRoutinesService;
}

const oneStepDraft: RoutineDraft = {
  name: "Routine test",
  icon: "sun",
  steps: [{ action: "hvac_power", enabled: true }],
};

afterEach(() => {
  window.localStorage.clear();
});

describe("mockRoutinesService", () => {
  it("user mới thấy đủ 3 mẫu mặc định", async () => {
    const service = await freshService();
    const routines = await service.listRoutines();
    const templates = routines.filter((r) => r.isDefaultTemplate);
    expect(templates).toHaveLength(3);
    expect(templates.map((t) => t.name).sort()).toEqual(["Thư giãn", "Về nhà", "Đi làm"].sort());
    expect(templates.every((t) => t.needsPreview === false)).toBe(true);
  });

  it("tạo Routine mới với tên và ít nhất một hành động", async () => {
    const service = await freshService();
    const created = await service.createRoutine(oneStepDraft);
    expect(created.id).toBeTruthy();
    expect(created.isDefaultTemplate).toBe(false);
    expect(created.needsPreview).toBe(true);

    const routines = await service.listRoutines();
    expect(routines.some((r) => r.id === created.id)).toBe(true);
  });

  it("không lưu được Routine rỗng (0 bước)", async () => {
    const service = await freshService();
    await expect(service.createRoutine({ ...oneStepDraft, steps: [] })).rejects.toMatchObject({
      code: "ROUTINE_EMPTY",
    });
  });

  it("không lưu được Routine có hơn 4 hành động", async () => {
    const service = await freshService();
    const fiveSteps: RoutineDraft = {
      ...oneStepDraft,
      steps: Array.from({ length: 5 }, () => ({ action: "hvac_power", enabled: true }) as const),
    };
    await expect(service.createRoutine(fiveSteps)).rejects.toMatchObject({
      code: "ROUTINE_TOO_MANY_STEPS",
    });
  });

  it("tên Routine phải duy nhất sau chuẩn hoá (trim/lowercase/gộp khoảng trắng)", async () => {
    const service = await freshService();
    await service.createRoutine({ ...oneStepDraft, name: "Routine test" });
    await expect(
      service.createRoutine({ ...oneStepDraft, name: "  ROUTINE   test  " }),
    ).rejects.toMatchObject({ code: "ROUTINE_NAME_DUPLICATE" });
  });

  it("template mặc định không xoá được, chỉ tắt/khôi phục", async () => {
    const service = await freshService();
    const routines = await service.listRoutines();
    const template = routines.find((r) => r.isDefaultTemplate);
    expect(template).toBeDefined();

    await expect(service.deleteRoutine(template!.id)).rejects.toMatchObject({
      code: "ROUTINE_DEFAULT_NOT_DELETABLE",
    });

    const disabled = await service.setEnabled(template!.id, false);
    expect(disabled.enabled).toBe(false);
  });

  it("Routine tự tạo xoá được", async () => {
    const service = await freshService();
    const created = await service.createRoutine(oneStepDraft);
    await service.deleteRoutine(created.id);
    const routines = await service.listRoutines();
    expect(routines.some((r) => r.id === created.id)).toBe(false);
  });

  it("sửa template mặc định rồi khôi phục trả lại đúng nội dung gốc", async () => {
    const service = await freshService();
    const routines = await service.listRoutines();
    const template = routines.find((r) => r.templateOrigin === "thu_gian")!;

    const edited = await service.updateRoutine(template.id, {
      name: "Thư giãn (đã sửa)",
      icon: template.icon,
      steps: [{ action: "hvac_power", enabled: false }],
    });
    expect(edited.needsPreview).toBe(true);
    expect(edited.name).toBe("Thư giãn (đã sửa)");

    const restored = await service.restoreDefault(template.id);
    expect(restored.name).toBe("Thư giãn");
    expect(restored.needsPreview).toBe(false);
    expect(restored.steps).toEqual(template.steps);
  });

  it("khôi phục Routine không phải mẫu mặc định thì báo lỗi", async () => {
    const service = await freshService();
    const created = await service.createRoutine(oneStepDraft);
    await expect(service.restoreDefault(created.id)).rejects.toMatchObject({
      code: "ROUTINE_NOT_DEFAULT_TEMPLATE",
    });
  });

  it("sửa Routine tự tạo bật cờ needsPreview", async () => {
    const service = await freshService();
    const created = await service.createRoutine(oneStepDraft);
    const updated = await service.updateRoutine(created.id, {
      name: created.name,
      icon: created.icon,
      steps: [{ action: "hvac_power", enabled: false }],
    });
    expect(updated.needsPreview).toBe(true);
  });

  describe("runRoutine (#292)", () => {
    it("chạy Routine hợp lệ trả về execution đã hoàn tất, đủ số bước", async () => {
      const service = await freshService();
      const created = await service.createRoutine({
        name: "Hai bước",
        icon: "sun",
        steps: [
          { action: "hvac_power", enabled: true },
          { action: "interior_light", enabled: true },
        ],
      });

      const execution = await service.runRoutine(created.id, "ses_1");

      expect(execution.routineId).toBe(created.id);
      expect(execution.sessionId).toBe("ses_1");
      expect(execution.status).toBe("completed");
      expect(execution.stepsTotal).toBe(2);
      expect(execution.results).toHaveLength(2);
      expect(execution.results.every((r) => r.status === "completed")).toBe(true);
    });

    it("Routine đang tắt -> ROUTINE_DISABLED", async () => {
      const service = await freshService();
      const created = await service.createRoutine(oneStepDraft);
      await service.setEnabled(created.id, false);
      await expect(service.runRoutine(created.id, "ses_1")).rejects.toMatchObject({ code: "ROUTINE_DISABLED" });
    });

    it("id không tồn tại -> ROUTINE_NOT_FOUND", async () => {
      const service = await freshService();
      await expect(service.runRoutine("rtn_khong_ton_tai", "ses_1")).rejects.toMatchObject({
        code: "ROUTINE_NOT_FOUND",
      });
    });
  });

  describe("getExecution (#292)", () => {
    it("mock không lưu execution nào -> luôn ROUTINE_EXECUTION_NOT_FOUND", async () => {
      const service = await freshService();
      await expect(service.getExecution("rex_bat_ky")).rejects.toMatchObject({
        code: "ROUTINE_EXECUTION_NOT_FOUND",
      });
    });
  });

  describe("cancelExecution (#298)", () => {
    it("mock không lưu execution nào -> luôn ROUTINE_EXECUTION_NOT_FOUND", async () => {
      const service = await freshService();
      await expect(service.cancelExecution("rex_bat_ky")).rejects.toMatchObject({
        code: "ROUTINE_EXECUTION_NOT_FOUND",
      });
    });
  });
});
