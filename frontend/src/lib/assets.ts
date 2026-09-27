/**
 * Chọn giữa asset đóng gói sẵn và tài nguyên web, theo một cờ duy nhất.
 *
 * Vì sao là một hàm chung chứ không phải mỗi component tự xử: IVI hiện phụ thuộc
 * sáu host ngoài lúc chạy (`basemaps.cartocdn.com`, `soundhelix.com`,
 * `picsum.photos`, `youtube.com/embed`, `i.ytimg.com`, `open.spotify.com/embed`)
 * trong khi slide mở màn demo nói "chạy hoàn toàn offline". Việc gỡ khoảng cách
 * đó là issue #176; hàm này là nửa đầu của nó, đặt vào đây TRƯỚC khi #173/#175
 * thêm asset mới — nếu không, mọi asset thêm hôm nay phải sửa lại lần hai.
 *
 * Cờ TẮT (mặc định) cho hành vi y hệt hôm nay, nên không component nào phải biết
 * cờ này tồn tại: chúng chỉ khai báo "bản cục bộ ở đây, bản web ở kia".
 *
 * Đọc `process.env` ở cấp module là cố ý, không phải nhỡ tay: Next thay thế
 * `process.env.NEXT_PUBLIC_*` lúc build bằng chuỗi hằng, nên đây là một hằng số
 * sau khi bundle, không phải một lần đọc mỗi khung hình.
 */
export const OFFLINE_ASSETS = process.env.NEXT_PUBLIC_OFFLINE_ASSETS === "true";

/**
 * @param local đường dẫn dưới `frontend/public/` — ví dụ `/media/carefree.mp3`
 * @param remote URL công khai dùng khi chưa bật chế độ demo
 */
export function assetUrl(local: string, remote: string): string {
  return OFFLINE_ASSETS ? local : remote;
}
