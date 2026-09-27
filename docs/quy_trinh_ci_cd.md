# Quy trình CI/CD — hướng dẫn cho nhóm P-192

Ai cũng đọc được, không cần biết trước gì về DevOps. Máy chủ và cấu hình cụ thể ở
[`deploy_vps_van_hanh.md`](deploy_vps_van_hanh.md); lệnh cập nhật thủ công chi tiết ở
[`deploy_vps_cap_nhat_code.md`](deploy_vps_cap_nhat_code.md).

## Luồng tổng quát

```
feature/*  ──PR──▶  develop  ──PR──▶  main  ──tự động──▶  https://c4-app-192.io.vn/
   │                   │                │
 code của bạn      CI kiểm tra      CI + CD deploy
                   (không deploy)
```

**Điều quan trọng nhất phải nhớ:**

| Bạn merge vào | Website công khai có đổi không? |
|---|---|
| `develop` | **Không** |
| `main` | **Có — tự động, trong vài phút** |

`main` = "cái đang chạy ngoài kia". Nhìn `main` là biết ban giám khảo đang thấy gì.

## 1. Làm việc hằng ngày — nhánh `feature/*` và `develop`

```
git checkout develop
git pull
git checkout -b feature/ten-viec-cua-ban
```

Code, commit, push, mở PR vào `develop`.

**CI tự chạy** (`ruff check` + `pytest`) mỗi khi bạn mở PR hoặc push thêm commit:

- **Xanh** → merge được.
- **Đỏ** → GitHub chặn merge. Bấm vào job đỏ để xem lỗi, sửa rồi push tiếp.

CI chạy trên máy ảo của BTC, **không** đụng tới VPS. Merge vào `develop` bao nhiêu
lần cũng không ảnh hưởng website công khai.

## 2. Muốn xem code của mình chạy thật thì làm sao

Ba cách, chọn theo nhu cầu:

### Cách A — chạy trên máy mình (an toàn nhất, khuyến nghị)

Không đụng gì tới VPS, không ai khác bị ảnh hưởng.

**Cửa sổ 1 — MQTT + xe ảo** (PowerShell, tại thư mục gốc repo):

```powershell
docker compose up -d --wait mqtt vehicle-simulator
```

**Cửa sổ 2 — backend:**

```powershell
.\.venv\Scripts\python.exe -m src.serve
```

Phải dùng `python -m src.serve`, **không** dùng `uvicorn src.main:app` — trên Windows
uvicorn chọn event loop thiếu hàm mà `paho-mqtt` cần, mọi kết nối MQTT sẽ lỗi.

**Cửa sổ 3 — frontend:**

```powershell
cd frontend
```

```powershell
npm run dev
```

Mở `http://localhost:3000`. Micro hoạt động vì `localhost` được trình duyệt coi là
secure context.

> **Trước khi tin những gì thấy trên màn hình**, mở Console (F12) và chạy:
> ```js
> (await navigator.serviceWorker.getRegistrations()).forEach(r => r.unregister());
> ```
> Service worker của một dự án khác từng chạy ở cổng 3000 sẽ chiếm quyền và hiển thị
> giao diện cũ của nó — trang vẫn hiện ra, bấm không ăn, không báo lỗi gì. Đã mất
> một buổi test vì chuyện này.

### Cách B — xem bản đang chạy trên VPS mà không cần domain

Dùng khi muốn kiểm chính xác thứ VPS đang phục vụ, hoặc xem `/engineer` (không nên
mở ra công khai vì nó lộ trace của mọi người).

```powershell
ssh -L 3000:127.0.0.1:3000 -L 8000:127.0.0.1:8000 vivi@103.146.23.41
```

Để nguyên cửa sổ đó, mở `http://localhost:3000`. Đóng cửa sổ là mất kết nối.

Lưu ý: cách này **không** chạy code của bạn — nó chỉ là cách nhìn vào bản trên VPS.

### Cách C — deploy nhánh `develop` lên VPS (cẩn thận)

Chỉ khi cần cho người khác xem qua Internet, hoặc test thứ chỉ hỏng trên máy chủ.

```bash
ssh vivi@103.146.23.41
```

```bash
tmux new -s deploy
```

```bash
DEPLOY_REF=develop /opt/vivi/deploy/vps/deploy.sh
```

> **Chỉ có một VPS.** Deploy `develop` nghĩa là `https://c4-app-192.io.vn/` phục vụ
> code `develop` cho **mọi người, kể cả ban giám khảo**. Script sẽ in cảnh báo lớn
> nhắc bạn điều này.
>
> Xong việc, **trả về production**:
> ```bash
> DEPLOY_REF=main /opt/vivi/deploy/vps/deploy.sh
> ```

## 3. Phát hành — merge `develop` vào `main`

Khi `develop` đã ổn và muốn đẩy ra cho ban giám khảo:

```powershell
gh pr create --base main --head develop --title "release: <mo ta ngan>"
```

Sau khi PR được merge:

1. CI chạy trên `main`.
2. CI xanh → workflow `CD - Trien khai VPS` **tự động** kích hoạt.
3. Nó SSH vào VPS, chạy `deploy.sh` với `DEPLOY_REF=main`.
4. Script tự quyết định cần rebuild gì (xem §5) và kiểm `/healthz` ở cuối.

Xem tiến trình ở tab **Actions** trên GitHub. Nếu đỏ, mở job ra đọc log —
thường là lỗi build, không phải lỗi hạ tầng.

**Deploy lại mà không có commit mới:** tab Actions → `CD - Trien khai VPS` →
**Run workflow**.

## 4. Script `deploy.sh` làm gì

Cùng một script cho cả hai đường (tay và tự động), chỉ khác biến `DEPLOY_REF`.

| Bước | Nội dung |
|---|---|
| 1 | Kiểm cây làm việc — có file lạ đang sửa dở thì **dừng**, không tự ý ghi đè |
| 2 | `git pull` nhánh đích. Nếu đã mới nhất → thoát luôn, không làm gì thừa |
| 3 | Đọc diff để quyết định phần nào cần build lại |
| 4 | Backend: `docker compose build` + `up -d` (chỉ khi `src/`, `Dockerfile`, `requirements*` đổi) |
| 5 | Frontend: `npm ci` (nếu lockfile đổi) + `npm run build` + restart (chỉ khi `frontend/` đổi) |
| 6 | Kiểm `/healthz` (chờ tới 150 s, hỏi lại mỗi 5 s) và bundle frontend không còn trỏ `localhost:8000` |

Bước 6 **phải chờ**: container backend vừa được tạo lại còn nạp FAISS index và
model STT/TTS, nên `/healthz` trả `503` trong vài chục giây đầu là bình thường.
Bản trước chỉ `sleep 2` rồi hỏi một lần nên gần như luôn báo động giả — xem §7.

Bước 6 cũng là thứ quyết định **mã thoát** của script, và do đó màu của job CD:
không đạt thì đỏ, đạt thì xanh. Trước đây script chỉ in `[LOI]` rồi vẫn thoát 0.

**Nó không tự làm:** đổi `.env`, `Caddyfile`, file systemd. Những thứ đó hiếm khi đổi
và nên làm có ý thức — xem `deploy_vps_cap_nhat_code.md` §4/§5/§6.

## 5. Ba lớp bảo vệ trong script

**Chống lùi phiên bản (cùng nhánh).** Nếu commit đích cũ hơn bản đang chạy, script
từ chối — trên cùng một nhánh, đi lùi gần như luôn là nhầm.

**Đổi nhánh thì cho phép**, kèm cảnh báo. Ví dụ thật: deploy tay `develop` để test,
sau đó CD trả về `main` — `main` lúc đó có thể sau `develop` vài commit nhưng vẫn là
bản production đúng.

Khi đổi nhánh, script tự khôi phục các file chỉ khác kiểu xuống dòng (CRLF/LF, nội
dung giống hệt — kiểm bằng `git diff --quiet`), nhưng **giữ nguyên** file có thay đổi
nội dung thật để không âm thầm xoá công của ai đó.

**Chạy từ một bản sao.** Bước 2 `git merge` ghi đè chính `deploy.sh` trong lúc nó
đang chạy. Bash đọc script theo khối 8 KB và nhớ **offset trong file**, nên với file
quá 8 KB (hiện là 10 563 byte) phần chưa chạy sẽ được đọc tiếp từ offset cũ trên nội dung
mới — bash nhảy vào giữa một dòng bất kỳ. Đo được: một script 8 954 byte bị ghi đè
giữa chừng chết với `unexpected EOF while looking for matching '"'`. Vì vậy script tự
sao chép sang `/tmp` và chạy bản sao đó; bản sao nằm ngoài repo nên `git merge` không
đụng tới.

## 6. Bảo mật — vì sao CD không tự do như bạn tưởng

CD dùng một tài khoản riêng tên `deploy` trên VPS, bị khoá bốn lớp:

| Lớp | Chặn được gì |
|---|---|
| Tài khoản riêng, không mật khẩu | Không dùng được tài khoản `vivi` |
| `command=` trong `authorized_keys` | Dù có khoá cũng **không mở được shell**, không đọc được `.env` |
| `sudo` chỉ cho đúng một đường dẫn script | Không chạy được lệnh nào khác |
| `DEPLOY_REF=main` ép sẵn | Không deploy nhánh khác được, kể cả khi GitHub bị chiếm |

Ba secret trên GitHub (`VPS_SSH_KEY`, `VPS_HOST`, `VPS_USER`) do người có quyền
`write` trên repo tạo. **Không dán khoá riêng tư vào chat, issue, hay commit.**

## 7. Gặp lỗi thì làm gì

| Triệu chứng | Nguyên nhân thường gặp |
|---|---|
| CI đỏ ở `ruff` | Lỗi format/lint. Chạy `ruff check src/ tests/ scripts/` ở máy để xem |
| CI đỏ ở `pytest` | Test hỏng thật. Chạy `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q` |
| CD không chạy sau khi merge `main` | CI chưa xanh. CD chỉ chạy khi CI thành công |
| `deploy.sh` báo `TU CHOI: ... la to tien` | Nhánh đích cũ hơn bản đang chạy — kiểm lại đang deploy nhánh nào |
| `deploy.sh` dừng ở "file lạ đang sửa dở" | Có ai đó sửa tay trên VPS. SSH vào xem `git status`, xử lý rồi chạy lại |
| Website lên nhưng WebSocket hỏng (`4403`) | `CORS_ORIGINS` trong `.env` lệch domain. Xem `deploy_vps_van_hanh.md` §5 |
| Trang lên nhưng gọi API về `localhost` | Frontend build thiếu domain. Chạy lại §3.4 của `deploy_vps_cap_nhat_code.md` |
| CD đỏ ngay sau `[LOI] healthz KHONG ready` | Nếu VPS vẫn khoẻ (`bash ~/health.sh` xanh) thì code **đã** deploy xong; xem log có phải bản `deploy.sh` cũ (chỉ `sleep 2`, không chờ) hay không |
| CD đỏ nhưng log không in dòng `== Xong: ... ==` | Script chết giữa chừng chứ không phải kiểm cuối trượt — đọc dòng cuối cùng in ra được để biết dừng ở đâu |
