import fixture from "./media.json";

/**
 * Playlist demo — đọc bản sao đồng bộ của `src/fixtures/media.json`.
 *
 * Bản sao là thứ SINH RA bởi `scripts/sync_fixtures.ps1`, không phải thứ viết
 * tay; `tests/test_services/test_fixtures.py` so từng byte hai bản. Thêm bài thì
 * sửa `src/fixtures/media.json` rồi chạy lại script, đừng sửa file JSON ở đây.
 *
 * `name` là **khoá nối** với backend: `vehicleState.media.track` mang đúng chuỗi
 * mà `default_playlist()` đọc ra từ cùng fixture. Trước issue #173 hai bên là hai
 * danh sách chép tay không khớp nhau một tên nào, nên mọi lượt tra đều trượt và
 * rơi về bài mặc định — UI đổi chữ, loa phát mãi một file.
 */
export interface MediaTrack {
  id: string;
  name: string;
  artist: string;
  /** Đường dẫn dưới `frontend/public/` — xem LICENSE.md. */
  file: string;
  license: string;
  /** Bắt buộc hiện ra UI: playlist là CC BY 4.0, ghi công là điều kiện của giấy phép. */
  attribution: string;
  source: string;
  source_url: string | null;
}

export const MEDIA_TRACKS: readonly MediaTrack[] = fixture.items;

/** Tên bài theo đúng thứ tự phát — khớp `default_playlist()` của simulator. */
export const TRACK_NAMES: readonly string[] = MEDIA_TRACKS.map((track) => track.name);

/**
 * Tra bài theo tên backend trả về.
 *
 * Trả `undefined` chứ **không** lặng lẽ rơi về bài đầu tiên: chính cái rơi-về-mặc
 * định im lặng đã che bug tên bài lệch suốt nhiều tuần. Chỗ gọi phải tự quyết
 * hiển thị gì khi không khớp, và quyết định ấy phải nhìn thấy được trong code.
 */
export function findTrack(name: string | null | undefined): MediaTrack | undefined {
  return name ? MEDIA_TRACKS.find((track) => track.name === name) : undefined;
}
