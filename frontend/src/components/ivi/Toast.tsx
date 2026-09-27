"use client";

import { useDriverShell } from "./DriverShellProvider";

/** Phản hồi tức thì cho mọi lệnh gửi qua turnService.sendText/sendVoice — không phụ thuộc voice overlay có mở hay không, giải quyết cảm giác "đứng hình" khi mock có độ trễ giả lập ~0.7-1.5s. */
export function Toast() {
  const { toast, pendingApproval } = useDriverShell();

  if (!toast || pendingApproval) return null;

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-24 z-30 flex justify-center px-4">
      <div className="max-w-md rounded-full border border-line bg-panel-solid/95 px-4 py-2 text-center text-[13px] text-ink shadow-lg backdrop-blur-sm">
        {toast}
      </div>
    </div>
  );
}
