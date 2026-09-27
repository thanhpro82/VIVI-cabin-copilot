// @vitest-environment jsdom
/**
 * Nói "Đồng ý" → IVI gọi `decideApproval` (#147).
 *
 * Backend chỉ **nhận ra** ý định rồi dừng (`api_spec.md:278`): nó phát
 * `approval.intent.detected` và không tự chốt. Nếu FE không nghe event ấy thì tài xế
 * nói "Đồng ý", backend hiểu đúng, **mà lệnh vẫn treo** — và không ai báo lỗi gì cả.
 * Đó chính là hiện trạng trước PR này: `grep -rn "approval.intent" frontend/src/` ra
 * rỗng.
 *
 * Ba acceptance của @thanhpro82 ở #142, kiểm ở tầng gọi được:
 *
 *   1. nói "Đồng ý"      -> gọi `decideApproval` ĐÚNG MỘT LẦN
 *   2. nói "Không đồng ý"-> gọi với `reject`, không thực thi
 *   3. câu mơ hồ         -> không gọi gì; hộp thoại còn nguyên để nói lại
 */
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent } from "@/lib/services/turn/types";
import { DriverShellProvider, useDriverShell } from "./DriverShellProvider";

  // Mốc hết hạn phải là **tương lai thật**, không phải một hằng số 2026-01-01: từ khi
  // hộp thoại tự gỡ theo `expires_at` (bug "hộp thoại duyệt biến mất"), một mốc trong
  // quá khứ nghĩa là fixture đang mô tả một phê duyệt ĐÃ CHẾT, và hộp thoại biến mất
  // ngay — test đỏ vì fixture, không phải vì hành vi.
const HET_HAN = () => new Date(Date.now() + 30_000).toISOString();

vi.mock("@/lib/audio/wavRecorder", () => ({
  startWavRecording: vi.fn(),
  createSpeechEnergyTracker: vi.fn(() => ({ push: () => false, reset: () => {} })),
}));

vi.mock("@/lib/services/session", () => ({
  sessionService: {
    getCurrentDriverSession: vi.fn(),
    createDriverSession: vi.fn(),
    getStoredSession: vi.fn(),
    logout: vi.fn(),
  },
}));

vi.mock("@/lib/services/turn", () => ({
  turnService: {
    getVehicleState: vi.fn(),
    sendText: vi.fn(),
    sendVoice: vi.fn(),
    decideApproval: vi.fn(),
    getCitation: vi.fn(),
    subscribe: vi.fn(),
  },
}));

const { startWavRecording } = await import("@/lib/audio/wavRecorder");
const { sessionService } = await import("@/lib/services/session");
const { turnService } = await import("@/lib/services/turn");

const PHIEN = {
  sessionId: "ses_vi_1",
  vehicleId: "vehicle-demo-01",
  status: "active",
  startedAt: "2026-01-01T00:00:00Z",
};

const TRANG_THAI_XE = {
  vehicleId: "vehicle-demo-01",
  stateVersion: 3,
  observedAt: "2026-01-01T00:00:00Z",
  motion: { speedKph: 0, gear: "P", ignition: "ON" },
  hvac: { power: false, temperatureC: 24, fanLevel: 0 },
  windows: { frontLeft: 0, frontRight: 0, rearLeft: 0, rearRight: 0 },
  doors: { frontLeft: "closed", frontRight: "closed", rearLeft: "closed", rearRight: "closed" },
  media: { status: "stopped", volume: 30, track: null },
  navigation: { status: "idle", destinationId: null },
  seat: {
    frontLeft: { heating: 0, foreAft: 50, recline: 50, height: 50 },
    frontRight: { heating: 0, foreAft: 50, recline: 50, height: 50 },
  },
  lights: { headlight: "auto", interior: false },
  trunk: { position: "closed" },
};

const Y_DINH_DONG_Y: DriverEvent = {
  type: "approval.intent.detected",
  turnId: "turn_intent",
  approvalId: "appr-123",
  originalTurnId: "turn_goc",
  decision: "approve",
  approvedVehicleStateVersion: 3,
};

function Consumer() {
  const { pendingApproval, approvalNeedsTap, approve } = useDriverShell();
  return (
    <>
      <span data-testid="cho-duyet">{pendingApproval ? pendingApproval.approvalId : "khong"}</span>
      {/* Hai thứ dưới đây thay cho việc render cả `HitlModal`: bài kiểm ở file này là
          về **luồng quyết định** trong Provider, không phải về giao diện hộp thoại.
          Nút gọi thẳng `approve` từ context — đúng thứ `HitlModal` làm, không hơn. */}
      <span data-testid="cho-cham">{approvalNeedsTap ? "co" : "khong"}</span>
      <button type="button" data-testid="nut-duyet" onClick={approve} />
    </>
  );
}

async function dungProvider() {
  let phat: (event: DriverEvent) => void = () => {};
  vi.mocked(turnService.subscribe).mockImplementation((cb) => {
    phat = cb;
    return () => {};
  });
  const view = render(
    <DriverShellProvider>
      <Consumer />
    </DriverShellProvider>,
  );
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return { phat, view };
}

describe("approval.intent.detected -> decideApproval", () => {
  beforeEach(() => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(PHIEN as never);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(TRANG_THAI_XE as never);
    vi.mocked(turnService.decideApproval).mockResolvedValue(undefined as never);
    // approval.required giờ tự bật mic (xem DriverShellProvider.autoListenApproval.test.tsx)
    // — mọi test ở đây phát approval.required nên cần mock startWavRecording.
    vi.mocked(startWavRecording).mockResolvedValue({
      stop: vi.fn().mockResolvedValue(new Blob()),
      cancel: vi.fn(),
      hadSpeech: () => true,
    } as never);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("nói 'Đồng ý' thì gọi decideApproval đúng một lần, đúng tham số", async () => {
    const { phat } = await dungProvider();

    await act(async () => phat(Y_DINH_DONG_Y));

    expect(turnService.decideApproval).toHaveBeenCalledTimes(1);
    expect(turnService.decideApproval).toHaveBeenCalledWith("appr-123", "approve", 3);
  });

  it("nói 'Không đồng ý' thì gửi reject", async () => {
    const { phat } = await dungProvider();

    await act(async () => phat({ ...Y_DINH_DONG_Y, decision: "reject" }));

    expect(turnService.decideApproval).toHaveBeenCalledWith("appr-123", "reject", 3);
  });

  it("event tới hai lần chỉ gọi REST một lần", async () => {
    // Không phải giả định: WS nối lại sẽ **replay** ring buffer (ADR-014), và
    // `approval.intent.detected` là event thật của stream nên nó nằm trong buffer.
    // Gọi lần hai trên một approval đã consume trả 409 và bắn toast lỗi cho tài xế,
    // dù chẳng có gì sai.
    const { phat } = await dungProvider();

    await act(async () => phat(Y_DINH_DONG_Y));
    await act(async () => phat(Y_DINH_DONG_Y));

    expect(turnService.decideApproval).toHaveBeenCalledTimes(1);
  });

  it("gửi hỏng thì cho phép thử lại — không khoá vĩnh viễn", async () => {
    // Khoá cứng sau lần hỏng đầu nghĩa là tài xế mất luôn cả đường bấm nút, trong khi
    // quyết định của họ chưa hề được ghi nhận.
    vi.mocked(turnService.decideApproval).mockRejectedValueOnce(new Error("mạng lỗi"));
    const { phat } = await dungProvider();

    await act(async () => phat(Y_DINH_DONG_Y));
    await act(async () => phat(Y_DINH_DONG_Y));

    expect(turnService.decideApproval).toHaveBeenCalledTimes(2);
  });

  it("câu mơ hồ không gọi gì — backend không phát intent nào", async () => {
    // Nhánh mơ hồ của backend phát `error(terminal)` + `turn.failed`, KHÔNG phát
    // `approval.intent.detected`. FE vì thế không được suy diễn gì thêm: hộp thoại
    // còn nguyên, và tài xế nói lại.
    const { phat } = await dungProvider();

    await act(async () =>
      phat({ type: "error", code: "APPROVAL_INTENT_AMBIGUOUS", message: "Tôi chưa rõ", retryable: true }),
    );

    expect(turnService.decideApproval).not.toHaveBeenCalled();
  });

  it("câu mơ hồ: hộp thoại còn nguyên sau CẢ turn.failed", async () => {
    // Test ngay trên đây khoá đúng một nửa và tự nhận là khoá cả hai: docstring của nó
    // ghi "hộp thoại còn nguyên", nhưng nó chỉ phát `error` rồi assert `decideApproval`
    // không được gọi. Nhánh mơ hồ thật phát **hai** event, và cái thứ hai —
    // `turn.failed` — mới là cái đóng hộp thoại.
    //
    // Vì sao đóng ở đây là sai chứ không chỉ xấu: lượt "trả lời phê duyệt" là một lượt
    // KHÁC với lượt tạo ra approval, nên nó kết thúc không có nghĩa approval kết thúc.
    // Phía server approval vẫn treo nguyên. Đóng hộp thoại là cắt mất đường duy nhất
    // để tài xế quyết — và vì mỗi phiên chỉ được một approval chờ
    // (`invalidate_orphaned_pending_approvals`, chỉ mục unique riêng phần của #46),
    // họ cũng không ra được lệnh S2 nào khác cho tới khi nó hết hạn 30 s.
    const { phat } = await dungProvider();

    await act(async () =>
      phat({
        type: "approval.required",
        turnId: "turn_goc",
        approvalId: "appr-123",
        planId: "plan-1",
        approvedVehicleStateVersion: 3,
        expiresAt: HET_HAN(),
      }),
    );
    expect(document.querySelector("[data-testid=cho-duyet]")?.textContent).toBe("appr-123");

    await act(async () =>
      phat({ type: "error", code: "APPROVAL_INTENT_AMBIGUOUS", message: "Tôi chưa rõ", retryable: true }),
    );
    await act(async () => phat({ type: "turn.failed", turnId: "turn_intent", code: "APPROVAL_INTENT_AMBIGUOUS" }));

    expect(document.querySelector("[data-testid=cho-duyet]")?.textContent).toBe("appr-123");
    expect(turnService.decideApproval).not.toHaveBeenCalled();
  });

  it("turn.failed vì lý do KHÁC vẫn đóng hộp thoại", async () => {
    // Bánh cóc cho chiều ngược lại. `turn.failed` được thêm vào nhánh dọn dẹp vì audio
    // rỗng làm voice overlay treo vĩnh viễn (xem chú thích tại chỗ) — sửa ca mơ hồ mà
    // làm hỏng ca ấy thì chỉ là đổi chỗ bug.
    const { phat } = await dungProvider();

    await act(async () =>
      phat({
        type: "approval.required",
        turnId: "turn_goc",
        approvalId: "appr-123",
        planId: "plan-1",
        approvedVehicleStateVersion: 3,
        expiresAt: HET_HAN(),
      }),
    );
    await act(async () => phat({ type: "turn.failed", turnId: "turn_goc", code: "STT_UNUSABLE" }));

    expect(document.querySelector("[data-testid=cho-duyet]")?.textContent).toBe("khong");
  });
});

/**
 * `committed` — ai chốt phê duyệt, và chuyện gì xảy ra khi không ai chốt (issue #207).
 *
 * #191 dựng ở BE một cổng **bất đối xứng**: mọi cụm từ chối đều được chốt, còn phía
 * chấp nhận chỉ cụm rõ ràng (`đồng ý`, `xác nhận`) mới chốt — đồng ý TRẦN (`ừ`,
 * `vâng`, `ok`) cố ý không, vì mấy tiếng ấy xuất hiện quá nhiều trong hội thoại
 * thường và nghe nhầm một tiếng "ừ" là xe tự làm một việc S2.
 *
 * Nhánh `case "approval.intent.detected"` viết từ #147 gọi REST cho **mọi** event,
 * nên nó chốt hộ đúng cái BE vừa từ chối chốt — cổng bất đối xứng thành trang trí.
 * Suite FE xanh suốt thời gian đó vì không test nào nhìn vào chuyện "ai chốt".
 */
describe("approval.intent.detected — ba trạng thái của `committed`", () => {
  beforeEach(() => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(PHIEN as never);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(TRANG_THAI_XE as never);
    vi.mocked(turnService.decideApproval).mockResolvedValue(undefined as never);
    vi.mocked(startWavRecording).mockResolvedValue({
      stop: vi.fn().mockResolvedValue(new Blob()),
      cancel: vi.fn(),
      hadSpeech: () => true,
    } as never);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  async function moPheDuyet(phat: (event: DriverEvent) => void) {
    await act(async () =>
      phat({
        type: "approval.required",
        turnId: "turn_goc",
        approvalId: "appr-123",
        planId: "plan-1",
        approvedVehicleStateVersion: 3,
        expiresAt: HET_HAN(),
      }),
    );
  }

  it("committed=true: KHÔNG gọi REST — backend chốt rồi", async () => {
    const { phat } = await dungProvider();
    await moPheDuyet(phat);

    await act(async () => phat({ ...Y_DINH_DONG_Y, committed: true }));

    expect(turnService.decideApproval).not.toHaveBeenCalled();
  });

  it("committed=false + approve: KHÔNG gọi REST, chuyển sang chờ chạm", async () => {
    // Đây là bài kiểm chính của #207. Gọi REST ở đây là chốt hộ đúng cái BE cố ý
    // không chốt, tức vô hiệu hoá toàn bộ phần an toàn của #191 từ phía client.
    const { phat } = await dungProvider();
    await moPheDuyet(phat);

    await act(async () => phat({ ...Y_DINH_DONG_Y, committed: false }));

    expect(turnService.decideApproval).not.toHaveBeenCalled();
    expect(document.querySelector("[data-testid=cho-cham]")?.textContent).toBe("co");
  });

  it("committed=false: turn.completed của lượt handoff KHÔNG được đóng hộp thoại", async () => {
    // Cùng lớp lỗi với ca "câu mơ hồ" mà #147 đã chặn, chỉ khác lối vào — và ca này
    // khó thấy hơn vì lượt handoff kết thúc **bình thường**: không mơ hồ, không lỗi,
    // `turn.completed` sạch sẽ. Nhưng backend chưa chốt gì, approval còn treo nguyên
    // ở server. Đóng hộp thoại là lấy nốt đường cuối để tài xế quyết, rồi khoá luôn
    // phiên khỏi mọi lệnh S2 khác cho tới lúc nó hết hạn (một pending mỗi phiên).
    const { phat } = await dungProvider();
    await moPheDuyet(phat);

    await act(async () => phat({ ...Y_DINH_DONG_Y, committed: false }));
    await act(async () => phat({ type: "turn.completed", turnId: "turn_intent" }));

    expect(document.querySelector("[data-testid=cho-duyet]")?.textContent).toBe("appr-123");
  });

  it("committed=false rồi chạm nút: gọi REST một lần, hộp thoại đóng lại được", async () => {
    // Chiều ngược của test trên. Cờ chờ-chạm phải hạ NGAY lúc chạm, không đợi event —
    // còn treo thì `turn.completed` của lượt lệnh gốc cũng bị giữ lại, và hộp thoại
    // đứng vĩnh viễn trên màn hình sau khi lệnh đã chạy xong.
    const { phat } = await dungProvider();
    await moPheDuyet(phat);
    await act(async () => phat({ ...Y_DINH_DONG_Y, committed: false }));

    await act(async () => document.querySelector<HTMLButtonElement>("[data-testid=nut-duyet]")?.click());

    expect(turnService.decideApproval).toHaveBeenCalledTimes(1);
    expect(turnService.decideApproval).toHaveBeenCalledWith("appr-123", "approve", 3);

    await act(async () => phat({ type: "turn.completed", turnId: "turn_goc" }));
    expect(document.querySelector("[data-testid=cho-duyet]")?.textContent).toBe("khong");
  });

  it("committed=undefined: giữ nguyên hành vi #147 — FE vẫn gọi REST", async () => {
    // Đường lui theo phiên bản, không phải code chết: phần BE của #207 chưa merge.
    // Không có nhánh này thì thứ tự merge quyết định hành vi — FE vào trước là lời
    // đồng ý trần rơi vào khoảng trống (không ai chốt) trong khi xe vừa đọc "Tôi sẽ
    // thực hiện ngay". Xoá test này cùng lúc xoá nhánh ấy, sau khi BE đã vào develop.
    const { phat } = await dungProvider();
    await moPheDuyet(phat);

    await act(async () => phat(Y_DINH_DONG_Y));

    expect(turnService.decideApproval).toHaveBeenCalledWith("appr-123", "approve", 3);
  });

  it("committed=false + reject vẫn gọi REST — từ chối là kết quả an toàn", async () => {
    // Cặp này BE không sinh ra (mọi cụm từ chối đều được chốt), nhưng nếu nó xuất hiện
    // thật thì bỏ qua sẽ để một lời từ chối rơi mất. Từ chối vốn đã là kết quả mặc
    // định khi phê duyệt hết hạn, nên gọi thừa ở đây không mất gì.
    const { phat } = await dungProvider();
    await moPheDuyet(phat);

    await act(async () => phat({ ...Y_DINH_DONG_Y, decision: "reject", committed: false }));

    expect(turnService.decideApproval).toHaveBeenCalledWith("appr-123", "reject", 3);
  });
});
