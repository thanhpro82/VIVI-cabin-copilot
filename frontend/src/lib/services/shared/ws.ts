/**
 * `Sec-WebSocket-Protocol` chỉ chấp nhận ký tự token hợp lệ theo RFC 6455 —
 * `btoa()` sinh base64 chuẩn có padding `=`, bị trình duyệt từ chối ngay tại
 * `new WebSocket(...)`. api_spec.md:503 cũng đòi base64url. Dùng hàm này thay
 * `btoa()` trực tiếp cho mọi subprotocol `bearer.<token>`.
 */
export function toBase64Url(input: string): string {
  return btoa(input).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
