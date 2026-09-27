"use client";

import { useEffect, useState } from "react";
import { useDriverShell } from "./DriverShellProvider";

const RING_RADIUS = 28;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

/** Đường lui khi chưa đo được tổng thời gian — bằng `hitl_timeout_seconds` của server. */
const TONG_MAC_DINH_MS = 30_000;

/**
 * Đếm ngược tới `expires_at`, và **tự đo lấy tổng** thay vì tin một hằng số.
 *
 * Bản trước chia cho `totalMs = 15000` trong khi server cho 30 giây
 * (`hitl_timeout_seconds`, `src/config.py`). Hệ quả không phải sai số làm đẹp: vòng
 * tròn cạn sạch ở giây thứ 15 rồi nằm im ở 0 suốt 15 giây còn lại, nên hộp thoại
 * **trông như đã chết** trong đúng nửa quãng thời gian nó vẫn bấm được. Đổi TTL ở
 * server mà quên sửa hằng số này thì lỗi ấy quay lại y nguyên.
 *
 * Tổng đo một lần cho mỗi phê duyệt (`expiresAt` đổi thì đo lại) chứ không đo mỗi
 * tick: đo mỗi tick thì `progress` luôn bằng 1 và vòng tròn đứng yên.
 */
function useCountdown(expiresAt: string | undefined) {
  // Một state cho cả hai, và tổng đo ở **lần tick đầu** trong closure của effect.
  //
  // Không đo lúc render (`Date.now()` là hàm không thuần — React Compiler chặn), cũng
  // không để tổng ở ref (đọc ref lúc render cũng bị chặn). Đo trong `tick` là chỗ duy
  // nhất còn lại mà vẫn đúng ngữ nghĩa "đo một lần cho mỗi phê duyệt".
  const [dong, setDong] = useState({ remainingMs: TONG_MAC_DINH_MS, totalMs: TONG_MAC_DINH_MS });
  useEffect(() => {
    if (!expiresAt) return;
    const expiresAtMs = new Date(expiresAt).getTime();
    let tong = 0;
    const tick = () => {
      const conLai = Math.max(0, expiresAtMs - Date.now());
      // Kẹp sàn 1 giây: đồng hồ máy lệch về phía trước có thể cho ra tổng 0, và một
      // mẫu số 0 làm vòng tròn nhảy loạn thay vì cạn dần.
      if (!tong) tong = Math.max(1000, conLai);
      setDong({ remainingMs: conLai, totalMs: tong });
    };
    tick();
    const timer = setInterval(tick, 200);
    return () => clearInterval(timer);
  }, [expiresAt]);
  return dong;
}

/** HITL modal — ADR-006 S2 (cần duyệt), nối approval.required/decideApproval qua DriverShellProvider. */
export function HitlModal() {
  const { pendingApproval, approve, reject, uiPolicy, recording, approvalNeedsTap } = useDriverShell();
  const { remainingMs, totalMs } = useCountdown(pendingApproval?.expiresAt);
  const secondsLeft = Math.ceil(remainingMs / 1000);
  const progress = Math.min(1, remainingMs / totalMs);

  if (!pendingApproval) return null;

  return (
    // Dải trên, KHÔNG `inset-0`, KHÔNG backdrop che toàn màn (#147, phương án (b) của
    // @thanhpro82). Bản trước là `absolute inset-0 z-50` có backdrop và bên trong chỉ
    // có hai nút — nên khi hộp thoại lên thì **không bấm được mic để mà nói**. Trong
    // một sản phẩm voice-first, đó là chặn đúng đường mà `ui.policy` ưu tiên:
    // `preferVoiceConfirmation` và `enlargeMicButton` tồn tại chính cho lúc đang lái.
    //
    // `pointer-events-none` ở lớp ngoài + `pointer-events-auto` ở thẻ: vùng trống
    // quanh dải không nuốt cú chạm, nên Dock và nút mic ở dưới vẫn bấm được.
    <div className="pointer-events-none absolute inset-x-0 top-4 z-50 flex justify-center px-4">
      <div className="pointer-events-auto w-full max-w-md rounded-[var(--r-lg)] border border-accent/60 bg-panel-solid p-6 shadow-2xl">
        <p className="flex items-center gap-2 font-display text-sm font-semibold text-accent">
          <span>●</span> Lệnh điều khiển vật lý
        </p>
        <div className="mt-4 flex items-center gap-4">
          <div className="relative h-16 w-16 shrink-0">
            <svg width="64" height="64" viewBox="0 0 64 64" className="-rotate-90">
              <circle cx="32" cy="32" r={RING_RADIUS} fill="none" stroke="var(--line)" strokeWidth="5" />
              <circle
                cx="32"
                cy="32"
                r={RING_RADIUS}
                fill="none"
                stroke="var(--accent)"
                strokeWidth="5"
                strokeDasharray={RING_CIRCUMFERENCE}
                strokeDashoffset={RING_CIRCUMFERENCE * (1 - progress)}
                style={{ transition: "stroke-dashoffset 200ms linear" }}
              />
            </svg>
            <span className="absolute inset-0 flex items-center justify-center font-technical text-lg font-semibold text-ink">
              {secondsLeft}
            </span>
          </div>
          <p className="text-sm leading-relaxed text-ink">
            Bạn xác nhận: <span className="font-semibold">{pendingApproval.summary}</span>?
          </p>
        </div>
        {/* Ba trạng thái, xét theo thứ tự "cái nào đang chờ tài xế nhất".
            `approvalNeedsTap` thắng cả `recording`: tài xế vừa nói "ừ" và hệ thống
            NGHE ĐÚNG — nhắc lại "hãy nói đồng ý" lúc này là nói với người vừa nói
            xong rằng máy không nghe thấy gì, sai sự thật và làm họ nói to hơn thay
            vì chạm. Cũng không đặt ngoài `preferVoiceConfirmation`: nhánh này chỉ
            phát sinh từ một lượt trả lời BẰNG LỜI, mà lời chỉ được mời khi cờ ấy bật. */}
        {uiPolicy.preferVoiceConfirmation &&
          (approvalNeedsTap ? (
            // KHÔNG dùng giọng cảnh báo (đỏ/"lỗi"): không có gì hỏng cả. #191 cố ý
            // không chốt lời đồng ý trần vì `ừ`/`vâng`/`ok` xuất hiện quá nhiều trong
            // hội thoại thường, chứ không phải vì máy nghe không rõ. Câu chữ phải nói
            // đúng thứ còn thiếu — một cụm dứt khoát, hoặc một cú chạm.
            <p className="mt-3 text-xs font-semibold text-accent">
              Đã nghe bạn đồng ý. Lệnh này cần xác nhận dứt khoát — nói &quot;xác nhận&quot; hoặc chạm nút
              &quot;Đồng ý&quot;.
            </p>
          ) : recording ? (
            // Mic tự bật ngay khi hộp thoại này hiện (xem effect trong
            // DriverShellProvider.tsx, "hạn chế bấm nút hết cỡ") — VoiceOverlay
            // tự ẩn lúc có pendingApproval nên đây là DẤU HIỆU DUY NHẤT tài xế
            // thấy được là mic đang thật sự ghi, không phải chỉ hứa suông.
            <p className="mt-3 flex items-center gap-1.5 text-xs font-semibold text-accent">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden />
              Đang nghe — nói &quot;đồng ý&quot; hoặc &quot;từ chối&quot;.
            </p>
          ) : (
            // Từ #147 đây KHÔNG còn là gợi ý suông: nói "đồng ý" chạy thật, qua
            // `approval.intent.detected` -> `decideApproval`. Chú thích cũ ("chưa có
            // voice-approval thật... voice input hiện chỉ gửi Blob rỗng") đã lạc hậu hai
            // lần — recorder thật vào ở PR #91/#99, còn nhánh phê duyệt vào ở #142.
            <p className="mt-3 text-xs text-ink-dim">Nói &quot;đồng ý&quot; hoặc chạm nút bên dưới để xác nhận.</p>
          ))}
        <div className="mt-5 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={reject}
            className="rounded-[var(--r-sm)] border border-line px-4 py-2 font-display text-sm font-semibold text-ink-soft hover:text-ink"
          >
            Từ chối
          </button>
          <button
            type="button"
            onClick={approve}
            // Vòng nhấn khi đang chờ chạm — `ring` chứ không đổi màu nền: nút này đã
            // là nút nổi bật sẵn (`bg-accent`), đổi nền nữa thì không còn bậc tương
            // phản nào để "nổi hơn". Ring trắng chứ không `ring-accent`: vòng cùng
            // màu với nền nút thì không thấy gì. Cũng KHÔNG `ring-offset-*` — token
            // `--panel-solid` trong suốt 40% nên khoảng offset sẽ để lộ chính màu
            // accent bên dưới, tức lại về đúng ca vòng-trùng-nền.
            className={`rounded-[var(--r-sm)] bg-accent px-4 py-2 font-display text-sm font-semibold text-white${
              approvalNeedsTap ? " ring-2 ring-white/80" : ""
            }`}
          >
            Đồng ý
          </button>
        </div>
      </div>
    </div>
  );
}
