# Git workflow — Làm việc nhóm không hỗn loạn

Một sai lầm phổ biến khi làm việc nhóm là thiếu quy trình Git thống nhất: đè code lên nhau (force push), merge conflict không giải quyết được, commit message vô nghĩa ("fix", "update", "test"), và code trên main branch liên tục bị hỏng. Nguyên nhân chính là thiếu quy trình rõ ràng. Tài liệu này thiết lập quy trình mà toàn bộ đội phải tuân thủ.

---

## 🌿 Chiến lược branching

AI20K khuyến nghị mô hình branching đơn giản nhưng hiệu quả:

- **`main`** — Branch chính, luôn ổn định và có thể deploy bất cứ lúc nào. Không bao giờ push trực tiếp lên main. Mọi thay đổi phải thông qua Pull Request.
- **`develop`** — Branch tích hợp, nơi tất cả feature branches merge vào trước khi lên main. Khi develop đã ổn định và sẵn sàng release, merge vào main.
- **`feature/TÊN-FEATURE`** — Mỗi tính năng mới hoặc bug fix được phát triển trên branch riêng. Tên branch phải mô tả rõ tính năng.

### Ví dụ quy trình làm việc:

```bash
# Bắt đầu tính năng mới
$ git checkout develop
$ git pull origin develop
$ git checkout -b feature/agent-search-tool

# Làm việc, commit thường xuyên
$ git add src/agent/tools/search.py
$ git commit -m "feat(agent): thêm tool tìm kiếm web"

# Push và tạo Pull Request
$ git push origin feature/agent-search-tool
# Sau đó tạo PR trên GitHub: feature/agent-search-tool → develop
```

---

## 📝 Định dạng commit message

Commit message phải có ý nghĩa. Mỗi commit message tuân theo format:

```text
type(scope): mô tả ngắn gọn

[mô tả chi tiết nếu cần]
```

### Các type phổ biến:

- **`feat`** — Thêm tính năng mới. Ví dụ: `feat(api): thêm endpoint /chat/stream`
- **`fix`** — Sửa bug. Ví dụ: `fix(agent): sửa lỗi Agent không xử lý input rỗng`
- **`docs`** — Cập nhật tài liệu. Ví dụ: `docs: cập nhật README với hướng dẫn cài đặt`
- **`test`** — Thêm hoặc sửa tests. Ví dụ: `test(agent): thêm test cho search tool`
- **`refactor`** — Tái cấu trúc code không thay đổi functionality. Ví dụ: `refactor(config): chuyển config sang pydantic-settings`
- **`chore`** — Việc bảo trì (update dependencies, v.v.). Ví dụ: `chore: cập nhật ruff lên v0.4.0`

> **Scope** là tùy chọn, nhưng khuyến nghị dùng: `agent`, `api`, `config`, `models`, `tests`, hoặc tên module khác.

---

## 🔀 Pull Request process

Pull Request (PR) không chỉ là cách merge code — nó là cơ hội review và đảm bảo chất lượng. Mỗi PR nên:

1. Có tiêu đề rõ ràng theo format commit message.
2. Có mô tả giải thích: thay đổi gì, tại sao, và cách test.
3. Nhỏ và tập trung — một PR nên giải quyết một vấn đề, không phải 10.
4. Được review bởi ít nhất 1 thành viên khác trước khi merge.
5. Pass tất cả automated checks (tests, linting) trước khi merge.

### PR Template

```markdown
### Thay đổi
- Thêm tool tìm kiếm web cho Agent
- Tích hợp Tavily Search API

### Tại sao
Agent cần khả năng tìm kiếm thông tin real-time để trả lời câu hỏi về sự kiện hiện tại.

### Cách test
1. Set `TAVILY_API_KEY` trong `.env`
2. Chạy `pytest tests/unit/test_search_tool.py -v`
3. Hoặc test manual qua Swagger UI: POST /api/v1/chat

### Checklist
- [x] Code tuân thủ style guide
- [x] Đã viết unit test
- [x] Tất cả tests pass
- [x] Không có hardcoded secrets
```

---

> 🔑 **ĐIỂM CHÍNH:** Git workflow không phải "paperwork" — nó là mạng lưới an toàn. Khi ai đó vô tình xóa code quan trọng, bạn có thể revert. Khi có bug mới, bạn biết commit nào gây ra nhờ git bisect. Khi review PR, bạn học code của đồng đội. Đầu tư 5 phút cho mỗi commit message và PR sẽ tiết kiệm 5 giờ debug sau này.
