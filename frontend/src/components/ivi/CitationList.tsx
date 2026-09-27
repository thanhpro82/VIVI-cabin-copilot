"use client";

import { useState } from "react";
import type { Citation } from "@/lib/services/turn/types";

interface CitationListProps {
  citations: Citation[];
  /**
   * `ui.policy.allow_detailed_document_browsing` do backend tính. FE **không**
   * được tự suy từ tốc độ (`docs/technical_spec.md:74`) — nhận qua props để
   * component này thuần trình bày, giống `Car3DViewer`.
   */
  allowDetailed: boolean;
  /** Số nguồn hiển thị tối đa; phần dư gộp thành "+N nguồn khác". */
  maxVisible: number;
}

/**
 * Nguồn sổ tay của câu trả lời vừa rồi.
 *
 * Đây là consumer UI đầu tiên của `allowDetailedDocumentBrowsing` (issue #111).
 * Cờ này **không** quyết định có hiện nguồn hay không — nó quyết định hiện tới
 * mức nào:
 *
 * - Đang chạy (`false`): chỉ một dòng tên tài liệu + số trang, không bung được.
 *   Tài xế vẫn biết câu trả lời có căn cứ và tra lại được sau, nhưng không có gì
 *   mời họ đọc một đoạn văn dài trong lúc lái.
 * - Đứng yên (`true`): chạm vào để bung đoạn trích nguyên văn.
 *
 * Bỏ hẳn phần nguồn khi đang chạy sẽ là hiểu sai cờ này: `user_experience.md:87`
 * nói "manual citation viewer ... may be shown when backend policy allows", tức
 * cái bị chặn là **trình xem chi tiết**, không phải sự tồn tại của trích dẫn.
 */
export function CitationList({ citations, allowDetailed, maxVisible }: CitationListProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (citations.length === 0) return null;

  const visible = citations.slice(0, Math.max(1, maxVisible));
  const hiddenCount = citations.length - visible.length;

  return (
    <div className="mt-3 border-t border-line pt-2.5">
      <p className="font-technical text-[10px] tracking-widest text-ink-dim uppercase">Nguồn sổ tay xe</p>
      <ul className="mt-1.5 flex flex-col gap-1">
        {visible.map((citation) => {
          const expanded = expandedId === citation.citationId;
          return (
            <li key={citation.citationId}>
              <button
                type="button"
                disabled={!allowDetailed}
                aria-expanded={allowDetailed ? expanded : undefined}
                onClick={() => setExpandedId(expanded ? null : citation.citationId)}
                className={`w-full text-left text-[11.5px] leading-snug text-ink-soft ${
                  allowDetailed ? "hover:text-ink" : "cursor-default"
                }`}
              >
                <span className="text-ink">{citation.section}</span>
                <span className="text-ink-dim">
                  {" "}
                  · {citation.documentTitle} · tr. {citation.page}
                  {allowDetailed && (expanded ? " ▴" : " ▾")}
                </span>
              </button>
              {allowDetailed && expanded && (
                <p className="mt-1 border-l-2 border-line pl-2.5 text-[11.5px] leading-relaxed text-ink-soft">
                  {citation.excerpt}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {hiddenCount > 0 && (
        <p className="mt-1 font-technical text-[10px] text-ink-dim">+{hiddenCount} nguồn khác</p>
      )}
    </div>
  );
}
