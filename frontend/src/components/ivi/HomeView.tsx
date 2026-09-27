"use client";

import type { ReactNode } from "react";
import { useDriverShell } from "./DriverShellProvider";
import type { ViewName } from "./DriverShellProvider";
import {
  BriefcaseIcon,
  MapPinIcon,
  MicIcon,
  MusicNoteIcon,
  SpotifyLogo,
  TiktokLogo,
  YoutubeLogo,
} from "./AppIcons";

interface AppTile {
  view: ViewName;
  label: string;
  sub: string;
  icon: ReactNode;
  colorVar: string;
}

/** Theo vivi_ivi_vf8style (1).html .appgrid — 3×2. "Điều khiển xe" đã có sẵn ở Dock
 * (thanh dưới, luôn hiện) nên không lặp lại ở đây nữa — thế chỗ bằng "Chuỗi lệnh"
 * (issue #271), giữ đúng 6 ô, không để hàng cuối lẻ 1 ô. */
const APP_TILES: AppTile[] = [
  { view: "map", label: "Bản đồ", sub: "Dẫn đường", icon: <MapPinIcon />, colorVar: "--cyan" },
  { view: "music", label: "Nhạc", sub: "Trên máy", icon: <MusicNoteIcon />, colorVar: "--violet" },
  { view: "youtube", label: "YouTube", sub: "Video", icon: <YoutubeLogo />, colorVar: "--accent" },
  { view: "spotify", label: "Spotify", sub: "Streaming nhạc", icon: <SpotifyLogo />, colorVar: "--green" },
  { view: "tiktok", label: "TikTok", sub: "Video ngắn", icon: <TiktokLogo />, colorVar: "--pink" },
  { view: "routines", label: "Chuỗi lệnh", sub: "Chuỗi lệnh riêng", icon: <BriefcaseIcon />, colorVar: "--indigo" },
];

export function HomeView() {
  const { vehicleState, uiPolicy, openVoice, setActiveView, voiceOpen, wakeWordAvailable, wakeWordEnabled } =
    useDriverShell();

  const suggestion = !vehicleState?.hvac.power
    ? "bật điều hòa 22 độ"
    : vehicleState.media.status !== "playing"
      ? "bật nhạc"
      : "áp suất lốp bao nhiêu";

  // enlarge_mic_button (ui.policy) — wrapper + button phải đổi kích thước cùng lúc, không thì lệch tâm.
  const micSizeClass = uiPolicy.enlargeMicButton ? "h-20 w-20" : "h-14 w-14";

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center gap-4.5">
        <div className={`relative flex shrink-0 items-center justify-center ${micSizeClass}`}>
          {wakeWordAvailable && wakeWordEnabled && (
            <div aria-hidden className="mic-breathe pointer-events-none absolute inset-0 rounded-full" />
          )}
          <button
            type="button"
            onClick={openVoice}
            disabled={voiceOpen}
            className={`relative flex items-center justify-center rounded-full border-[1.5px] border-cyan/60 bg-[radial-gradient(circle,color-mix(in_srgb,var(--cyan)_18%,transparent),transparent_70%)] text-xl text-cyan disabled:opacity-50 ${micSizeClass}`}
          >
            <MicIcon size={24} />
          </button>
        </div>
        <div className="min-w-0 flex-1">
          {/* Câu này ĐIỀU KIỆN, không cố định. Bản 2026-08-13 gỡ "Hey VIVI" đi vì
              lúc đó chưa có wake word thật đứng sau và câu chữ hứa hẹn sai tính
              năng (TASK-FE-BE-004). Lý do đó vẫn đúng nguyên vẹn — nên câu mời
              gọi bằng giọng chỉ hiện khi bộ dò ĐANG chạy thật:
              `wakeWordAvailable` chỉ bật sau khi nó nạp xong model và vào trạng
              thái nghe. Bản deploy thiếu model.onnx (file này nằm ngoài git) sẽ
              không bao giờ đạt điều kiện đó và tự động hiện lại câu chạm mic —
              không cần cờ riêng, không có đường nào để nó hứa suông. */}
          <p className="font-display text-lg font-bold text-ink">
            {wakeWordAvailable && wakeWordEnabled ? 'Nói "Hey Vi Vi" hoặc chạm mic' : "Chạm mic để ra lệnh"}
          </p>
          <p className="mt-0.5 text-[12.5px] text-ink-soft">
            Thử nói &quot;{suggestion}&quot;
          </p>
        </div>
      </div>

      <div className="grid flex-1 grid-cols-3 grid-rows-2 gap-3.5">
        {APP_TILES.map((tile) => (
          <button
            key={tile.view}
            type="button"
            onClick={() => setActiveView(tile.view)}
            className="group relative flex flex-col items-center justify-center gap-2.5 overflow-hidden rounded-[22px] border border-line bg-panel-solid transition-transform hover:-translate-y-0.5"
            style={{ ["--tile-c" as string]: `var(${tile.colorVar})` }}
          >
            <span
              aria-hidden
              className="pointer-events-none absolute inset-0 opacity-[.16] transition-opacity group-hover:opacity-30"
              style={{
                background: "radial-gradient(ellipse 140px 100px at 50% 20%, var(--tile-c), transparent 70%)",
              }}
            />
            <span
              className="relative flex h-13 w-13 items-center justify-center rounded-2xl"
              style={{ background: "var(--tile-c)", color: "var(--bg)" }}
            >
              {tile.icon}
            </span>
            <span className="relative font-display text-sm font-semibold text-ink">{tile.label}</span>
            <span className="relative text-[10.5px] text-ink-soft">{tile.sub}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
