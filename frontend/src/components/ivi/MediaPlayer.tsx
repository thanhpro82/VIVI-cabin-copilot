"use client";

import { useEffect, useRef } from "react";
import { findTrack } from "@/lib/fixtures/media";
import { useDriverShell } from "./DriverShellProvider";

/**
 * Trình phát nhạc — không vẽ gì, chỉ giữ một thẻ `<audio>` duy nhất cho cả IVI.
 *
 * ## Vì sao KHÔNG nằm trong `MusicView`
 *
 * `DriverShell` chỉ render đúng view đang mở, nên đặt `<audio>` trong
 * `MusicView` thì chuyển sang màn Bản đồ là React tháo nó khỏi DOM. Theo spec
 * HTML, một media element bị gỡ khỏi document sẽ **bị tạm dừng** — nên nhạc tự
 * tắt mỗi lần đổi màn. Đo được trên trình duyệt thật ngày 19/08.
 *
 * Đó là hành vi đúng của trình duyệt, không phải lỗi cần né. Cách chữa là để
 * trình phát sống ở tầng shell — nơi không bao giờ bị tháo — còn `MusicView`
 * chỉ còn việc hiển thị và gửi lệnh.
 *
 * ## Một thẻ duy nhất, và phải giữ như thế
 *
 * Không thêm `key` vào thẻ `<audio>`. `key` đổi thì React tháo phần tử cũ và
 * tạo phần tử mới; đổi `src` là đủ để nạp bài mới (spec HTML: đổi thuộc tính
 * `src` tự kích hoạt lại media element load algorithm).
 *
 * Nguồn sự thật vẫn là backend: component này không giữ state phát/dừng của
 * riêng nó, chỉ soi `vehicleState.media` rồi làm theo. Bấm nút ở `MusicView`
 * gửi lệnh lên xe, xe đổi trạng thái, trạng thái quay về đây.
 */
export function MediaPlayer() {
  const { vehicleState } = useDriverShell();
  const playing = vehicleState?.media.status === "playing";
  const volume = vehicleState?.media.volume ?? 0;
  const meta = findTrack(vehicleState?.media.track);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    // `play()` trả Promise và bị từ chối khi trình duyệt chặn autoplay trước
    // thao tác đầu tiên của người dùng. Nuốt lỗi ở đây là có chủ ý: phần chữ và
    // nút bấm vẫn phải hoạt động bình thường dù loa chưa kêu.
    if (playing) void audio.play().catch(() => {});
    else audio.pause();
  }, [playing, meta?.file]);

  useEffect(() => {
    const audio = audioRef.current;
    if (audio) audio.volume = Math.min(1, Math.max(0, volume / 100));
  }, [volume]);

  // Không `src` khi tên bài không có trong fixture: thà im lặng còn hơn phát
  // nhầm bài — rơi về bài mặc định chính là cách bug #173 ẩn mình suốt nhiều tuần.
  return <audio ref={audioRef} src={meta?.file} loop data-testid="media-player" />;
}
