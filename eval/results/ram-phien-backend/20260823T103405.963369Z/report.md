# RAM bien cua backend cho moi phien tai xe

- Run id: `20260823T103405.963369Z`
- May: `Linux-6.8.0-138-generic-x86_64-with-glibc2.39`, Python `3.12.3`
- Container do: `vivi-backend-1`
- Che do: **phien_co_luot**, on dinh 4.0s moi moc
- Phien da tao: 25 (luot loi: 0)

## So do

| So phien | MEM USAGE (MB) |
|---:|---:|
| 0 | 1333.25 |
| 1 | 1334.27 |
| 5 | 1336.32 |
| 10 | 1338.37 |
| 25 | 1346.56 |

## Ket qua khop

- **RAM bien: 0.512 MB moi phien tai xe**
- Diem chan: 1333.63 MB
- Quy doi tho: ~4577 phien lap day 0.7 x MemAvailable (3348.2 MB). **KHONG phai suc chua that** - CPU, so ket noi WS va khoa STT/TTS vo truoc RAM.

## Diem mu

- **mot_may_mot_lan** - MOT lan lay mau tren MOT may. So de lap ngan sach, khong phai benchmark.
- **docker_stats_khong_phai_rss_thuan** - `docker stats` bao working set cua cgroup, khong phai VmRSS thuan: no gom ca page cache cua container. Do doc van dung vi cache gan nhu khong doi giua cac moc, nhung DIEM CHAN thi khong so duoc voi VmRSS cua script khac.
- **gop_ba_chi_phi** - Do doc gom CA BA: checkpoint LangGraph, ban ghi trace trong TraceStore, va phien trong SQLite. Day la chu y - cai can lap ngan sach la 'mot tai xe dang hoat dong ton bao nhieu', khong phai tach rieng tung cau truc.
- **mot_luot_moi_phien** - Moi phien chi chay MOT luot. Tai xe that noi nhieu luot, checkpoint lon dan theo lich su hoi thoai. Nen day la SAN, khong phai tran.
- **khong_tru_nhieu_slm** - SLM dang bat: llama-server la tien trinh RIENG tren host, khong nam trong container backend, nen no khong vao con so nay. Nhung KV cache cua no co lon len theo so luot - phan do phai do rieng.
- **lru_lam_phang_duong** - MAX_SESSIONS=128 va MAX_TOKENS=256 la LRU. Chay qua nguong do thi duong cong phang ra mot cach gia tao vi phien cu bi day ra, khong phai vi phien re di.
