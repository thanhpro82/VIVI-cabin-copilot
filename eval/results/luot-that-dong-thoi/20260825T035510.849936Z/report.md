# Luot that qua backend duoi tai dong thoi

- Run id: `20260825T035510.849936Z`
- Commit: `3e4e6a49ff81` (dirty: True)
- Base URL: `https://c4-app-192.io.vn/api/v1` — che do **text**
- Nguong doi chieu: p50 2500 ms, p95 4500 ms
- Tran dung khi do: 60s (co y noi, de do duoc do tre THAT)
- **Cau hinh llama-server: n_ctx 2048, n_slots 4, kv_unified None**

## Tong hop

| N | p50 (ms) | p95 (ms) | max (ms) | vuot p95 | loi | cat cut | p50 dat | p95 dat |
|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | 330 | 1048 | 1048 | 0/3 | 0/3 | 0 | DAT | DAT |
| 2 | 1502 | 19207 | 19207 | 2/6 | 0/6 | 0 | DAT | **TRUOT** |
| 3 | 1424 | 29675 | 29675 | 3/9 | 0/9 | 0 | DAT | **TRUOT** |

## Tach theo duong di

| N | nhan | p50 (ms) | p95 (ms) | vuot p95 |
|---:|---|---:|---:|---:|
| 1 | dieu_khien | 265 | 330 | 0/2 |
| 1 | so_tay | 1048 | 1048 | 0/1 |
| 2 | chitchat | 19035 | 19035 | 1/1 |
| 2 | dieu_khien | 449 | 532 | 0/2 |
| 2 | planner | 19207 | 19207 | 1/1 |
| 2 | so_tay | 1502 | 1787 | 0/2 |
| 3 | chitchat | 29507 | 29507 | 1/1 |
| 3 | dieu_khien | 858 | 1577 | 0/4 |
| 3 | planner | 29675 | 29675 | 1/1 |
| 3 | so_tay | 1424 | 29332 | 1/3 |

## Doc bang the nao

1. **Tach theo nhan truoc khi ket luan.** `dieu_khien` khong cham SLM chut nao (router tat dinh), `so_tay` cham classify roi di RAG, `planner` la duong dat nhat va khong co loi vong. Tron chung thi duong re che mat duong dat.
2. **`cat cut` > 0** thi moi so trong dong do la CAN DUOI, khong phai gia tri.
3. **Che do `text` la CAN DUOI cua luot thoai that** — khong co STT, khong co TTS.
4. **`loi` khac 0 sau khi them van SLM la du kien**, khong phai su co: do chinh la 'tu choi nhanh' dang lam viec. Doc `ban_ghi` (chay voi `--giu-ban-ghi`) de tach 'bi tu choi' khoi 'that su hong'.

## Diem mu

- **mot_may_mot_lan** - MOT lan do tren MOT may. So de ra quyet dinh cau hinh, khong phai benchmark.
- **dong_thoi_khong_deu** - N request ban ra gan nhu cung luc, KHONG mo phong nguoi dung that (ho den rai rac). Day la ca XAU NHAT, co y: cho tran tren cua do tre, khong cho ky vong trung binh.
- **mot_tai_khoan_N_phien** - Tat ca N phien thuoc cung MOT tai khoan demo (src/services/auth.py chi co hai tai khoan hard-code). Do duoc tranh chap tai nguyen, KHONG do duoc tranh chap o tang auth hay pool xe theo nguoi dung.
- **am_thanh_tong_hop** - Che do voice dung WAV Piper tong hop trong tests/fixtures/voice/. Do duoc DO TRE that, KHONG ket luan duoc gi ve WER nguoi noi that.
- **che_do_text_khong_co_stt_tts** - --che-do text bo qua STT va TTS. Ca hai co khoa toan cuc (voice.py:97, :192, num_threads=1) nen chung noi tiep bat ke van SLM dat bao nhieu. So cua che do text la CAN DUOI cua do tre luot thoai that.
- **lich_su_anh_huong_ket_qua** - Do tre phu thuoc slot nao dang giu tien to nao, tuc phu thuoc vai phut TRUOC do. Hai run cung cau hinh co the lech nhieu lan. Luon doc cau_hinh_llama trong manifest truoc khi so.
- **caddy_trong_duong_do** - Mac dinh do qua domain that, tuc CO Caddy va TLS trong duong. Dung --base-url http://127.0.0.1:8000/api/v1 de bo ra. Hai cach cho hai con so khac nhau; dung tron.
