import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // issue #323 bước 2 — model 3D (~43 MB) mặc định ăn header `Cache-Control:
  // public, max-age=0` mà Next tự đặt cho toàn bộ public/, nên MỖI lần F5 phải
  // revalidate 26 request; ETag lệch (vd sau deploy) là tải lại từ đầu dù nội
  // dung không đổi. `immutable` chỉ đúng vì asset trong đường dẫn có version:
  // đổi nội dung model bắt buộc đổi tên thư mục (vd `sedan-realistic-v2/`),
  // nếu không máy đã ghé sẽ không bao giờ nhận bản mới trong 1 năm tới.
  async headers() {
    return [
      {
        source: "/assets/models/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
    ];
  },
};

export default nextConfig;
