# Lệnh vận hành nhanh — VPS

Một trang, tra là chạy — dùng lúc đang hỏng, không phải lúc đọc hiểu.

| Cần gì | Đọc file nào |
|---|---|
| **Lệnh restart/log/trạng thái, deploy, đổi env, dọn đĩa** | **file này** |
| Địa chỉ máy, kiến trúc, file cấu hình nằm đâu, ai có quyền vào | [`deploy_vps_van_hanh.md`](deploy_vps_van_hanh.md) |
| Dựng lại từ đầu, và vì sao mỗi bước như vậy | [`deploy_vps_fullstack.md`](deploy_vps_fullstack.md) |
| Cập nhật code đã deploy | [`deploy_vps_cap_nhat_code.md`](deploy_vps_cap_nhat_code.md) |
| Quy trình nhánh và CD cho cả nhóm | [`quy_trinh_ci_cd.md`](quy_trinh_ci_cd.md) |

**Mọi lệnh dưới đây chạy trên VPS** (`ssh vivi@103.146.23.41`), **đứng ở đâu cũng
được** — đều dùng đường dẫn tuyệt đối. Tài khoản `vivi` đã ở trong nhóm `docker` nên
lệnh `docker` **không** cần `sudo`; lệnh `systemctl` thì cần.

## 0. Hệ thống gồm những gì

| Thành phần | Chạy bằng | Tên |
|---|---|---|
| Backend (FastAPI) | Docker Compose | `backend` |
| Broker MQTT | Docker Compose | `mqtt` |
| Xe ảo | Docker Compose | `vehicle-simulator` |
| Frontend (Next.js) | systemd | `vivi-frontend` |
| SLM (llama-server) | systemd | `vivi-slm` |
| HTTPS / reverse proxy | systemd | `caddy` |

Ba cái đầu là container, ba cái sau là dịch vụ hệ thống — **hai loại lệnh khác nhau**,
đừng trộn.

## 1. Kiểm tra trước đã

```bash
bash ~/health.sh
```

Chạy cái này **trước khi** restart bất cứ thứ gì. Phần lớn lần "hình như hỏng" hoá ra
không cần restart, và restart mù làm mất luôn manh mối.

## 2. Backend

**Sau khi đổi `.env`, `docker-compose.yml` hay `docker-compose.override.yml`** — dùng
lệnh này, không dùng `restart`:

```bash
cd /opt/vivi && docker compose up -d --force-recreate backend
```

> `docker compose restart` **không đọc lại cấu hình**. Nó chỉ dừng rồi chạy lại tiến
> trình trong cái vỏ container cũ, nên `.env`, `extra_hosts` và `ports` đều giữ nguyên
> giá trị lúc container được **tạo**. Đây là nguyên nhân sự cố 2026-08-23: `llm: down`
> và cổng 8000 hở ra Internet cùng lúc, trong khi `docker compose config` vẫn in ra cấu
> hình đúng. Xem `deploy_vps_fullstack.md` §11.3.

**Sau khi đổi code trong `src/`** (phải build lại image):

```bash
cd /opt/vivi && docker compose build backend && docker compose up -d backend
```

**Chỉ muốn khởi động lại tiến trình, không đổi gì:**

```bash
cd /opt/vivi && docker compose restart backend
```

## 3. Frontend

**Sau khi đổi code `frontend/` hoặc biến `NEXT_PUBLIC_*`** — phải build lại:

```bash
cd /opt/vivi/frontend && npm run build && sudo systemctl restart vivi-frontend
```

> `NEXT_PUBLIC_*` được **nướng vào bundle lúc build**. `systemctl restart` một mình
> không đổi được gì cả. Nếu `package-lock.json` cũng đổi thì chèn `npm ci &&` trước
> `npm run build`.

**Chỉ khởi động lại server đang phục vụ bundle sẵn có:**

```bash
sudo systemctl restart vivi-frontend
```

Nếu `npm run build` chết giữa chừng vì hết RAM (đỉnh ~1 173 MB), tắt SLM rồi build:

```bash
sudo systemctl stop vivi-slm && cd /opt/vivi/frontend && npm run build && sudo systemctl start vivi-slm && sudo systemctl restart vivi-frontend
```

## 4. SLM (llama-server)

```bash
sudo systemctl restart vivi-slm
```

Lệnh này **mất 30–60 giây mới xong**: nó nạp lại ~2 GB trọng số rồi chạy
`slm_warmup.sh` để hâm nóng KV cache (`TimeoutStartSec=180`). Trong lúc đó `/healthz`
báo `llm: down` — đó là bình thường, đợi rồi kiểm lại:

```bash
curl -s -m 20 -w '\nHTTP %{http_code}\n' http://127.0.0.1:8093/health
```

`{"status":"ok"}` + `HTTP 200` là xong. `HTTP 503` nghĩa là vẫn đang nạp model.

## 5. MQTT và xe ảo

`vehicle-simulator` **phụ thuộc healthcheck của `mqtt`**, nên restart broker thì phải
restart xe ảo theo, và phải chờ:

```bash
cd /opt/vivi && docker compose up -d --wait mqtt vehicle-simulator
```

Chỉ restart xe ảo (broker vẫn khoẻ):

```bash
cd /opt/vivi && docker compose restart vehicle-simulator
```

> Đừng chạy `python -m src.vehicle_sim` bằng tay khi container xe ảo đang chạy: hai
> tiến trình dùng trùng `client_id`, broker sẽ đá nhau qua lại và triệu chứng nhìn hệt
> như "frontend sập".

## 6. Caddy (HTTPS)

Sau khi sửa `Caddyfile`, dùng **`reload`** chứ không phải `restart` — reload giữ nguyên
kết nối đang mở và không xin lại chứng chỉ:

```bash
sudo systemctl reload caddy
```

Kiểm cú pháp trước cho chắc:

```bash
caddy validate --config /etc/caddy/Caddyfile
```

## 7. Khởi động lại toàn bộ, đúng thứ tự

Chỉ làm khi thật cần. Thứ tự quan trọng: broker trước, xe ảo và backend sau.

```bash
cd /opt/vivi && docker compose up -d --wait mqtt vehicle-simulator && docker compose up -d --force-recreate backend
```

```bash
sudo systemctl restart vivi-slm && sudo systemctl restart vivi-frontend && sudo systemctl reload caddy
```

```bash
bash ~/health.sh
```

## 8. Xem log khi có gì đó hỏng

```bash
cd /opt/vivi && docker compose logs -n 100 backend
```

```bash
cd /opt/vivi && docker compose logs -n 50 vehicle-simulator
```

```bash
sudo journalctl -u vivi-frontend -n 50 --no-pager
```

```bash
sudo journalctl -u vivi-slm -n 50 --no-pager
```

```bash
sudo journalctl -u caddy -n 50 --no-pager
```

Theo dõi trực tiếp thì thay `-n 50 --no-pager` bằng `-f` (Ctrl+C để thoát).

## 9. Trạng thái nhanh

```bash
cd /opt/vivi && docker compose ps
```

```bash
systemctl is-active caddy vivi-frontend vivi-slm
```

```bash
free -h && df -h /
```

## 10. Deploy code mới

```bash
bash /opt/vivi/deploy/vps/deploy.sh
```

Deploy nhánh **đang checkout** trên VPS. Muốn nhánh khác:

```bash
DEPLOY_REF=main bash /opt/vivi/deploy/vps/deploy.sh
```

Script tự quyết có cần build lại backend/frontend không, dựa trên **file thực sự thay
đổi** giữa hai lần `git pull` — nên lần deploy chỉ sửa tài liệu không tốn vài phút build.

**Nó cố ý không đổi bốn thứ**: `.env`, `Caddyfile`, `vivi-slm.service`,
`vivi-frontend.service`. Bốn file ấy đổi hiếm và nên đổi có ý thức — xem §12.

Hai điều cần biết trước khi gõ:

- **Gõ tay thì mở `tmux` trước.** Rớt mạng giữa lúc build backend là để lại một container
  nửa vời. Script tự cảnh báo nếu thấy không có `tmux`, nhưng nó không chặn.
- **Mã thoát có nghĩa.** Đỏ = *"code đã lên nhưng kiểm cuối không đạt"* — hoặc `/healthz`
  không `ready` sau khoảng chờ, hoặc bundle frontend còn trỏ `localhost:8000`. Đọc đúng
  hai mục cuối trong output, đừng deploy lại ngay.

## 11. Xem cấu hình đang chạy

**`.env` có mật khẩu.** `MQTT_BACKEND_PASSWORD`, `MQTT_SIMULATOR_PASSWORD` và
`AI_LOG_API_KEY` nằm trong đó, nên đừng `cat` nguyên file khi đang chia sẻ màn hình. Xem
**tên khoá** trước:

```bash
grep -oE '^[A-Z_]+' /opt/vivi/.env | sort
```

Xem giá trị của đúng một khoá:

```bash
grep '^SLM_ENABLED=' /opt/vivi/.env
```

**Cấu hình sau khi hợp nhất** (`.env` + `docker-compose.yml` + override) — đây mới là thứ
Docker thật sự dùng khi tạo container:

```bash
cd /opt/vivi && docker compose config
```

**Cái container đang chạy thực sự mang giá trị nào** — dùng khi nghi `.env` và container
đã lệch nhau (xem bẫy §14):

```bash
cd /opt/vivi && docker compose exec backend printenv SLM_ENABLED MQTT_ENABLED
```

Ba nơi cấu hình, và chúng **không** thay thế nhau được:

| File | Ai đọc | Đổi xong phải làm gì |
|---|---|---|
| `/opt/vivi/.env` | backend + xe ảo (Docker) | `up -d --force-recreate` (§2) |
| `/opt/vivi/frontend/.env.production` | `NEXT_PUBLIC_*`, **nhúng lúc build** | build lại frontend (§3) |
| `/opt/vivi/frontend/.env.runtime` | systemd `vivi-frontend` | `systemctl restart vivi-frontend` |

## 12. Đổi cấu hình

**Sao lưu trước.** Một dòng, và nó cứu được buổi demo:

```bash
cp /opt/vivi/.env /opt/vivi/.env.bak.$(date +%F-%H%M)
```

**Backend** — sửa rồi tạo lại container:

```bash
nano /opt/vivi/.env
```
```bash
cd /opt/vivi && docker compose up -d --force-recreate backend
```
```bash
bash ~/health.sh
```

**Frontend, biến `NEXT_PUBLIC_*`** — biến build-time, restart không đủ:

```bash
nano /opt/vivi/frontend/.env.production
```
```bash
cd /opt/vivi/frontend && npm run build && sudo systemctl restart vivi-frontend
```

**Frontend, biến runtime:**

```bash
sudo nano /opt/vivi/frontend/.env.runtime && sudo systemctl restart vivi-frontend
```

Ba kỷ luật, mỗi cái đến từ một lần hỏng thật:

1. **Đổi một biến mỗi lần**, rồi chạy `health.sh`. Đổi ba biến cùng lúc thì lúc hỏng
   không biết biến nào.
2. **Không sửa `.env` trên VPS rồi quên ghi lại.** `.env` không đi qua git — máy khác
   không có thay đổi ấy, và lần dựng lại VPS sẽ mất.
3. **`SLM_ENABLED` để `true`.** Thiếu tài nguyên thì nâng máy, không tắt bớt tính năng.

## 13. Dọn đĩa — image và cache Docker

**Điều tra trước, xoá sau.** Script này **chỉ đọc**, không xoá gì:

```bash
bash /opt/vivi/deploy/vps/kiem_dung_luong.sh
```

Xem trước cái gì sẽ bị xoá:

```bash
docker image ls -f dangling=true
```

Hai lệnh dọn **an toàn** — chỉ chạm thứ không ai tham chiếu tới:

```bash
docker image prune -f
```
```bash
docker builder prune -f
```

`image prune -f` xoá image mồ côi (`<none>`, còn lại sau mỗi lần build lại).
`builder prune -f` xoá cache build — **không** đụng image đang chạy.

### Chừa lại phần mới bằng `--filter until=`

Hai lệnh trên xoá **sạch** thứ chúng nhắm tới. Trên máy này thường không phải điều mình
muốn: cache build của hôm nay là thứ làm lần deploy kế tiếp nhanh, và image `<none>` vừa
sinh ra mấy phút trước có thể đang là lớp của bản vừa build. `until` chừa phần mới lại:

```bash
docker image prune -f --filter until=24h
```
```bash
docker builder prune -f --filter until=168h
```

Chọn số theo nhịp làm việc chứ không theo thói quen: 24h cho image (giữ nguyên mọi thứ
sinh ra trong ngày), 168h = 7 ngày cho cache (giữ cache của cả tuần deploy).

**Hai lệnh này lọc theo hai mốc khác nhau** — đây là chỗ dễ nhầm:

| Lệnh | `until` tính theo |
|---|---|
| `docker image prune` | **thời điểm image được tạo** — xoá cái tạo trước mốc |
| `docker builder prune` | **lần cuối cache được dùng tới** — xoá cái nằm không lâu hơn mốc |

Nên một cache build hôm qua vẫn được dùng sáng nay thì `until=168h` **không** đụng tới nó,
trong khi một image tạo tuần trước thì `until=24h` xoá — dù nó vừa được tham chiếu.

Giá trị nhận cả `24h`, `168h`, `30m`, hoặc một mốc thời gian tuyệt đối
(`2026-08-01T00:00:00`).

> `docker image prune --help` trên máy dev in thẳng ví dụ `"until=<timestamp>"`. Với
> `docker builder prune` thì bản `buildx` mỗi máy một khác — bản trên máy dev chỉ in
> `--filter filter  Provide filter values` mà không liệt kê giá trị nào. **Kiểm trên
> chính VPS trước khi đưa vào việc chạy định kỳ**, một lệnh là xong:
>
> ```bash
> docker builder prune --filter until=99999h --force
> ```
>
> Ra `Total reclaimed space: 0B` là filter được chấp nhận và không xoá gì (không cache nào
> cũ tới thế). Báo lỗi filter thì bản buildx trên VPS không nhận `until`, dùng
> `docker builder prune -f` trần và chấp nhận mất cache.

**Hai lệnh KHÔNG nên gõ trên VPS này:**

| Lệnh | Vì sao |
|---|---|
| `docker image prune -a` | xoá cả image **không chạy nhưng còn dùng để rollback**. Mất nó thì đường lùi nhanh nhất khi deploy hỏng biến mất, và build lại trên VPS mất hàng chục phút. Nếu buộc phải chạy, ít nhất kèm `--filter until=` để chừa bản vừa deploy |
| `docker system prune -a` | như trên, cộng volume và network — có thể lấy luôn dữ liệu MQTT/SQLite |

Sau khi dọn, kiểm lại còn bao nhiêu:

```bash
df -h / && docker system df
```

## 14. Năm cái bẫy hay vấp nhất

| Làm gì | Vì sao hỏng |
|---|---|
| Đổi `.env` rồi `docker compose restart backend` | `restart` không đọc lại cấu hình — phải `up -d --force-recreate` (§2) |
| Đổi `NEXT_PUBLIC_*` rồi `systemctl restart vivi-frontend` | Biến build-time, phải `npm run build` lại (§3) |
| Restart `vivi-slm` rồi kết luận ngay là hỏng | Cần 30–60 s nạp model; `llm: down` trong lúc đó là bình thường (§4) |
| `docker image prune -a` cho "gọn máy" | Xoá luôn image còn dùng để rollback; build lại trên VPS mất hàng chục phút (§13) |
| Sửa `.env` trên VPS rồi quên ghi lại | `.env` không đi qua git — lần dựng lại VPS là mất (§12) |
