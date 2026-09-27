"use client";

import { useState } from "react";
import { OFFLINE_ASSETS } from "@/lib/assets";
import { OfflineNotice } from "./OfflineNotice";

/**
 * Spotify Embed widget <iframe> thật — dùng playlist biên tập chính thức
 * của Spotify (ổn định, công khai, không cần API key/token) để demo trực
 * quan, thay vì đoán ID từng track riêng lẻ (rủi ro sai/không tồn tại).
 */
const PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"; // Spotify — Today's Top Hits

export function SpotifyView() {
  const [loaded, setLoaded] = useState(false);

  // Đặt SAU mọi hook: `OFFLINE_ASSETS` là hằng số lúc build nên không đổi
  // giữa các lần render, nhưng return sớm trước hook vẫn vi phạm rules-of-hooks.
  if (OFFLINE_ASSETS) return <OfflineNotice appName="Spotify" />;

  return (
    <div className="flex h-full flex-col gap-3">
      <p className="flex items-center gap-2 font-display text-[17px] font-bold text-ink">
        <span className="text-green">◍</span> Spotify
      </p>
      <div className="relative min-h-0 flex-1 overflow-hidden rounded-(--r-md) border border-green/30">
        {!loaded && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-panel-solid">
            <span className="h-8 w-8 animate-spin rounded-full border-2 border-green/30 border-t-green" />
            <p className="text-xs text-ink-soft">Đang tải Spotify…</p>
          </div>
        )}
        <iframe
          className="h-full w-full"
          style={{ borderRadius: 0 }}
          src={`https://open.spotify.com/embed/playlist/${PLAYLIST_ID}?theme=0`}
          title="Spotify — Today's Top Hits"
          allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
          // Chặn embed điều hướng thoát khỏi app (không allow-top-navigation) —
          // trước đây bấm vào ảnh trong widget làm cả trang nhảy sang
          // open.spotify.com thật, mất luôn Dock/StatusBar, phải gõ lại URL.
          sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-forms"
          onLoad={() => setLoaded(true)}
        />
      </div>
    </div>
  );
}
