// @vitest-environment jsdom
// Cần DOM thật cho `sessionStorage` — xem chú thích trong vitest.config.ts.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  consumeAuthNotice,
  isAuthFailureCode,
  peekAuthNotice,
  reportAuthFailure,
  resetAuthFailureListeners,
  subscribeAuthFailure,
} from "./authFailure";

describe("authFailure", () => {
  afterEach(() => {
    resetAuthFailureListeners();
    window.sessionStorage.clear();
  });

  it("chỉ AUTH_REQUIRED nghĩa là phiên không còn dùng được", () => {
    expect(isAuthFailureCode("AUTH_REQUIRED")).toBe(true);
    // `FORBIDDEN` từng trả `true` ở đây và đó là lỗi (PM/PO review PR #157): mọi 403
    // của backend đều mang đúng mã này, nhưng không ca nào nghĩa là token chết — sai
    // role, Origin không hợp lệ, tài nguyên của người khác, session hết hạn. Token
    // vẫn sống nguyên trong cả bốn.
    expect(isAuthFailureCode("FORBIDDEN")).toBe(false);
    // Những mã này KHÔNG được đá người dùng ra ngoài — chúng là lỗi của một
    // lượt cụ thể, phiên vẫn tốt.
    expect(isAuthFailureCode("INPUT_INVALID")).toBe(false);
    expect(isAuthFailureCode("MQTT_UNAVAILABLE")).toBe(false);
    expect(isAuthFailureCode(undefined)).toBe(false);
  });

  it("báo cho mọi listener đang đăng ký", () => {
    const first = vi.fn();
    const second = vi.fn();
    subscribeAuthFailure(first);
    subscribeAuthFailure(second);

    reportAuthFailure("token đã hết hạn");

    expect(first).toHaveBeenCalledWith("token đã hết hạn");
    expect(second).toHaveBeenCalledWith("token đã hết hạn");
  });

  it("huỷ đăng ký thì không nhận nữa", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeAuthFailure(listener);
    unsubscribe();

    reportAuthFailure("token đã hết hạn");

    expect(listener).not.toHaveBeenCalled();
  });

  it("peek đọc được nhiều lần với cùng một giá trị — getSnapshot của useSyncExternalStore đòi đúng thế", () => {
    // Một `getSnapshot` trả giá trị khác nhau giữa hai lần gọi liên tiếp làm
    // React render vô hạn; đó là lý do peek và consume là hai hàm khác nhau.
    reportAuthFailure("token không còn hiệu lực");

    expect(peekAuthNotice()).toBe("token không còn hiệu lực");
    expect(peekAuthNotice()).toBe("token không còn hiệu lực");
  });

  it("consume đọc được đúng MỘT lần rồi biến mất", () => {
    // Xoá là chủ đích: nếu để lại, lần sau người dùng chủ động đăng xuất và
    // quay lại /login sẽ thấy một câu cảnh báo cũ không còn đúng nữa.
    reportAuthFailure("token không còn hiệu lực");

    expect(consumeAuthNotice()).toBe("token không còn hiệu lực");
    expect(consumeAuthNotice()).toBeNull();
  });

  it("báo nhiều lần liên tiếp không hỏng gì — poll 2 giây có thể trượt vài nhịp trước khi trang kịp chuyển", () => {
    const listener = vi.fn();
    subscribeAuthFailure(listener);

    reportAuthFailure("lần 1");
    reportAuthFailure("lần 2");

    expect(listener).toHaveBeenCalledTimes(2);
    expect(consumeAuthNotice()).toBe("lần 2");
  });
});
