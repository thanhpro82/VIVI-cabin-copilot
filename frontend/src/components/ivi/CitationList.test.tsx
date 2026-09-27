// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CitationList } from "./CitationList";
import type { Citation } from "@/lib/services/turn/types";

function citation(id: string, page: number): Citation {
  return {
    citationId: id,
    documentTitle: "Sổ tay VF9",
    section: `Mục ${id}`,
    page,
    excerpt: `Nội dung nguyên văn của ${id}`,
  };
}

const ONE = [citation("c1", 42)];

afterEach(cleanup);

describe("CitationList", () => {
  it("không có trích dẫn thì không chiếm chỗ nào", () => {
    // `jest-dom` không được cài trong repo này nên không có toBeEmptyDOMElement.
    const { container } = render(<CitationList citations={[]} allowDetailed maxVisible={3} />);
    expect(container.innerHTML).toBe("");
  });

  /**
   * Cờ `allowDetailedDocumentBrowsing` chặn TRÌNH XEM CHI TIẾT, không chặn sự
   * tồn tại của trích dẫn (`user_experience.md:87`). Ẩn hẳn nguồn khi đang chạy
   * sẽ khiến câu trả lời sổ tay trông như không có căn cứ.
   */
  it("đang chạy (cờ tắt): vẫn hiện nguồn + số trang, nhưng không bung được", () => {
    render(<CitationList citations={ONE} allowDetailed={false} maxVisible={3} />);

    expect(screen.getByText(/Sổ tay VF9/)).toBeDefined();
    expect(screen.getByText(/tr\. 42/)).toBeDefined();
    expect(screen.getByRole("button")).toHaveProperty("disabled", true);
    expect(screen.queryByText(/Nội dung nguyên văn/)).toBeNull();
  });

  it("đứng yên (cờ bật): chạm vào bung đoạn trích nguyên văn, chạm lại thì gập", () => {
    render(<CitationList citations={ONE} allowDetailed maxVisible={3} />);
    const toggle = screen.getByRole("button");

    expect(screen.queryByText(/Nội dung nguyên văn/)).toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByText(/Nội dung nguyên văn của c1/)).toBeDefined();
    fireEvent.click(toggle);
    expect(screen.queryByText(/Nội dung nguyên văn/)).toBeNull();
  });

  it("maxVisibleActions giới hạn số nguồn hiện cùng lúc, phần dư được đếm", () => {
    const many = [citation("c1", 1), citation("c2", 2), citation("c3", 3), citation("c4", 4), citation("c5", 5)];
    render(<CitationList citations={many} allowDetailed maxVisible={3} />);

    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(screen.getByText("+2 nguồn khác")).toBeDefined();
  });

  /**
   * Hợp đồng giới hạn `max_visible_actions` trong 1..3, nhưng backend có thể
   * đổi và FE không được vì thế mà hiện SỐ KHÔNG nguồn — mất trắng phần căn cứ
   * còn tệ hơn hiện thừa một dòng.
   */
  it("maxVisible = 0 vẫn hiện ít nhất một nguồn", () => {
    render(<CitationList citations={ONE} allowDetailed maxVisible={0} />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });
});
