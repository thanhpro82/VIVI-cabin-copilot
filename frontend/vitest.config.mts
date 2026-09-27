import path from "node:path";
import { defineConfig } from "vitest/config";

// Chỉ thêm alias resolution — Next.js tự hiểu "@/*" -> "src/*" qua tsconfig
// paths (webpack alias riêng của nó), nhưng Vitest chạy trên Vite thuần,
// không tự đọc tsconfig paths. Không set `test.environment` toàn cục: phần
// lớn test hiện có (mock.test.ts, real.subscribe.test.ts) không cần DOM, môi
// trường mặc định "node" nhanh hơn — test cần jsdom (component React) tự khai
// riêng qua docblock `// @vitest-environment jsdom` ở đầu file.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
    },
  },
});
