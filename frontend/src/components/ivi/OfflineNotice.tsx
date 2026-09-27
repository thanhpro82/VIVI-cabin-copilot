"use client";

/**
 * Chỗ giữ chỗ cho các app cần mạng, dùng ở chế độ demo offline (issue #176).
 *
 * Vì sao cần: `youtube.com/embed`, `open.spotify.com/embed` và `i.ytimg.com` là
 * ba trong sáu host ngoài mà IVI gọi lúc chạy. Rút dây mạng ra thì ba màn ấy
 * **trắng trơn** — người xem không biết là hỏng, là đang tải, hay là chưa làm.
 *
 * Vẽ hoàn toàn bằng CSS và SVG nội tuyến, cố ý không dùng file ảnh: một chỗ giữ
 * chỗ mà lại phải tải ảnh về là tự mâu thuẫn.
 *
 * Nội dung ghi rõ **giới hạn của bản demo**, không giả vờ là lỗi mạng của người
 * dùng — họ không bật được thứ gì để sửa nó.
 */
export function OfflineNotice({ appName }: { appName: string }) {
  return (
    <div
      role="status"
      className="flex h-full flex-col items-center justify-center gap-4 rounded-(--r-md) border border-line bg-panel-solid p-8 text-center"
    >
      <svg
        width="44"
        height="44"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        aria-hidden
        className="text-ink-dim"
      >
        <path d="M2 8.5a15 15 0 0 1 20 0" />
        <path d="M5 12.5a10 10 0 0 1 14 0" />
        <path d="M8.5 16a5 5 0 0 1 7 0" />
        <circle cx="12" cy="19.5" r="0.6" fill="currentColor" />
        <path d="M3 3l18 18" strokeWidth="1.8" />
      </svg>

      <div>
        <p className="font-display text-[15px] font-semibold text-ink">{appName} cần kết nối mạng</p>
        <p className="mt-1.5 max-w-80 text-xs leading-relaxed text-ink-soft">
          Bản demo đang chạy ở chế độ offline. Điều khiển xe, tra sổ tay, nhạc và bản đồ vẫn hoạt
          động bình thường — chỉ nội dung của {appName} là không tải được.
        </p>
      </div>
    </div>
  );
}
