// @vitest-environment jsdom
/**
 * `HitlModal` giờ có chỉ báo "đang nghe" khi mic tự bật (xem
 * DriverShellProvider.autoListenApproval.test.tsx) — `VoiceOverlay` tự ẩn
 * lúc có `pendingApproval` (effectiveVoiceOpen = voiceOpen && !pendingApproval),
 * nên nếu không có gì ở đây, tài xế không biết mic đã tự ghi, dù nó đang ghi
 * thật.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HitlModal } from "./HitlModal";

const shell = {
  pendingApproval: null as { approvalId: string; summary: string | null; expiresAt?: string } | null,
  approve: vi.fn(),
  reject: vi.fn(),
  uiPolicy: { preferVoiceConfirmation: true },
  recording: false,
  approvalNeedsTap: false,
};

vi.mock("./DriverShellProvider", () => ({
  useDriverShell: () => shell,
}));

describe("HitlModal — chỉ báo đang nghe khi mic tự bật", () => {
  afterEach(() => {
    cleanup();
    shell.pendingApproval = null;
    shell.recording = false;
    shell.approvalNeedsTap = false;
  });

  it("không có approval đang chờ thì không render gì", () => {
    const { container } = render(<HitlModal />);
    expect(container.textContent).toBe("");
  });

  it("có approval nhưng chưa ghi thì hiện lời mời nói, không hiện 'đang nghe'", () => {
    shell.pendingApproval = { approvalId: "appr-1", summary: "mở cửa trước bên lái" };
    shell.recording = false;

    render(<HitlModal />);

    expect(screen.getByText(/Nói "đồng ý"/)).toBeTruthy();
    expect(screen.queryByText(/Đang nghe/)).toBeNull();
  });

  it("đang ghi (mic tự bật) thì hiện 'Đang nghe'", () => {
    shell.pendingApproval = { approvalId: "appr-1", summary: "mở cửa trước bên lái" };
    shell.recording = true;

    render(<HitlModal />);

    expect(screen.getByText(/Đang nghe/)).toBeTruthy();
  });
});

/**
 * Chờ chạm xác nhận — tài xế đồng ý bằng lời TRẦN ("ừ"), backend cố ý không chốt
 * (#191), nên hộp thoại phải nói rõ còn thiếu gì và làm nổi nút (issue #207).
 */
describe("HitlModal — chờ chạm khi đồng ý bằng lời trần", () => {
  afterEach(() => {
    cleanup();
    shell.pendingApproval = null;
    shell.recording = false;
    shell.approvalNeedsTap = false;
  });

  it("nói rõ còn thiếu một cụm dứt khoát hoặc một cú chạm", () => {
    shell.pendingApproval = { approvalId: "appr-1", summary: "mở cửa trước bên lái" };
    shell.approvalNeedsTap = true;

    render(<HitlModal />);

    expect(screen.getByText(/Đã nghe bạn đồng ý/)).toBeTruthy();
  });

  it("thắng cả chỉ báo 'Đang nghe'", () => {
    // Tài xế vừa nói "ừ" và hệ thống NGHE ĐÚNG. Hiện "Đang nghe — nói đồng ý" lúc này
    // là nói với người vừa nói xong rằng máy không nghe thấy gì: sai sự thật, và đẩy
    // họ nói to hơn thay vì chạm — đúng thứ duy nhất còn lại để đi tiếp.
    shell.pendingApproval = { approvalId: "appr-1", summary: "mở cửa trước bên lái" };
    shell.recording = true;
    shell.approvalNeedsTap = true;

    render(<HitlModal />);

    expect(screen.getByText(/Đã nghe bạn đồng ý/)).toBeTruthy();
    expect(screen.queryByText(/Đang nghe/)).toBeNull();
  });

  it("làm nổi nút Đồng ý, và chỉ khi đang chờ chạm", () => {
    shell.pendingApproval = { approvalId: "appr-1", summary: "mở cửa trước bên lái" };
    shell.approvalNeedsTap = true;
    render(<HitlModal />);
    expect(screen.getByRole("button", { name: "Đồng ý" }).className).toContain("ring-2");

    // Bánh cóc: vòng nhấn phải VẮNG ở trạng thái thường, không thì nó chẳng phân biệt
    // được gì và mọi lượt S2 đều trông như đang chờ tài xế chạm.
    cleanup();
    shell.approvalNeedsTap = false;
    render(<HitlModal />);
    expect(screen.getByRole("button", { name: "Đồng ý" }).className).not.toContain("ring-2");
  });
});
