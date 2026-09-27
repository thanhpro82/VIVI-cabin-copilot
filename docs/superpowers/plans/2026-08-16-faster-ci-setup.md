# Faster CI Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Giảm setup CI trên runner BTC từ khoảng 10 phút xuống dưới 3 phút bằng cách không restore pip cache 6.1 GB.

**Architecture:** Hai workflow tiếp tục dùng `actions/setup-python@v5` để ghim Python 3.11. Chỉ bỏ tích hợp GitHub Actions pip cache; dependencies vẫn được cài trực tiếp từ `requirements.txt` trên mỗi ephemeral runner.

**Tech Stack:** GitHub Actions YAML, Python 3.11, pip, pytest.

## Global Constraints

- Giữ `actions/setup-python@v5` và `python-version: "3.11"`.
- Không dùng `cache: pip` hoặc `cache-dependency-path`.
- Giữ timeout CI 30 phút làm giới hạn an toàn.
- Cả CI fast suite và MQTT contract phải tiếp tục chạy trên BTC self-hosted runner.

---

### Task 1: Bỏ pip cache dung lượng lớn khỏi hai workflow

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/mqtt-contract.yml`
- Test: `tests/test_vehicle/test_compose_healthcheck.py`

**Interfaces:**
- Consumes: runner BTC `self-hosted`, `actions/setup-python@v5`, `requirements.txt`.
- Produces: hai workflow dùng Python 3.11 mà không gọi GitHub Actions cache service.

- [ ] **Step 1: Xác nhận cấu hình chậm hiện tại**

Run:

```powershell
rg -n "setup-python|cache: pip|cache-dependency-path|python-version" .github/workflows/ci.yml .github/workflows/mqtt-contract.yml
```

Expected: cả hai workflow có `cache: pip` và `cache-dependency-path` dưới step `actions/setup-python@v5`.

- [ ] **Step 2: Bỏ hai thuộc tính cache khỏi mỗi workflow**

Giữ step ở đúng dạng sau trong cả hai file:

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.11"
```

Tên step `Set up Python` trong `ci.yml` được giữ nguyên; chỉ nội dung `with` thay đổi.

- [ ] **Step 3: Xác nhận không còn cấu hình cache**

Run:

```powershell
rg -n "cache: pip|cache-dependency-path" .github/workflows
```

Expected: không có kết quả trong hai workflow vừa sửa.

- [ ] **Step 4: Chạy test và lint liên quan**

Run:

```powershell
python -m pytest tests/test_vehicle/test_compose_healthcheck.py -q --tb=short
python -m ruff check tests/test_vehicle/test_compose_healthcheck.py
git diff --check
```

Expected: `5 passed`, Ruff sạch, `git diff --check` không có output.

- [ ] **Step 5: Commit và push `develop`**

```powershell
git add .github/workflows/ci.yml .github/workflows/mqtt-contract.yml
git commit -m "ci: skip oversized pip cache restore"
git push origin HEAD:develop
```

- [ ] **Step 6: Đo run mới**

Run:

```powershell
gh run list --branch develop --limit 4
```

Expected: `Set up Python` không có log `Cache restored`; mục tiêu setup cộng install dưới 3 phút. CI fast suite và MQTT contract kết thúc `success`.
