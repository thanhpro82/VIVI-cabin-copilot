# Luot that qua backend duoi tai dong thoi

- Run id: `20260825T040756.906529Z`
- Commit: `3e4e6a49ff81` (dirty: True)
- Base URL: `https://c4-app-192.io.vn/api/v1` — che do **voice**
- Nguong doi chieu: p50 2500 ms, p95 4500 ms
- Tran dung khi do: 60s (co y noi, de do duoc do tre THAT)
- **Cau hinh llama-server: n_ctx 2048, n_slots 4, kv_unified None**

## Tong hop

| N | p50 (ms) | p95 (ms) | max (ms) | vuot p95 | loi | cat cut | p50 dat | p95 dat |
|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | 33 | 56 | 56 | 0/2 | 0/2 | 0 | DAT | DAT |
| 2 | 450 | 661 | 661 | 0/4 | 0/4 | 0 | DAT | DAT |
| 3 | 844 | 3631 | 3631 | 0/5 | 1/6 | 1 | DAT | DAT |

## Tach theo duong di

| N | nhan | p50 (ms) | p95 (ms) | vuot p95 |
|---:|---|---:|---:|---:|
| 1 | voice:Bật điều hòa | 56 | 56 | 0/1 |
| 1 | voice:Đặt điều hòa hai mươi bốn độ | 10 | 10 | 0/1 |
| 2 | voice:Bật điều hòa | 312 | 312 | 0/1 |
| 2 | voice:Mở cửa sổ bên phụ một nửa | 34 | 34 | 0/1 |
| 2 | voice:Tăng nhiệt độ lên hai mươi sáu độ | 587 | 587 | 0/1 |
| 2 | voice:Đặt điều hòa hai mươi bốn độ | 661 | 661 | 0/1 |
| 3 | voice:Bật sưởi ghế lái mức hai | 3631 | 3631 | 0/1 |
| 3 | voice:Bật điều hòa | 1279 | 2435 | 0/2 |
| 3 | voice:Mở cửa sổ bên phụ một nửa | - | - | 1 loi |
| 3 | voice:Tăng nhiệt độ lên hai mươi sáu độ | 65 | 65 | 0/1 |
| 3 | voice:Đặt điều hòa hai mươi bốn độ | 844 | 844 | 0/1 |

## Doc bang the nao

1. **Tach theo nhan truoc khi ket luan.** `dieu_khien` khong cham SLM chut nao (router tat dinh), `so_tay` cham classify roi di RAG, `planner` la duong dat nhat va khong co loi vong. Tron chung thi duong re che mat duong dat.
2. **`cat cut` > 0** thi moi so trong dong do la CAN DUOI, khong phai gia tri.
3. **Che do `text` la CAN DUOI cua luot thoai that** — khong co STT, khong co TTS.
4. **`loi` khac 0 sau khi them van SLM la du kien**, khong phai su co: do chinh la 'tu choi nhanh' dang lam viec. Doc `ban_ghi` (chay voi `--giu-ban-ghi`) de tach 'bi tu choi' khoi 'that su hong'.

## Diem mu

- **mot_may_mot_lan** - MOT lan do tren MOT may. So de ra quyet dinh cau hinh, khong phai benchmark.
- **dong_thoi_khong_deu** - N request ban ra gan nhu cung luc, KHONG mo phong nguoi dung that (ho den rai rac). Day la ca XAU NHAT, co y: cho tran tren cua do tre, khong cho ky vong trung binh.
- **mot_tai_khoan_N_phien** - Tat ca N phien thuoc cung MOT tai khoan demo (src/services/auth.py chi co hai tai khoan hard-code). Do duoc tranh chap tai nguyen, KHONG do duoc tranh chap o tang auth hay pool xe theo nguoi dung.
- **wav_toan_lenh_dieu_khien** - CA 5 file trong tests/fixtures/voice/synthetic_commands deu la LENH DIEU KHIEN ('Bat dieu hoa', 'Mo cua so ben phu mot nua'...). Router tat dinh xu duoc het, nen che do voice do STT -> router -> executor -> TTS va KHONG BAO GIO cham SLM. Doc so cua no nhu 'san cua duong thoai', KHONG phai nhu bang chung ve tranh chap model. Muon do ca hai thi phai co WAV cua cau hoi so tay / cau truot luat — chua ai lam.
- **am_thanh_tong_hop** - Che do voice dung WAV Piper tong hop trong tests/fixtures/voice/. Do duoc DO TRE that, KHONG ket luan duoc gi ve WER nguoi noi that.
- **che_do_text_khong_co_stt_tts** - --che-do text bo qua STT va TTS. Ca hai co khoa toan cuc (voice.py:97, :192, num_threads=1) nen chung noi tiep bat ke van SLM dat bao nhieu. So cua che do text la CAN DUOI cua do tre luot thoai that.
- **lich_su_anh_huong_ket_qua** - Do tre phu thuoc slot nao dang giu tien to nao, tuc phu thuoc vai phut TRUOC do. Hai run cung cau hinh co the lech nhieu lan. Luon doc cau_hinh_llama trong manifest truoc khi so.
- **caddy_trong_duong_do** - Mac dinh do qua domain that, tuc CO Caddy va TLS trong duong. Dung --base-url http://127.0.0.1:8000/api/v1 de bo ra. Hai cach cho hai con so khac nhau; dung tron.
