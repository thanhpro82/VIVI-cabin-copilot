"use client";

import { DriverShellProvider, useDriverShell } from "./DriverShellProvider";
import { StatusBar } from "./StatusBar";
import { Dock } from "./Dock";
import { RightPanel } from "./RightPanel";
import { MediaPlayer } from "./MediaPlayer";
import { HitlModal } from "./HitlModal";
import { VoiceOverlay } from "./VoiceOverlay";
import { Toast } from "./Toast";
import { SpeedDebugDrawer } from "./SpeedDebugDrawer";
import { HomeView } from "./HomeView";
import { VehicleControlView } from "./VehicleControlView";
import { MusicView } from "./MusicView";
import { MapView } from "./MapView";
import { YoutubeView } from "./YoutubeView";
import { SpotifyView } from "./SpotifyView";
import { TiktokView } from "./TiktokView";
import { RoutinesView } from "./RoutinesView";

function Content() {
  const { activeView, routinePreview } = useDriverShell();
  switch (activeView) {
    case "music":
      return <MusicView />;
    case "map":
      return <MapView />;
    case "youtube":
      return <YoutubeView />;
    case "spotify":
      return <SpotifyView />;
    case "tiktok":
      return <TiktokView />;
    case "routines":
      return <RoutinesView key={routinePreview?.turnId ?? "routines"} />;
    case "home":
    default:
      return <HomeView />;
  }
}

/** "Điều khiển xe" tự quản lý bố cục 3 phần riêng (nhóm nút bên trái + xe 3D
 * 1/3 chiều rộng bên phải, cao toàn khung) — không dùng chung khung <main>
 * bo viền/padding lẫn RightPanel như các view khác, tránh lặp xe 3D và nút
 * khoá/điều hoà/đèn 2 nơi cùng lúc trên cùng 1 màn hình. */
function MainArea() {
  const { activeView } = useDriverShell();
  if (activeView === "vehicle") {
    return <VehicleControlView />;
  }
  return (
    <>
      <main className="min-w-0 flex-1 overflow-hidden rounded-(--r-lg) border border-line bg-(--panel)">
        <div className="h-full overflow-y-auto p-6">
          <Content />
        </div>
      </main>
      <RightPanel />
    </>
  );
}

/** IVI Screen — StatusBar/Content/RightPanel/Dock/HITL/Voice, theo docs/ARCHITECTURE.md mục 3 + vivi_ivi_vf8style (1).html. */
export function DriverShell() {
  return (
    <DriverShellProvider>
      {/* Nền "vũ trụ" (sao + tinh vân) đặt chung ở <body> — globals.css — nên khối này để trong suốt, không tự vẽ background riêng nữa. */}
      <div className="relative flex h-screen flex-col">
        <StatusBar />
        <div className="flex min-h-0 flex-1 gap-4 p-4">
          <MainArea />
        </div>
        <Dock />
        {/* Trình phát nhạc sống ở đây, KHÔNG trong MusicView: shell không bao
            giờ bị tháo, nên nhạc phát xuyên qua mọi lần đổi màn. Đặt trong
            MusicView thì chuyển sang Bản đồ là React gỡ thẻ audio khỏi DOM và
            trình duyệt tạm dừng nó — đúng spec, và đúng lỗi đo được 19/08. */}
        <MediaPlayer />
        <HitlModal />
        <VoiceOverlay />
        <Toast />
        <SpeedDebugDrawer />
      </div>
    </DriverShellProvider>
  );
}
