import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent, TurnService } from "./types";

/**
 * mockTurnService giữ state dạng module-singleton (vehicleState,
 * pendingApprovalId...) — mỗi test cần 1 instance sạch, nên phải
 * resetModules() + import lại thay vì import tĩnh ở đầu file.
 */
async function freshMock(): Promise<{ service: TurnService; setSpeedKph: (kph: number) => void }> {
  vi.resetModules();
  const mod = await import("./mock");
  return { service: mod.mockTurnService, setSpeedKph: mod.__setMockSpeedKph };
}

function collectEvents(service: TurnService) {
  const events: DriverEvent[] = [];
  service.subscribe((e) => events.push(e));
  return events;
}

function waitFor(events: DriverEvent[], type: DriverEvent["type"], timeoutMs = 3000) {
  const start = Date.now();
  return new Promise<void>((resolve, reject) => {
    const check = () => {
      if (events.some((e) => e.type === type)) return resolve();
      if (Date.now() - start > timeoutMs) return reject(new Error(`timeout chờ event ${type}`));
      setTimeout(check, 10);
    };
    check();
  });
}

/**
 * Cho test gửi NHIỀU lượt liên tiếp. `waitFor` ở trên chỉ hỏi "đã từng có event
 * này chưa" nên từ lượt thứ hai trở đi nó trả về ngay lập tức nhờ event của
 * lượt TRƯỚC — assert sau đó đọc phải state cũ. Đếm theo số lần xuất hiện mới
 * phân biệt được lượt nào.
 */
function waitForCount(events: DriverEvent[], type: DriverEvent["type"], count: number, timeoutMs = 3000) {
  const start = Date.now();
  return new Promise<void>((resolve, reject) => {
    const check = () => {
      if (events.filter((e) => e.type === type).length >= count) return resolve();
      if (Date.now() - start > timeoutMs) return reject(new Error(`timeout chờ ${count} event ${type}`));
      setTimeout(check, 10);
    };
    check();
  });
}

describe("mockTurnService", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  it("control_ac là S1 — thực thi ngay, không cần duyệt", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("bật điều hòa 25 độ");
    await waitFor(events, "turn.completed");

    expect(events.find((e) => e.type === "plan.ready")).toMatchObject({ requiresApproval: false });
    expect(events.some((e) => e.type === "approval.required")).toBe(false);

    // `steps` là thứ duy nhất trong allowlist nói được **cái gì vừa được lập kế hoạch**.
    // Lượt bằng giọng nói là 202 async nên client chỉ có WebSocket để bám; không có
    // trường này thì không cách nào biết vừa bật điều hòa hay vừa mở nhạc.
    const planReady = events.find((e) => e.type === "plan.ready");
    expect(planReady && "steps" in planReady && planReady.steps).toMatchObject([
      { tool: "control_ac", domain: "hvac" },
    ]);

    const state = await service.getVehicleState();
    expect(state.hvac.temperatureC).toBe(25);
    expect(state.hvac.power).toBe(true);
  });

  // issue #115 mục 5: mock từng kẹp quạt tới 5 trong khi backend chỉ nhận 0..3
  // (`fan_level_out_of_range`), nên mock xanh mà real đỏ.
  it("quạt gió: nhận mức tuyệt đối và KHÔNG vượt quá 3 như dải thật của backend", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("đặt quạt gió mức 2");
    await waitForCount(events, "turn.completed", 1);
    expect((await service.getVehicleState()).hvac.fanLevel).toBe(2);

    await service.sendText("đặt quạt gió mức 9");
    await waitForCount(events, "turn.completed", 2);
    expect((await service.getVehicleState()).hvac.fanLevel).toBe(3);
  });

  // issue #115 mục 4: enum headlight không có `off` — router thật trả
  // `denied/headlight_off_not_permitted`, mock không được phép dạy hành vi khác.
  it("đèn pha: chọn được chế độ, nhưng KHÔNG tắt được", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("bật đèn chiếu xa");
    await waitForCount(events, "turn.completed", 1);
    expect((await service.getVehicleState()).lights.headlight).toBe("high_beam");

    await service.sendText("chuyển đèn sang chế độ tự động");
    await waitForCount(events, "turn.completed", 2);
    expect((await service.getVehicleState()).lights.headlight).toBe("auto");

    await service.sendText("bật đèn chiếu gần");
    await waitForCount(events, "turn.completed", 3);
    await service.sendText("tắt đèn pha");
    // Không có tool nào khớp → mock rơi về nhánh "không hiểu", state giữ nguyên.
    expect((await service.getVehicleState()).lights.headlight).toBe("low_beam");
  });

  it("đèn trần tắt/bật được cả hai chiều, không đụng đèn pha", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("bật đèn trần");
    await waitForCount(events, "turn.completed", 1);
    let state = await service.getVehicleState();
    expect(state.lights.interior).toBe(true);
    expect(state.lights.headlight).toBe("auto");

    await service.sendText("tắt đèn trần");
    await waitForCount(events, "turn.completed", 2);
    state = await service.getVehicleState();
    expect(state.lights.interior).toBe(false);
  });

  /**
   * Luồng "nghe tiếp" (issue #116) chạy được trong mock, không cần backend và
   * không cần corpus RAG — đó là điều kiện để test được nó ở CI.
   */
  it("câu hỏi sổ tay trả về phần đầu kèm cờ còn-nữa và trích dẫn", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("áp suất lốp tiêu chuẩn là bao nhiêu");
    await waitForCount(events, "turn.completed", 1);

    const response = events.find((e) => e.type === "assistant.response");
    if (response?.type !== "assistant.response") throw new Error("thiếu assistant.response");
    expect(response.result.hasMoreToRead).toBe(true);
    expect(response.result.citations).toHaveLength(1);
    // Từ 21/08 hai kênh dùng chung một chuỗi, nên tín hiệu "còn nữa" mà mắt đọc được
    // chính là lời mời trong câu nói — không còn dấu `(còn tiếp — …)` riêng cho màn hình.
    expect(response.result.displayText).toContain("nghe tiếp");
    expect(response.result.displayText).toBe(response.result.speakText);
  });

  it("'nói tiếp đi' đọc đoạn KẾ TIẾP, giữ nguyên trích dẫn, hết thì hạ cờ", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("áp suất lốp tiêu chuẩn là bao nhiêu");
    await waitForCount(events, "turn.completed", 1);
    await service.sendText("Nói tiếp đi");
    await waitForCount(events, "turn.completed", 2);

    const responses = events.filter((e) => e.type === "assistant.response");
    const second = responses[1];
    if (second?.type !== "assistant.response") throw new Error("thiếu lượt 2");
    expect(second.result.displayText).not.toBe(responses[0].type === "assistant.response" ? responses[0].result.displayText : "");
    expect(second.result.citations).toHaveLength(1);
    expect(second.result.hasMoreToRead).toBe(true);

    // Đoạn cuối — hết phần để đọc thì cờ phải tắt, không thì nút "Nghe tiếp"
    // đứng đó mãi và bấm vào không ra gì.
    await service.sendText("Nói tiếp đi");
    await waitForCount(events, "turn.completed", 3);
    const third = events.filter((e) => e.type === "assistant.response")[2];
    if (third?.type !== "assistant.response") throw new Error("thiếu lượt 3");
    expect(third.result.hasMoreToRead).toBe(false);
    expect(third.result.displayText).not.toContain("nghe tiếp");
  });

  it("lệnh điều khiển không bao giờ bật cờ còn-nữa", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("bật điều hòa 25 độ");
    await waitForCount(events, "turn.completed", 1);

    const response = events.find((e) => e.type === "assistant.response");
    if (response?.type !== "assistant.response") throw new Error("thiếu assistant.response");
    expect(response.result.hasMoreToRead).toBe(false);
  });

  it("câu vu vơ vẫn ra 'chưa nghe rõ', không bị biến thành câu trả lời sổ tay", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("ơ cái đó ừm");
    await waitForCount(events, "turn.completed", 1);

    const response = events.find((e) => e.type === "assistant.response");
    if (response?.type !== "assistant.response") throw new Error("thiếu assistant.response");
    expect(response.result.displayText).toContain("chưa nghe rõ");
    expect(response.result.hasMoreToRead).toBe(false);
  });

  it("control_window luôn là S2 — cần duyệt kể cả khi xe đứng yên", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("mở cửa sổ");
    await waitFor(events, "approval.required");

    const plan = events.find((e) => e.type === "plan.ready");
    expect(plan).toMatchObject({ requiresApproval: true });

    // Lượt cần duyệt vẫn có `steps` — nhưng đây KHÔNG phải mốc để đổi màn. Event này
    // phát ở giai đoạn định tuyến, trước cả hộp thoại phê duyệt; client đổi màn ở đây
    // là hiển thị kết quả của một việc chưa ai đồng ý. Mốc đúng là `tool.result`
    // completed, và ở thời điểm này nó chưa tồn tại. Xem ADR-023.
    expect(plan && "steps" in plan && plan.steps.length).toBe(1);
    expect(events.some((e) => e.type === "tool.result")).toBe(false);

    // Chưa duyệt thì chưa được đổi state.
    const state = await service.getVehicleState();
    expect(state.windows.frontLeft).toBe(0);
  });

  it("duyệt approval (approve) thì thực thi và đổi state", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("mở cửa sổ");
    await waitFor(events, "approval.required");
    const approval = events.find((e) => e.type === "approval.required");
    if (approval?.type !== "approval.required") throw new Error("thiếu approval.required");

    await service.decideApproval(approval.approvalId, "approve", approval.approvedVehicleStateVersion);
    await waitFor(events, "turn.completed");

    const state = await service.getVehicleState();
    expect(state.windows.frontLeft).toBe(100);
  });

  it("từ chối approval (reject) thì KHÔNG đổi state, turn bị canceled", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("mở cửa sổ");
    await waitFor(events, "approval.required");
    const approval = events.find((e) => e.type === "approval.required");
    if (approval?.type !== "approval.required") throw new Error("thiếu approval.required");

    await service.decideApproval(approval.approvalId, "reject", approval.approvedVehicleStateVersion);
    await waitFor(events, "turn.canceled");

    const canceled = events.find((e) => e.type === "turn.canceled");
    expect(canceled).toMatchObject({ reason: "approval_rejected" });

    const state = await service.getVehicleState();
    expect(state.windows.frontLeft).toBe(0);
  });

  it("control_door: S2 khi xe đứng yên — cần duyệt, không bị chặn", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("mở khóa cửa");
    await waitFor(events, "approval.required");

    expect(events.some((e) => e.type === "action.blocked")).toBe(false);
  });

  it("control_door: S3 khi xe đang chạy — bị chặn ngay, không có approval", async () => {
    const { service, setSpeedKph } = await freshMock();
    setSpeedKph(40);
    const events = collectEvents(service);

    await service.sendText("mở khóa cửa");
    await waitFor(events, "action.blocked");

    expect(events.some((e) => e.type === "approval.required")).toBe(false);
    const canceled = events.some((e) => e.type === "turn.completed");
    expect(canceled).toBe(true);

    // Xe vẫn khoá (đóng) — lệnh bị chặn hoàn toàn, không có gì để "duyệt sau".
    // setSpeedKph(40) ở trên đã tự khoá cửa qua speed-sensing auto-lock
    // trước khi gửi lệnh, nhưng giá trị vẫn là "closed" như mặc định ban đầu
    // vì cả hai đều map về cùng trạng thái cửa (đóng), không phân biệt được
    // ở field này — đúng hợp đồng backend, chỉ có "open"/"closed".
    const state = await service.getVehicleState();
    expect(state.doors.frontLeft).toBe("closed");
  });

  it("control_window vẫn là S2 (không phải S3) dù xe đang chạy — khác control_door", async () => {
    const { service, setSpeedKph } = await freshMock();
    setSpeedKph(40);
    const events = collectEvents(service);

    await service.sendText("mở cửa sổ");
    await waitFor(events, "approval.required");

    expect(events.some((e) => e.type === "action.blocked")).toBe(false);
  });

  it("chỉ tối đa 1 approval đang chờ cùng lúc — lệnh S2 thứ 2 bị từ chối ngay", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("mở cửa sổ");
    await waitFor(events, "approval.required");

    await service.sendText("đóng cửa sổ");
    await waitFor(events, "error");

    const error = events.find((e) => e.type === "error");
    expect(error).toMatchObject({ code: "APPROVAL_ALREADY_PENDING" });

    // Vẫn chỉ có đúng 1 approval.required từ lệnh đầu tiên.
    expect(events.filter((e) => e.type === "approval.required")).toHaveLength(1);
  });

  it("câu không nhận diện được → assistant.response yêu cầu nói lại, không có plan", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("ơ cái đó ừm");
    await waitFor(events, "turn.completed");

    expect(events.some((e) => e.type === "plan.ready")).toBe(false);
    const response = events.find((e) => e.type === "assistant.response");
    expect(response).toMatchObject({
      result: { displayText: expect.stringContaining("chưa nghe rõ") },
    });
  });

  it("speed-sensing auto-lock: mở khoá cửa lúc đứng yên rồi tăng tốc >0 → tự khoá lại cửa và cốp", async () => {
    const { service, setSpeedKph } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("mở khóa cửa");
    await waitFor(events, "approval.required");
    const approval = events.find((e) => e.type === "approval.required");
    if (approval?.type !== "approval.required") throw new Error("thiếu approval.required");
    await service.decideApproval(approval.approvalId, "approve", approval.approvedVehicleStateVersion);
    await waitFor(events, "turn.completed");

    const openState = await service.getVehicleState();
    expect(openState.doors.frontLeft).toBe("open");

    // Trước fix: tăng tốc không đụng gì tới cửa đã mở khoá từ lúc đứng yên —
    // lỗ hổng an toàn thật (phát hiện qua review 2026-08-09).
    setSpeedKph(40);
    const movingState = await service.getVehicleState();
    expect(movingState.doors.frontLeft).toBe("closed");
    expect(movingState.doors.frontRight).toBe("closed");
    expect(movingState.doors.rearLeft).toBe("closed");
    expect(movingState.doors.rearRight).toBe("closed");
    expect(movingState.trunk.position).toBe("closed");
  });

  it("approval hết hạn sau timeout → turn.canceled reason approval_expired", async () => {
    vi.useFakeTimers();
    const { service } = await freshMock();
    const events = collectEvents(service);

    await service.sendText("mở cửa sổ");
    await vi.advanceTimersByTimeAsync(1000); // qua khỏi delay routing để có approval.required
    expect(events.some((e) => e.type === "approval.required")).toBe(true);

    await vi.advanceTimersByTimeAsync(16000); // qua khỏi APPROVAL_TIMEOUT_MS (15000ms)

    const canceled = events.find((e) => e.type === "turn.canceled");
    expect(canceled).toMatchObject({ reason: "approval_expired" });

    vi.useRealTimers();
  });

  it("ui.policy — subscribe phát ngay 1 event khoá khi xe đang chạy lúc nối máy", async () => {
    const { service, setSpeedKph } = await freshMock();
    setSpeedKph(40);
    const events = collectEvents(service);

    const policyEvents = events.filter((e) => e.type === "ui.policy");
    expect(policyEvents).toHaveLength(1);
    expect(policyEvents[0]).toMatchObject({ uiPolicy: { lockSmallControls: true, enlargeMicButton: true } });
  });

  it("ui.policy — subscribe phát ngay 1 event mở khi xe đứng yên lúc nối máy", async () => {
    const { service } = await freshMock();
    const events = collectEvents(service);

    const policyEvents = events.filter((e) => e.type === "ui.policy");
    expect(policyEvents).toHaveLength(1);
    expect(policyEvents[0]).toMatchObject({ uiPolicy: { lockSmallControls: false, allowTextInput: true } });
  });

  it("ui.policy — băng qua ranh giới 0↔>0 mới phát thêm event, không phát mỗi lần đổi tốc độ", async () => {
    const { service, setSpeedKph } = await freshMock();
    const events = collectEvents(service);
    const countAfterSubscribe = events.filter((e) => e.type === "ui.policy").length;

    setSpeedKph(40); // 0 -> >0: băng qua ranh giới, phát thêm
    setSpeedKph(50); // >0 -> >0: cùng phía, không phát thêm
    expect(events.filter((e) => e.type === "ui.policy")).toHaveLength(countAfterSubscribe + 1);

    setSpeedKph(0); // >0 -> 0: băng qua ranh giới lần nữa
    expect(events.filter((e) => e.type === "ui.policy")).toHaveLength(countAfterSubscribe + 2);
  });

  /**
   * `setSimSpeed` — bản mock của kênh harness `v1/sim` (issue #183, ADR-024).
   *
   * Mock KHÔNG chứng minh gì về kênh harness thật (không có MQTT nào ở đây); nó
   * chỉ phải giữ cho màn hình mock mô phỏng đúng chiếc xe mà backend mô phỏng.
   * Chỗ dễ lệch nhất là `gear`: backend đòi `speed_kph == 0 && gear == "P"` mới
   * cho cửa xuống S2, nên một mock giữ nguyên `P` ở 45 km/h sẽ nói dối về ca S3.
   */
  describe("setSimSpeed", () => {
    it("bỏ trống gear thì tự chọn D khi chạy và P khi dừng, đúng quy ước set_motion(gear=None)", async () => {
      const { service } = await freshMock();

      await service.setSimSpeed(45);
      let state = await service.getVehicleState();
      expect(state.motion).toMatchObject({ speedKph: 45, gear: "D" });

      await service.setSimSpeed(0);
      state = await service.getVehicleState();
      expect(state.motion).toMatchObject({ speedKph: 0, gear: "P" });
    });

    it("gear truyền tay thì dùng đúng gear đó, không tự suy từ tốc độ", async () => {
      const { service } = await freshMock();

      await service.setSimSpeed(0, "D");

      const state = await service.getVehicleState();
      expect(state.motion).toMatchObject({ speedKph: 0, gear: "D" });
    });

    it("echo lại gear NGƯỜI GỌI gửi, không phải gear xe đang mang", async () => {
      // Giống hệt backend: route echo `body.gear`, còn việc suy ra D/P là do xe
      // ảo làm. Trả về gear đã suy ở đây sẽ khiến UI tưởng mình biết số thật mà
      // không cần poll — đúng cái ảo tưởng mà 202 sinh ra để chặn.
      const { service } = await freshMock();

      const result = await service.setSimSpeed(45);

      expect(result).toEqual({ accepted: true, speedKph: 45, gear: null });
      expect((await service.getVehicleState()).motion.gear).toBe("D");
    });

    it("chạy tiếp tục dùng chung đường với __setMockSpeedKph — vẫn tự khoá cửa và vẫn phát ui.policy", async () => {
      const { service } = await freshMock();
      const events = collectEvents(service);
      const before = events.filter((e) => e.type === "ui.policy").length;

      await service.setSimSpeed(40);

      const state = await service.getVehicleState();
      expect(state.doors.frontLeft).toBe("closed");
      expect(state.trunk.position).toBe("closed");
      expect(events.filter((e) => e.type === "ui.policy")).toHaveLength(before + 1);
    });
  });
});
