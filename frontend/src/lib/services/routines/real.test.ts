import { beforeEach, describe, expect, it, vi } from "vitest";
import { mapRoutine, realRoutinesService } from "./real";
import { sessionService } from "../session";

const RAW_ROUTINE = {
  id: "rtn_1",
  user_id: "usr_driver_01",
  name: "Đi làm",
  icon: "briefcase" as const,
  enabled: true,
  steps: [{ action: "hvac_power", enabled: true }],
  is_default_template: true,
  template_origin: "di_lam" as const,
  version: 3,
  needs_preview: false,
  needs_setup: true,
  runnable: false,
  created_at: "2026-08-29T00:00:00Z",
  updated_at: "2026-08-29T01:00:00Z",
};

function stubFetchOnce(response: { ok: boolean; status: number; json: () => Promise<unknown> }) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
}

describe("routines real.ts", () => {
  beforeEach(() => {
    vi.spyOn(sessionService, "getStoredSession").mockReturnValue({
      accessToken: "t",
      role: "driver",
    } as never);
  });

  describe("mapRoutine", () => {
    it("đổi snake_case -> camelCase, giữ nguyên steps và 3 field dẫn xuất", () => {
      const mapped = mapRoutine(RAW_ROUTINE);
      expect(mapped).toEqual({
        id: "rtn_1",
        userId: "usr_driver_01",
        name: "Đi làm",
        icon: "briefcase",
        enabled: true,
        steps: [{ action: "hvac_power", enabled: true }],
        isDefaultTemplate: true,
        templateOrigin: "di_lam",
        needsPreview: false,
        needsSetup: true,
        runnable: false,
        version: 3,
        createdAt: "2026-08-29T00:00:00Z",
        updatedAt: "2026-08-29T01:00:00Z",
      });
    });
  });

  describe("listRoutines", () => {
    it("map data.items", async () => {
      stubFetchOnce({ ok: true, status: 200, json: async () => ({ data: { items: [RAW_ROUTINE] } }) });
      const routines = await realRoutinesService.listRoutines();
      expect(routines).toHaveLength(1);
      expect(routines[0].needsSetup).toBe(true);
      expect(routines[0].runnable).toBe(false);
    });

    it("lỗi backend giữ nguyên code/message/retryable", async () => {
      stubFetchOnce({
        ok: false,
        status: 403,
        json: async () => ({ error: { code: "FORBIDDEN", message: "không đủ quyền", retryable: false } }),
      });
      await expect(realRoutinesService.listRoutines()).rejects.toMatchObject({
        code: "FORBIDDEN",
        message: "không đủ quyền",
      });
    });
  });

  describe("createRoutine", () => {
    it("gửi đúng thân, map 201", async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({ data: RAW_ROUTINE }) });
      vi.stubGlobal("fetch", fetchMock);

      const draft = { name: "Đi làm", icon: "briefcase" as const, steps: [{ action: "hvac_power" as const, enabled: true }] };
      const routine = await realRoutinesService.createRoutine(draft);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/routines$/),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ name: draft.name, icon: draft.icon, steps: draft.steps }),
        }),
      );
      expect(routine.id).toBe("rtn_1");
    });

    it("mã lỗi trùng tên đi qua ServiceError đúng mã cũ của mock.ts", async () => {
      stubFetchOnce({
        ok: false,
        status: 409,
        json: async () => ({ error: { code: "ROUTINE_NAME_DUPLICATE", message: "đã có Routine khác trùng tên này", retryable: true } }),
      });
      await expect(
        realRoutinesService.createRoutine({ name: "x", icon: "briefcase", steps: [{ action: "hvac_power", enabled: true }] }),
      ).rejects.toMatchObject({ code: "ROUTINE_NAME_DUPLICATE", retryable: true });
    });
  });

  describe("setEnabled", () => {
    it("PUT /{id}/enabled với đúng thân", async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: RAW_ROUTINE }) });
      vi.stubGlobal("fetch", fetchMock);

      await realRoutinesService.setEnabled("rtn_1", false);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/routines\/rtn_1\/enabled$/),
        expect.objectContaining({ method: "PUT", body: JSON.stringify({ enabled: false }) }),
      );
    });
  });

  describe("deleteRoutine", () => {
    it("204 không có thân — không throw, không gọi .json trên nhánh ok", async () => {
      const jsonSpy = vi.fn();
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 204, json: jsonSpy }));
      await expect(realRoutinesService.deleteRoutine("rtn_1")).resolves.toBeUndefined();
      expect(jsonSpy).not.toHaveBeenCalled();
    });

    it("409 ROUTINE_TEMPLATE_PROTECTED — mã mới của backend, không phải ROUTINE_DEFAULT_NOT_DELETABLE của mock", async () => {
      stubFetchOnce({
        ok: false,
        status: 409,
        json: async () => ({
          error: { code: "ROUTINE_TEMPLATE_PROTECTED", message: "mẫu mặc định không xoá được", retryable: false },
        }),
      });
      await expect(realRoutinesService.deleteRoutine("rtn_1")).rejects.toMatchObject({
        code: "ROUTINE_TEMPLATE_PROTECTED",
      });
    });

    it("409 ROUTINE_RUNNING — Routine đang chạy thì không xoá được", async () => {
      stubFetchOnce({
        ok: false,
        status: 409,
        json: async () => ({ error: { code: "ROUTINE_RUNNING", message: "đang chạy", retryable: false } }),
      });
      await expect(realRoutinesService.deleteRoutine("rtn_1")).rejects.toMatchObject({ code: "ROUTINE_RUNNING" });
    });
  });

  describe("restoreDefault", () => {
    it("POST /{id}/restore-default, map kết quả", async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: RAW_ROUTINE }) });
      vi.stubGlobal("fetch", fetchMock);

      const routine = await realRoutinesService.restoreDefault("rtn_1");

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/routines\/rtn_1\/restore-default$/),
        expect.objectContaining({ method: "POST" }),
      );
      expect(routine.version).toBe(3);
    });

    it("409 ROUTINE_NOT_TEMPLATE — mã mới của backend, không phải ROUTINE_NOT_DEFAULT_TEMPLATE của mock", async () => {
      stubFetchOnce({
        ok: false,
        status: 409,
        json: async () => ({ error: { code: "ROUTINE_NOT_TEMPLATE", message: "không phải mẫu mặc định", retryable: false } }),
      });
      await expect(realRoutinesService.restoreDefault("rtn_1")).rejects.toMatchObject({ code: "ROUTINE_NOT_TEMPLATE" });
    });
  });

  describe("chưa đăng nhập", () => {
    it("throw AUTH_REQUIRED thay vì gọi fetch", async () => {
      vi.spyOn(sessionService, "getStoredSession").mockReturnValue(null);
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);

      await expect(realRoutinesService.listRoutines()).rejects.toMatchObject({ code: "AUTH_REQUIRED" });
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  const RAW_EXECUTION = {
    id: "rex_838202cc4faefeff",
    routine_id: "rtn_usr_driver_01_thu_gian",
    session_id: "ses_1",
    routine_version: 1,
    status: "completed" as const,
    current_index: 2,
    approval_id: null,
    steps_total: 2,
    results: [
      { index: 0, action: "interior_light", status: "completed" as const, description: "bật đèn trần", error_code: null },
      { index: 1, action: "media_control", status: "completed" as const, description: "phát nhạc", error_code: null },
    ],
    terminal_reason: "completed",
    created_at: "2026-08-29T09:05:50+00:00",
    updated_at: "2026-08-29T09:05:50+00:00",
  };

  describe("runRoutine (#292)", () => {
    it("POST /routines/{id}/run với đúng session_id, map 202 -> RoutineExecution", async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 202, json: async () => ({ data: RAW_EXECUTION }) });
      vi.stubGlobal("fetch", fetchMock);

      const execution = await realRoutinesService.runRoutine("rtn_usr_driver_01_thu_gian", "ses_1");

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/routines\/rtn_usr_driver_01_thu_gian\/run$/),
        expect.objectContaining({ method: "POST", body: JSON.stringify({ session_id: "ses_1" }) }),
      );
      expect(execution).toEqual({
        id: "rex_838202cc4faefeff",
        routineId: "rtn_usr_driver_01_thu_gian",
        sessionId: "ses_1",
        routineVersion: 1,
        status: "completed",
        currentIndex: 2,
        approvalId: null,
        stepsTotal: 2,
        results: [
          { index: 0, action: "interior_light", status: "completed", description: "bật đèn trần", errorCode: null },
          { index: 1, action: "media_control", status: "completed", description: "phát nhạc", errorCode: null },
        ],
        terminalReason: "completed",
        createdAt: "2026-08-29T09:05:50+00:00",
        updatedAt: "2026-08-29T09:05:50+00:00",
      });
    });

    it("ROUTINE_NEEDS_SETUP (409) đi qua ServiceError", async () => {
      stubFetchOnce({
        ok: false,
        status: 409,
        json: async () => ({ error: { code: "ROUTINE_NEEDS_SETUP", message: "thiếu địa điểm", retryable: false } }),
      });
      await expect(realRoutinesService.runRoutine("rtn_1", "ses_1")).rejects.toMatchObject({ code: "ROUTINE_NEEDS_SETUP" });
    });

    it("ROUTINE_ALREADY_RUNNING (409) đi qua ServiceError", async () => {
      stubFetchOnce({
        ok: false,
        status: 409,
        json: async () => ({ error: { code: "ROUTINE_ALREADY_RUNNING", message: "đang chạy Routine khác", retryable: false } }),
      });
      await expect(realRoutinesService.runRoutine("rtn_1", "ses_1")).rejects.toMatchObject({ code: "ROUTINE_ALREADY_RUNNING" });
    });
  });

  describe("getExecution (#292)", () => {
    it("GET /routine-executions/{id}, map giống hệt runRoutine", async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: RAW_EXECUTION }) });
      vi.stubGlobal("fetch", fetchMock);

      const execution = await realRoutinesService.getExecution("rex_838202cc4faefeff");

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/routine-executions\/rex_838202cc4faefeff$/),
        expect.anything(),
      );
      expect(execution.id).toBe("rex_838202cc4faefeff");
      expect(execution.results[0].description).toBe("bật đèn trần");
    });

    it("404 ROUTINE_EXECUTION_NOT_FOUND đi qua ServiceError", async () => {
      stubFetchOnce({
        ok: false,
        status: 404,
        json: async () => ({ error: { code: "ROUTINE_EXECUTION_NOT_FOUND", message: "không tìm thấy", retryable: false } }),
      });
      await expect(realRoutinesService.getExecution("rex_la")).rejects.toMatchObject({
        code: "ROUTINE_EXECUTION_NOT_FOUND",
      });
    });
  });

  describe("cancelExecution (#298)", () => {
    it("POST /routine-executions/{id}/cancel, map 200 -> RoutineExecution (idempotent, không có thân request)", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          data: {
            ...RAW_EXECUTION,
            status: "user_canceled",
            results: [
              { index: 0, action: "window_position", status: "canceled", description: "window_position", error_code: "canceled_before_run" },
              { index: 1, action: "hvac_power", status: "skipped", description: "hvac_power", error_code: "skipped_due_to_prior_stop" },
            ],
          },
        }),
      });
      vi.stubGlobal("fetch", fetchMock);

      const execution = await realRoutinesService.cancelExecution("rex_838202cc4faefeff");

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/routine-executions\/rex_838202cc4faefeff\/cancel$/),
        expect.objectContaining({ method: "POST" }),
      );
      expect(execution.status).toBe("user_canceled");
      expect(execution.results[0]).toEqual({
        index: 0,
        action: "window_position",
        status: "canceled",
        description: "window_position",
        errorCode: "canceled_before_run",
      });
    });

    it("404 ROUTINE_EXECUTION_NOT_FOUND đi qua ServiceError", async () => {
      stubFetchOnce({
        ok: false,
        status: 404,
        json: async () => ({ error: { code: "ROUTINE_EXECUTION_NOT_FOUND", message: "không tìm thấy", retryable: false } }),
      });
      await expect(realRoutinesService.cancelExecution("rex_la")).rejects.toMatchObject({
        code: "ROUTINE_EXECUTION_NOT_FOUND",
      });
    });
  });

  describe("throwIfError — details pass-through (#298)", () => {
    it("409 ROUTINE_RUNNING mang details.execution_id để nối sang nút Dừng", async () => {
      stubFetchOnce({
        ok: false,
        status: 409,
        json: async () => ({
          error: {
            code: "ROUTINE_RUNNING",
            message: "Routine đang chạy — hãy dừng lần chạy đó trước khi xoá",
            retryable: true,
            details: { execution_id: "rex_838202cc4faefeff" },
          },
        }),
      });
      await expect(realRoutinesService.deleteRoutine("rtn_1")).rejects.toMatchObject({
        code: "ROUTINE_RUNNING",
        details: { execution_id: "rex_838202cc4faefeff" },
      });
    });
  });
});
