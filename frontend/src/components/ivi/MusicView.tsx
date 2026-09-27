"use client";

import { findTrack } from "@/lib/fixtures/media";
import { trackCoverGradient } from "@/lib/ivi/trackCover";
import { useDriverShell } from "./DriverShellProvider";

export function MusicView() {
  const { vehicleState, send } = useDriverShell();
  const playing = vehicleState?.media.status === "playing";
  const volume = vehicleState?.media.volume ?? 0;
  const track = vehicleState?.media.track;
  // Không có trường `muted` trong hợp đồng (`MediaState` chỉ có status/volume/track),
  // nên "đã tắt tiếng" chỉ suy ra được từ mức 0 — xem `_match_media_mute` bên router.
  const muted = volume === 0;
  // Tra thẳng trong fixture, KHÔNG rơi về bài đầu tiên khi trượt: backend và
  // fixture đọc chung một file nên trượt nghĩa là hai bên đã lệch nguồn, và im
  // lặng phát bừa một bài khác là đúng cách bug cũ ẩn mình (issue #173).
  const meta = findTrack(track);

  return (
    <div className="relative flex h-full flex-col items-center justify-center gap-6 overflow-hidden rounded-(--r-lg) border border-line p-8">
      {/* Bìa sinh bằng code, không phải file ảnh (@thanhpro82 chốt ở #188).
          Gradient dựng từ token có sẵn nên không thêm hex mới, và cả sáu bìa ở
          trong họ `--violet` — token dành riêng cho nhạc — nên không bài nào
          đọc nhầm thành cảnh báo hay thành TikTok. Xem lib/ivi/trackCover.ts. */}
      {meta && (
        <div
          aria-hidden
          className="absolute inset-0 opacity-35 blur-2xl transition-opacity duration-700"
          style={{ background: trackCoverGradient(meta.id) }}
        />
      )}
      <div
        aria-hidden
        className="absolute inset-0 bg-panel-solid/80"
        style={{ background: "radial-gradient(ellipse 700px 500px at 50% 30%, transparent, var(--panel-solid) 85%)" }}
      />

      <div
        className="relative flex h-43 w-43 items-center justify-center rounded-(--r-md) border border-line text-5xl text-ink backdrop-blur-sm"
        style={meta ? { background: trackCoverGradient(meta.id) } : undefined}
      >
        ♪
      </div>
      <div className="relative text-center">
        {/* Nhãn theo TRẠNG THÁI PHÁT, không hard-code "Đang phát" — trước đây
            nhãn này luôn hiện "Đang phát" bất kể `playing`, trong khi dòng bên
            dưới lật thành "Tắt" và nút play hiện ▶ (issue #226 B1). Ba tín
            hiệu mâu thuẫn trên cùng một khung. Tên bài giờ LUÔN hiện, không
            biến mất khi tạm dừng — bài hát không "biến mất" chỉ vì đang dừng,
            đúng cách `meta.attribution` bên dưới vốn đã cư xử (không phụ
            thuộc `playing`).

            `đã tắt tiếng` là nhánh thứ tư, thêm cùng lệnh thoại "tắt tiếng"
            (#320). Nó bắt buộc chứ không phải trang trí: `set_volume: 0` giữ
            nguyên `status: playing`, nên không có nhãn này thì màn hình nói
            "Đang phát" trong lúc loa im — đúng loại mâu thuẫn mà #226 B1 vừa
            dọn, chỉ khác nguồn. Người test báo lỗi là chuyện chắc chắn xảy ra,
            và họ sẽ đúng. */}
        <p className="font-technical text-[10px] uppercase tracking-widest text-ink-dim">
          {track ? (playing ? (muted ? "Đang phát · đã tắt tiếng" : "Đang phát") : "Đã dừng") : "Chưa có bài nào"}
        </p>
        <p className="mt-1 font-display text-2xl font-semibold text-ink">
          {track ?? "Chưa có bài nào"}
        </p>
        {/* Ghi công là ĐIỀU KIỆN của CC BY 4.0, không phải trang trí — playlist
            lấy từ incompetech.com, xem frontend/public/media/LICENSE.md. */}
        {meta && (
          <p className="mt-1 text-[10px] text-ink-dim">{meta.attribution}</p>
        )}
      </div>

      <div className="relative flex items-center gap-5">
        <button
          type="button"
          // `previous` CÓ route thật từ issue #65: `_match_music`
          // (src/agents/router.py:758) khớp cụm bài-trước và cố ý xét TRƯỚC
          // `next`, vì cả hai cùng mở đầu bằng "chuyển". Comment cũ ở đây nói
          // ngược lại — nó viết 2026-08-11, trước khi luật ấy được thêm.
          onClick={() => send("bài trước")}
          title="Bài trước"
          className="flex h-10 w-10 items-center justify-center rounded-full border border-line text-base text-ink-soft hover:border-violet hover:text-violet"
        >
          ⏮
        </button>
        <button
          type="button"
          // Router thật đòi "tạm dừng"/"dừng" để pause — "tắt nhạc" không
          // khớp nhánh nào cả (Assistant._match_music), xác nhận 2026-08-11.
          onClick={() => send(playing ? "dừng nhạc" : "bật nhạc")}
          className="flex h-14 w-14 items-center justify-center rounded-full border border-violet/60 text-xl text-violet hover:shadow-[0_0_0_8px_rgba(139,124,246,0.12)]"
        >
          {playing ? "⏸" : "▶"}
        </button>
        <button
          type="button"
          // Router đòi câu bắt đầu bằng "chuyển"/"tiếp" và chứa "nhạc" HOẶC
          // "bài" — issue #65 thêm "bài" làm từ khoá miền (router.py:751).
          onClick={() => send("chuyển bài nhạc")}
          title="Bài tiếp theo"
          className="flex h-10 w-10 items-center justify-center rounded-full border border-line text-base text-ink-soft hover:border-violet hover:text-violet"
        >
          ⏭
        </button>
      </div>

      <div className="relative flex w-full max-w-105 items-center justify-center gap-3">
        <span className="w-16 text-xs text-ink-soft">Âm lượng</span>
        <button
          type="button"
          // Router thật (Assistant._match_music, nhánh "âm lượng") đọc số
          // tuyệt đối qua _number(text) — không có "giảm 1 nấc" như mock,
          // luôn cần tính sẵn mục tiêu rồi gửi kèm số, xác nhận 2026-08-11.
          onClick={() => send(`chỉnh âm lượng ${Math.max(0, volume - 10)}`)}
          className="flex h-8 w-8 items-center justify-center rounded-(--r-sm) border border-line text-ink hover:border-violet"
        >
          −
        </button>
        <div className="h-[5px] flex-1 rounded-full bg-line">
          <div className="h-full rounded-full bg-violet" style={{ width: `${volume}%` }} />
        </div>
        <button
          type="button"
          onClick={() => send(`chỉnh âm lượng ${Math.min(100, volume + 10)}`)}
          className="flex h-8 w-8 items-center justify-center rounded-(--r-sm) border border-line text-ink hover:border-violet"
        >
          +
        </button>
        <span className="w-8 text-right font-technical text-xs text-ink-soft">{volume}</span>
      </div>
    </div>
  );
}
