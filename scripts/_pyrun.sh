#!/usr/bin/env bash
# Cross-platform Python launcher for AI log hooks.
# Ưu tiên venv của repo, rồi mới python3 → python → py -3 trên PATH; trên Windows
# còn dò các thư mục cài Python thường gặp, vì Git Bash do một số hook gọi lên có
# PATH bị cắt bớt và thiếu thư mục Python của Windows.
# Dùng như: bash scripts/_pyrun.sh <script> [args...]
#
# Thoát 0 im lặng nếu không tìm thấy Python — hook không bao giờ được chặn AI tool.
set -u

# Venv của repo đứng trước PATH, vì hai lý do:
#
# 1. Đó là Python duy nhất repo này validate (3.11.9 — xem CLAUDE.md). Hook chạy
#    bằng interpreter khác là chạy ngoài thứ đã được kiểm chứng.
# 2. `submit_log.py` nạp `.env` qua `python-dotenv` trong một `try/except
#    ImportError: pass` **im lặng**. Trên máy có MSYS2, `python3` trỏ vào
#    /c/msys64/... (3.12) vốn không cài dotenv, nên `.env` không bao giờ được đọc,
#    `AI_LOG_SERVER` rỗng, và submit_log lặng lẽ in "skipping submission" — log
#    ghi đủ ở cục bộ nhưng **không bao giờ lên server**. Mất nhiều thời gian mới
#    chẩn đoán ra vì lỗi thoái hoá thành "bỏ qua" chứ không thành "hỏng".
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
# `.venv` đứng trước `.venv311`: PR #114 đã xoá cây 3.13.7 ở `.venv` rồi đổi tên
# `.venv311` thành `.venv`, nên danh sách cũ chỉ dò `.venv311` không khớp gì nữa trên
# máy đã đổi tên. Giữ lại `.venv311` cho máy chưa đổi — `.gitignore:15` loại `.venv*/`
# nên không venv nào qua git, và mỗi máy ở một trạng thái khác nhau.
for venv_py in \
  "$REPO_ROOT/.venv/Scripts/python.exe" \
  "$REPO_ROOT/.venv/bin/python" \
  "$REPO_ROOT/.venv311/Scripts/python.exe" \
  "$REPO_ROOT/.venv311/bin/python"; do
  if [ -x "$venv_py" ]; then
    # shellcheck disable=SC2086
    exec "$venv_py" "$@"
  fi
done

# Loại stub App Execution Alias của Windows. Nó nằm sẵn trên PATH của mọi máy Windows,
# `command -v` thấy nó nên nhánh dò thư mục bên dưới không bao giờ chạy tới, mà gọi thì
# nó chỉ in "Python was not found..." rồi thoát. Kết hợp với `|| true` ở pre-push, hỏng
# này **hoàn toàn im lặng**: push vẫn xanh, log không bao giờ lên server — đúng cùng lớp
# lỗi mà chính file này đã ghi cho ca `python-dotenv`.
_that_python() {
  local duong_dan
  duong_dan="$(command -v "$1" 2>/dev/null)" || return 1
  case "$duong_dan" in
    */WindowsApps/*) return 1 ;;
  esac
  return 0
}

if _that_python python3; then
  PY=python3
elif _that_python python; then
  PY=python
elif _that_python py; then
  PY="py -3"
else
  # PATH lookup failed — probe standard Windows install locations.
  PY=""
  shopt -s nullglob 2>/dev/null || true
  for cand in \
    /c/Users/*/AppData/Local/Programs/Python/Python*/python.exe \
    "/c/Program Files/Python"*/python.exe \
    "/c/Program Files (x86)/Python"*/python.exe \
    /c/Python*/python.exe; do
    if [ -x "$cand" ]; then PY="$cand"; break; fi
  done
  shopt -u nullglob 2>/dev/null || true
  [ -n "$PY" ] || exit 0
fi

# shellcheck disable=SC2086
exec $PY "$@"
