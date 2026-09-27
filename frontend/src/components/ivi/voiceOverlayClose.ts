/**
 * Quyết định "đóng overlay đợi audio hay đóng ngay" — tách khỏi
 * `DriverShellProvider.tsx` để test thuần, không cần dựng `HTMLAudioElement`
 * thật hay effect React.
 *
 * Trước đây overlay tự đóng cố định 1.8s sau khi CÓ TEXT câu trả lời — không
 * liên quan gì tới audio TTS thật đang phát (`assistant.speech` tới gần như
 * cùng lúc `assistant.response`, nên với câu dài audio còn đang đọc mà
 * overlay đã tắt gần hết giờ). Giờ đợi audio phát XONG (`ended`) rồi mới bắt
 * đầu đếm giờ đóng — nhưng phải fail-open: audio bị trình duyệt chặn
 * autoplay, lỗi decode, hoặc turn này không có `assistant.speech` (TTS thất
 * bại phía BE, "vắng mặt hoàn toàn" theo đúng hợp đồng, không phải lỗi) đều
 * phải coi như "không có gì để đợi", đóng ngay theo hẹn giờ thường — không
 * được để overlay treo vô thời hạn chờ 1 sự kiện `ended` sẽ không bao giờ tới.
 */
export function shouldStartCloseTimerImmediately(
  audio: Pick<HTMLAudioElement, "ended" | "error"> | null,
): boolean {
  if (!audio) return true;
  return audio.ended || audio.error !== null;
}
