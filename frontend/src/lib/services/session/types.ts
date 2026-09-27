export type UserRole = "driver" | "engineer";

export interface AuthUser {
  userId: string;
  role: UserRole;
  displayName: string;
}

export interface LoginResult {
  accessToken: string;
  tokenType: string;
  expiresAt: string;
  user: AuthUser;
}

export interface VehiclePoolStatus {
  total: number;
  inUse: number;
  free: number;
}

export interface DriverSession {
  sessionId: string;
  vehicleId: string;
  status: string;
  startedAt: string;
  /**
   * false = chế độ chỉ xem: vẫn tra sổ tay, vẫn đọc trạng thái xe, nhưng lệnh
   * điều khiển bị từ chối (`vehicle_pool_exhausted`). KHÔNG được suy ra từ
   * `vehicleId` — cột đó luôn có giá trị kể cả phiên chỉ-xem.
   */
  canDrive: boolean;
  /** null = hệ đang chạy một xe, không có trần nào để hiện. */
  pool: VehiclePoolStatus | null;
}

export interface SessionService {
  /** Card "Tài xế" ở /login — auto-login bằng credential demo, không hiện form. */
  loginAsDriver(): Promise<LoginResult>;
  /** Card "Kỹ sư" ở /login — form nhập tay email/password thật. */
  login(email: string, password: string): Promise<LoginResult>;
  /** Đọc phiên đã lưu (localStorage) nếu còn hạn — dùng lúc load app để bỏ qua /login. */
  getStoredSession(): LoginResult | null;
  logout(): void;
  /**
   * Interface #2 (POST /api/v1/sessions) — chỉ Tài xế cần, gọi sau khi đã có
   * access_token, trước khi turnService gửi lệnh đầu tiên. Domain `turn` phụ
   * thuộc vào session_id trả về từ đây (xem turn/real.ts).
   */
  createDriverSession(vehicleId: string): Promise<DriverSession>;
  getCurrentDriverSession(): DriverSession | null;
}
