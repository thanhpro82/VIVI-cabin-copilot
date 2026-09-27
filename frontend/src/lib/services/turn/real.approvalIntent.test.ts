/**
 * `approval.intent.detected` — ánh xạ event handoff của lượt phê duyệt bằng lời (#147).
 *
 * Từ #191 backend tự chốt quyết định, nhưng **bất đối xứng** — đồng ý trần ("ừ") cố ý
 * không chốt, và trường `committed` là thứ duy nhất nói cho IVI biết mình đang ở ca
 * nào. Ánh xạ hỏng thì hoặc lệnh treo (không ai chốt), hoặc IVI chốt hộ đúng cái
 * backend vừa từ chối chốt (issue #207) — cả hai đều im lặng, không ai báo lỗi gì.
 *
 * Payload chép **nguyên văn** từ `emit_approval_intent_handoff`
 * (`src/services/ivi_events.py`), không viết lại theo trí nhớ: khớp một hình dạng
 * tưởng tượng thì test xanh mà FE vẫn hỏng, đúng cách bug #136 lọt lần đầu.
 */
import { describe, expect, it } from "vitest";

import { mapServerEvent } from "./real";

const RAW = {
  type: "approval.intent.detected",
  turn_id: "turn_intent_01",
  payload: {
    approval_id: "appr-123",
    original_turn_id: "turn_goc_01",
    decision: "approve",
    approved_vehicle_state_version: 3,
  },
};

describe("mapServerEvent — approval.intent.detected", () => {
  it("đọc đủ bốn trường của hợp đồng, không để undefined", () => {
    const event = mapServerEvent(RAW);

    expect(event).toEqual({
      type: "approval.intent.detected",
      turnId: "turn_intent_01",
      approvalId: "appr-123",
      originalTurnId: "turn_goc_01",
      decision: "approve",
      approvedVehicleStateVersion: 3,
    });
  });

  it("giữ nguyên decision reject", () => {
    const event = mapServerEvent({ ...RAW, payload: { ...RAW.payload, decision: "reject" } });
    expect(event?.type === "approval.intent.detected" && event.decision).toBe("reject");
  });

  it("approvalId là chuỗi thật, không phải undefined", () => {
    // Kiểm riêng vì đây là trường **duy nhất** IVI cần để gọi REST. Thiếu nó thì cả cơ
    // chế handoff thành vô dụng, và lỗi chỉ hiện ra ở `GET /approvals/undefined`.
    const event = mapServerEvent(RAW);
    const id = event?.type === "approval.intent.detected" ? event.approvalId : undefined;
    expect(typeof id).toBe("string");
    expect(id).not.toBe("undefined");
    expect(id).toBeTruthy();
  });

  it("committed: đọc được cả true và false", () => {
    // Trường của #191/#207. Nó là thứ DUY NHẤT phân biệt "backend đã chốt" với
    // "backend cố ý không chốt" — hai ca có payload giống hệt nhau ở mọi trường khác.
    const daChot = mapServerEvent({ ...RAW, payload: { ...RAW.payload, committed: true } });
    const chuaChot = mapServerEvent({ ...RAW, payload: { ...RAW.payload, committed: false } });

    expect(daChot?.type === "approval.intent.detected" && daChot.committed).toBe(true);
    expect(chuaChot?.type === "approval.intent.detected" && chuaChot.committed).toBe(false);
  });

  it("committed vắng mặt thì là undefined, KHÔNG phải false", () => {
    // `?? false` ở mapper sẽ biến "BE cũ, chưa biết" thành "chắc chắn chưa chốt", tức
    // xoá mất đường lui theo phiên bản mà `DriverShellProvider` dựa vào để merge được
    // trước phần BE của #207. Hai giá trị này phải phân biệt được ở nơi tiêu thụ.
    const event = mapServerEvent(RAW);
    const c = event?.type === "approval.intent.detected" ? event.committed : "sai-nhánh";
    expect(c).toBeUndefined();
  });

  it("version là số, không phải chuỗi", () => {
    // `decideApproval(id, decision, version)` gửi thẳng số này lên REST; một chuỗi ở đây
    // sẽ thành `"3"` trong JSON và backend từ chối vì sai kiểu.
    const event = mapServerEvent(RAW);
    const v = event?.type === "approval.intent.detected" ? event.approvedVehicleStateVersion : null;
    expect(typeof v).toBe("number");
  });
});
