"use client";

import { useState } from "react";
import { OFFLINE_ASSETS } from "@/lib/assets";
import { OfflineNotice } from "./OfflineNotice";

/**
 * <iframe> YouTube Embed thật — dùng ID video công khai, nổi tiếng toàn cầu
 * (đảm bảo luôn cho phép nhúng) để demo trực quan, không cần API key. Bố cục
 * theo vivi_ivi_vf8style (1).html .yt-grid, thêm khu vực "đang phát" khi chọn.
 */
const VIDEOS = [
  { id: "dQw4w9WgXcQ", title: "VIVI Cabin Copilot — Trải nghiệm lái thực tế", channel: "AutoDaily · 128k views" },
  { id: "jNQXAC9IVRw", title: "Sạc xe điện tại nhà — Hướng dẫn A-Z", channel: "EV Vietnam · 54k views" },
  { id: "9bZkp7q19f0", title: "Top 5 mẹo lái xe mùa mưa", channel: "Kỹ năng lái · 21k views" },
  { id: "kJQP7kiw5Fk", title: "Podcast: Tương lai xe điện Việt Nam", channel: "Tech Talk · 9.2k views" },
  { id: "60ItHLz5WEA", title: "Nhạc chạy xe — Lofi buổi sáng", channel: "Lofi Garage · 210k views" },
  { id: "fJ9rUzIMcZQ", title: "Bảo dưỡng xe định kỳ cần biết gì", channel: "Garage 24h · 33k views" },
];

export function YoutubeView() {
  const [selected, setSelected] = useState<(typeof VIDEOS)[number] | null>(null);

  if (selected) {
    return (
      <div className="flex h-full flex-col gap-3">
        <button
          type="button"
          onClick={() => setSelected(null)}
          className="self-start font-technical text-[11px] text-ink-soft hover:text-cyan"
        >
          ← Quay lại danh sách
        </button>
        <div className="min-h-0 flex-1 overflow-hidden rounded-(--r-md) border border-line bg-black">
          <iframe
            key={selected.id}
            className="h-full w-full"
            src={`https://www.youtube.com/embed/${selected.id}?autoplay=1`}
            title={selected.title}
            allow="autoplay; encrypted-media; picture-in-picture"
            allowFullScreen
          />
        </div>
        <div>
          <p className="font-display text-sm font-semibold text-ink">{selected.title}</p>
          <p className="text-[11px] text-ink-soft">{selected.channel}</p>
        </div>
      </div>
    );
  }

  // Đặt SAU mọi hook: `OFFLINE_ASSETS` là hằng số lúc build nên không đổi
  // giữa các lần render, nhưng return sớm trước hook vẫn vi phạm rules-of-hooks.
  if (OFFLINE_ASSETS) return <OfflineNotice appName="YouTube" />;

  return (
    <div className="flex h-full flex-col gap-4">
      <p className="flex items-center gap-2 font-display text-[17px] font-bold text-ink">
        <span className="text-accent">▶</span> YouTube
      </p>
      <div className="grid flex-1 grid-cols-3 grid-rows-2 gap-3.5">
        {VIDEOS.map((v) => (
          <button
            key={v.id}
            type="button"
            onClick={() => setSelected(v)}
            className="flex flex-col overflow-hidden rounded-(--r-md) border border-line bg-panel-solid text-left transition-transform hover:-translate-y-0.5"
          >
            <div className="relative min-h-0 flex-1 overflow-hidden bg-black">
              <img
                src={`https://i.ytimg.com/vi/${v.id}/hqdefault.jpg`}
                alt={v.title}
                className="absolute inset-0 h-full w-full object-cover"
              />
              <div className="absolute inset-0 bg-linear-to-b from-black/5 to-black/50" />
              <span className="absolute inset-0 flex items-center justify-center">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/25 text-sm text-white">
                  ▶
                </span>
              </span>
            </div>
            <div className="flex-1 p-3">
              <p className="line-clamp-2 text-[12.5px] leading-snug font-semibold text-ink">{v.title}</p>
              <p className="mt-1 text-[10.5px] text-ink-soft">{v.channel}</p>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
