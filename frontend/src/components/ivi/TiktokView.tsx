"use client";

import { useState } from "react";
import { OFFLINE_ASSETS } from "@/lib/assets";
import { OfflineNotice } from "./OfflineNotice";

/**
 * Giữ mock tĩnh vĩnh viễn (không có embed feed phù hợp, rủi ro ToS) — quyết
 * định đã chốt, không phải "chưa làm" (docs/ARCHITECTURE.md mục 7). Dùng ảnh
 * thumbnail thật (chỉ là ảnh JPEG tĩnh, không phải player) để trông sống
 * động hơn emoji — không nhúng iframe nên không lộ logo/watermark YouTube.
 */
const POSTS = [
  { thumbId: "aqz-KE-bpKQ", user: "@vivi.official", caption: "Một ngày cùng VIVI Cabin Copilot 🚗⚡ #EV", likes: "12.4k" },
  { thumbId: "jNQXAC9IVRw", user: "@evdaily.vn", caption: "5 mẹo tiết kiệm pin khi lái xe điện 🔋", likes: "8.7k" },
  { thumbId: "9bZkp7q19f0", user: "@roadtrip.vn", caption: "Cung đường đẹp nhất miền Trung 🌄", likes: "21.9k" },
];

export function TiktokView() {
  const [index, setIndex] = useState(0);
  const post = POSTS[index];

  function go(delta: number) {
    setIndex((i) => (i + delta + POSTS.length) % POSTS.length);
  }

  // Đặt SAU mọi hook: `OFFLINE_ASSETS` là hằng số lúc build nên không đổi
  // giữa các lần render, nhưng return sớm trước hook vẫn vi phạm rules-of-hooks.
  if (OFFLINE_ASSETS) return <OfflineNotice appName="TikTok" />;

  return (
    <div className="flex h-full items-stretch justify-center gap-3">
      <div className="relative h-full w-[60%] max-w-100 overflow-hidden rounded-[28px] border border-line bg-black">
        <img
          key={post.thumbId}
          src={`https://i.ytimg.com/vi/${post.thumbId}/hqdefault.jpg`}
          alt={post.caption}
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{ background: "linear-gradient(180deg, rgba(0,0,0,.2) 0%, transparent 35%, rgba(0,0,0,.75) 100%)" }}
        />
        <div className="absolute right-15 bottom-5 left-3.5 text-[12px] leading-relaxed text-white">
          <p className="mb-1 font-display text-[13px] font-bold">{post.user}</p>
          {post.caption}
        </div>
        <div className="absolute right-2.5 bottom-5 flex flex-col items-center gap-4">
          {[
            { icon: "♥", label: post.likes },
            { icon: "💬", label: "348" },
            { icon: "↗", label: "Chia sẻ" },
          ].map((action) => (
            <div key={action.icon} className="flex flex-col items-center gap-0.5">
              <span className="flex h-8.5 w-8.5 items-center justify-center rounded-full bg-white/15 text-sm text-white">
                {action.icon}
              </span>
              <span className="text-[9.5px] text-white/80">{action.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-col items-center justify-center gap-3">
        <button
          type="button"
          onClick={() => go(-1)}
          title="Video trước"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-line bg-panel-solid text-lg text-ink-soft hover:border-pink hover:text-pink"
        >
          ▲
        </button>
        <span className="font-technical text-[10px] text-ink-dim">
          {index + 1}/{POSTS.length}
        </span>
        <button
          type="button"
          onClick={() => go(1)}
          title="Video tiếp theo"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-line bg-panel-solid text-lg text-ink-soft hover:border-pink hover:text-pink"
        >
          ▼
        </button>
      </div>
    </div>
  );
}
