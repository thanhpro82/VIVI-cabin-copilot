"use client";

import { useEngineerShell } from "./EngineerShellProvider";

const STATUS_COLOR: Record<string, string> = {
  completed: "text-ink",
  failed: "text-accent",
  canceled: "text-amber",
};

const APPROVAL_COLOR: Record<string, string> = {
  approved: "text-cyan",
  rejected: "text-accent",
  expired: "text-amber",
};

const APPROVAL_LABEL: Record<string, string> = {
  approved: "Đã đồng ý",
  rejected: "Từ chối",
  expired: "Hết giờ",
};

const STATUS_LABEL: Record<string, string> = {
  completed: "Xong",
  failed: "Thất bại",
  canceled: "Đã huỷ",
};

/**
 * Ring buffer log realtime từ /ws/engineer — KHÔNG phải historical viewer, xem
 * docs/ARCHITECTURE.md mục 6.1.
 *
 * `answerText` là câu VIVI trả lời (ADR-029). Nó do server sinh nên hiện được ở
 * đây; câu nói của tài xế thì không, và backend cũng không lưu.
 */
export function LogsTable() {
  const { filteredLogs } = useEngineerShell();

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-(--r-md) border border-line bg-panel-solid">
      <p className="border-b border-line px-4 py-2 font-technical text-[10px] text-ink-dim">
        Nhật ký từ khi mở phiên làm việc — tối đa 200 dòng gần nhất
      </p>
      <div className="grid grid-cols-[90px_1fr_110px_100px_90px_80px] gap-2 border-b border-line bg-(--panel) px-4 py-2 font-technical text-[9.5px] tracking-wide text-ink-dim uppercase">
        <span>Giờ</span>
        <span>Tóm tắt / Trả lời</span>
        <span>Nguồn</span>
        <span>Xác nhận</span>
        <span>Trạng thái</span>
        <span className="text-right">Độ trễ</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {filteredLogs.length === 0 ? (
          <p className="p-4 text-sm text-ink-dim">Chưa có lượt hội thoại nào trong phiên này.</p>
        ) : (
          filteredLogs.map((entry) => (
            <div
              key={entry.traceId}
              className={`grid grid-cols-[90px_1fr_110px_100px_90px_80px] gap-2 border-b border-line-soft px-4 py-2 text-[11.5px] ${
                entry.status === "failed" ? "bg-accent/5" : ""
              }`}
            >
              <span className="font-technical text-ink-soft">{entry.time}</span>
              {/*
                Câu trả lời xếp dưới tóm tắt thay vì thành cột thứ bảy: bảng đã có
                sáu cột ở 11.5px, thêm một cột `1fr` nữa thì cả hai cột chữ đều cụt.
                Xếp chồng đọc đúng thứ tự cần đọc — "lượt này làm gì" rồi "nó đã
                nói gì" — và giữ nguyên lưới.
              */}
              <span className="min-w-0">
                <span className="block truncate text-ink" title={entry.safeSummary}>
                  {entry.safeSummary}
                </span>
                {entry.answerText ? (
                  <span className="block truncate text-[10.5px] text-ink-dim" title={entry.answerText}>
                    {entry.answerText}
                  </span>
                ) : null}
              </span>
              <span className="text-ink-soft">{entry.routeSource ?? "—"}</span>
              <span className={entry.approvalStatus ? (APPROVAL_COLOR[entry.approvalStatus] ?? "text-ink-soft") : "text-ink-dim"}>
                {entry.approvalStatus ? (APPROVAL_LABEL[entry.approvalStatus] ?? entry.approvalStatus) : "—"}
              </span>
              <span className={STATUS_COLOR[entry.status] ?? "text-ink-soft"}>
                {STATUS_LABEL[entry.status] ?? entry.status}
              </span>
              <span className="text-right font-technical text-ink-soft">
                {entry.latencyMs != null ? `${entry.latencyMs}ms` : "—"}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
