import { NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

/**
 * Route Handler chạy server-side — đọc DEMO_DRIVER_EMAIL/_PASSWORD (KHÔNG có
 * prefix NEXT_PUBLIC_) nên không bao giờ bị bundle vào client JS. Client (card
 * "Tài xế" ở /login) chỉ gọi POST tới route này, không bao giờ thấy credential
 * thật. Xem ARCHITECTURE.md mục 3.1.
 */
export async function POST() {
  const email = process.env.DEMO_DRIVER_EMAIL;
  const password = process.env.DEMO_DRIVER_PASSWORD;

  if (!email || !password) {
    return NextResponse.json(
      {
        error: {
          code: "DEMO_CREDENTIALS_MISSING",
          message: "Chưa cấu hình DEMO_DRIVER_EMAIL/_PASSWORD trên server — xin giá trị thật từ BE.",
          retryable: false,
        },
      },
      { status: 500 },
    );
  }

  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8; version=1.0" },
    body: JSON.stringify({ email, password }),
  });

  const body = await res.json().catch(() => null);
  return NextResponse.json(body, { status: res.status });
}
