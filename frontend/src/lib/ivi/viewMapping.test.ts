import { describe, expect, it } from "vitest";
import type { PlanReadyStep } from "@/lib/services/turn/types";
import { viewForStep } from "./viewMapping";

function step(partial: Partial<PlanReadyStep>): PlanReadyStep {
  return { stepId: "step_1", tool: "x", domain: null, args: {}, ...partial };
}

describe("viewForStep", () => {
  it.each([
    ["hvac", "vehicle"],
    ["seat", "vehicle"],
    ["windows", "vehicle"],
    ["doors", "vehicle"],
    ["lights", "vehicle"],
    ["trunk", "vehicle"],
    ["media", "music"],
    ["navigation", "map"],
  ])("domain %s -> %s", (domain, view) => {
    expect(viewForStep(step({ domain, tool: "set_something" }))).toBe(view);
  });

  it.each([
    ["youtube", "youtube"],
    ["tiktok", "tiktok"],
    ["spotify", "spotify"],
  ])("open_app(%s) -> %s", (app, view) => {
    // `open_app` có domain=null (ADR-023) nên CHỈ args mới phân biệt được app.
    expect(viewForStep(step({ tool: "open_app", args: { app } }))).toBe(view);
  });

  it("motion không có màn riêng — nó là tốc độ, không phải một trang", () => {
    expect(viewForStep(step({ domain: "motion", tool: "set_speed" }))).toBeNull();
  });

  it.each([["query_manual"], ["get_vehicle_state"], ["search_nearby_poi"]])(
    "tool S0 %s không đổi màn",
    (tool) => {
      // null là câu trả lời hợp lệ: nhảy màn khi tra sổ tay xong là giật màn
      // hình của tài xế vì một lý do họ không nhìn thấy được.
      expect(viewForStep(step({ tool }))).toBeNull();
    },
  );

  it("app lạ hoặc args thiếu thì trả null, không ném", () => {
    expect(viewForStep(step({ tool: "open_app", args: { app: "netflix" } }))).toBeNull();
    expect(viewForStep(step({ tool: "open_app", args: {} }))).toBeNull();
    expect(viewForStep(step({ tool: "open_app", args: { app: 42 } }))).toBeNull();
  });

  it("domain lạ (backend mới hơn frontend) trả null thay vì vỡ", () => {
    expect(viewForStep(step({ domain: "domain-chua-ton-tai" }))).toBeNull();
  });
});
