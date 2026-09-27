import { describe, expect, it } from "vitest";
import { mapTraceEntry } from "./real";

/**
 * Payload thật của `GET /api/v1/traces/{id}` và event `trace` của `/ws/engineer`
 * (docs/api_spec.md mục "Citation and trace"), giữ nguyên snake_case.
 *
 * Hai trường ADR-029 thêm vào — `answer_text` và `vehicle_id` — là lý do file này
 * tồn tại: chúng nullable, và một `?? ""` lẻn vào lớp map sẽ biến "lượt chưa từng
 * trả lời" thành "lượt trả lời rỗng" trên màn kỹ sư.
 */
const RAW_DAY_DU = {
  trace_id: "tr_1",
  turn_id: "turn_1",
  vehicle_id: "vehicle-demo-01",
  route_source: "deterministic",
  safe_summary: "Điều chỉnh điều hoà",
  answer_text: "Đã đặt điều hòa ở 22 độ.",
  status: "completed",
  safety_summary: { admission: "executed" },
  stage_latencies_ms: { end_to_end: 2121 },
};

describe("mapTraceEntry", () => {
  it("mang cả câu trả lời và xe sang camelCase", () => {
    const entry = mapTraceEntry(RAW_DAY_DU);

    expect(entry.answerText).toBe("Đã đặt điều hòa ở 22 độ.");
    expect(entry.vehicleId).toBe("vehicle-demo-01");
    expect(entry.safeSummary).toBe("Điều chỉnh điều hoà");
  });

  it("lượt hỏng trước lúc compose thì answerText là null, không phải chuỗi rỗng", () => {
    const entry = mapTraceEntry({ ...RAW_DAY_DU, answer_text: null, status: "failed" });

    expect(entry.answerText).toBeNull();
  });

  /**
   * Backend cũ (trước ADR-029) không gửi hai trường này. FE phải chạy nguyên chứ
   * không nổ — quan trọng trong lúc PR này và bản deploy còn lệch phiên bản.
   */
  it("backend chưa có hai trường thì vẫn map được, cả hai là null", () => {
    const { answer_text, vehicle_id, ...cu } = RAW_DAY_DU;
    void answer_text;
    void vehicle_id;

    const entry = mapTraceEntry(cu);

    expect(entry.answerText).toBeNull();
    expect(entry.vehicleId).toBeNull();
    expect(entry.safeSummary).toBe("Điều chỉnh điều hoà");
  });
});
