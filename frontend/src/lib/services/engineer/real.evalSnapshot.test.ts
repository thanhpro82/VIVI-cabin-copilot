import { beforeEach, describe, expect, it, vi } from "vitest";
import { realEngineerService } from "./real";
import { sessionService } from "../session";

describe("getEvalSnapshot", () => {
  beforeEach(() => {
    vi.spyOn(sessionService, "getStoredSession").mockReturnValue({
      accessToken: "t",
      role: "engineer",
    } as never);
  });

  it("map run id, metrics va provenance", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          data: {
            suite: "rag",
            run_id: "20260828T101500Z",
            metrics: { grounded_rate: 1.0, hallucination_rate: 0.05 },
            graded_by: "dap_an_khoa",
            dataset: "cases.jsonl",
            note: null,
          },
        }),
      }),
    );

    const snap = await realEngineerService.getEvalSnapshot("rag");

    expect(snap?.runId).toBe("20260828T101500Z");
    expect(snap?.metrics.hallucination_rate).toBe(0.05);
    expect(snap?.gradedBy).toBe("dap_an_khoa");
  });

  it("404 tra null chu khong nem loi — chua co run la trang thai binh thuong", async () => {
    // Bien "chua do" thanh "hong" chinh la kieu nham ma o `—` sinh ra de tranh.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ error: { code: "NOT_FOUND", message: "chua co run" } }),
      }),
    );

    await expect(realEngineerService.getEvalSnapshot("rag")).resolves.toBeNull();
  });

  it("403 van nem loi — sai quyen khong duoc im lang thanh 'chua co run'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        json: async () => ({ error: { code: "FORBIDDEN", message: "khong du quyen" } }),
      }),
    );

    await expect(realEngineerService.getEvalSnapshot("rag")).rejects.toThrow();
  });
});
