/**
 * Ảnh bìa sinh bằng code, không phải file (@thanhpro82 chốt ở PR #188).
 *
 * Vì sao không dùng ảnh: incompetech không phát hành bìa cho 6 bài này, nên mọi
 * ảnh dùng thay đều là ảnh stock chẳng liên quan tới bài. Gradient sinh sẵn thì
 * không thêm file vào git, không có license phải khai, và mỗi bài vẫn có một nền
 * riêng, ổn định qua mọi lần chạy.
 *
 * ## Vì sao không sinh màu tuỳ ý
 *
 * `frontend/CLAUDE.md` cấm thêm hex mới ngoài `docs/DESIGN_TOKENS.md`, và lệnh
 * cấm đó có lý do ngữ nghĩa chứ không chỉ thẩm mỹ: bảng token gán **ý nghĩa** cho
 * từng màu — `--accent` là cảnh báo và điều khiển xe nguy hiểm, `--green` là
 * Spotify, `--pink` là TikTok, `--cyan` là bản đồ. Rải sáu hue ngẫu nhiên lên sáu
 * bìa sẽ đẻ ra một bìa đỏ đọc thành "nguy hiểm" và một bìa hồng đọc thành TikTok.
 *
 * Nên cả sáu bìa ở trong họ `--violet` (token dành riêng cho *nhạc trên máy*),
 * chỉ khác nhau ở góc nghiêng và tỉ lệ pha với `--cyan` / `--bg2`. Vẫn phân biệt
 * được bằng mắt, vẫn đọc ra "đây là màn nhạc".
 */

/**
 * Băm ổn định từ chuỗi id sang số nguyên không âm.
 *
 * Cố ý dùng một hàm băm tầm thường và tự viết: nó phải cho **cùng một kết quả ở
 * mọi lần chạy và mọi máy**, vì bìa đổi màu giữa hai lần mở app trông như lỗi.
 * `Math.random` hay `Date` đều hỏng yêu cầu đó.
 */
function bam(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i += 1) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  return h;
}

/** Số biến thể. Không cần bằng số bài — trùng bìa vẫn chấp nhận được, còn thêm
 *  biến thể chỉ để "đủ 6" thì đẩy hai đầu dải ra xa họ màu nhạc. */
const SO_BIEN_THE = 6;

/**
 * Chuỗi CSS `background` cho bìa của một bài.
 *
 * @param id `track.id` trong `src/fixtures/media.json` — dùng id chứ không dùng
 * tên bài, để đổi tên hiển thị không làm đổi bìa.
 */
export function trackCoverGradient(id: string | null | undefined): string {
  const idx = id ? bam(id) % SO_BIEN_THE : 0;
  const goc = 120 + idx * 40;
  const dam = 78 - idx * 8;
  const nhat = 58 - idx * 6;

  return [
    `linear-gradient(${goc}deg,`,
    `color-mix(in srgb, var(--violet) ${dam}%, var(--cyan)) 0%,`,
    `color-mix(in srgb, var(--violet) ${nhat}%, var(--bg2)) 100%)`,
  ].join(" ");
}
