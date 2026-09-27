export interface ServiceErrorShape {
  code: string;
  message: string;
  retryable: boolean;
  /**
   * Chi tiết máy-đọc-được đi kèm lỗi (vd `{execution_id}` của 409
   * `ROUTINE_RUNNING` — #298, để nối "xoá thất bại vì đang chạy" sang nút
   * Dừng). Tuỳ chọn: hầu hết lỗi không cần, và không phải domain nào cũng
   * đọc `error.details` từ backend.
   */
  details?: Record<string, unknown>;
}

export class ServiceError extends Error implements ServiceErrorShape {
  code: string;
  retryable: boolean;
  details?: Record<string, unknown>;

  constructor({ code, message, retryable, details }: ServiceErrorShape) {
    super(message);
    this.name = "ServiceError";
    this.code = code;
    this.retryable = retryable;
    this.details = details;
  }
}
