# Luot that qua backend duoi tai dong thoi

- Run id: `20260825T073454.403779Z`
- Commit: `5861ea7fa3cf` (dirty: True)
- Base URL: `https://c4-app-192.io.vn/api/v1` — che do **text**
- Nguong doi chieu: p50 2500 ms, p95 4500 ms
- Tran dung khi do: 60s (co y noi, de do duoc do tre THAT)
- **Cau hinh llama-server: n_ctx 2048, n_slots 4, kv_unified None**

## Tong hop

| N | p50 (ms) | p95 (ms) | max (ms) | vuot p95 | bi tu choi | loi | cat cut | p50 dat | p95 dat |
|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | 895 | 21999 | 28626 | 9/24 | **0**/24 | 0/24 | 0 | DAT | **TRUOT** |
| 2 | 1393 | 31480 | 32439 | 9/24 | **0**/24 | 0/24 | 0 | DAT | **TRUOT** |
| 3 | 2060 | 28279 | 35119 | 7/24 | **0**/24 | 0/24 | 0 | DAT | **TRUOT** |

## Tach theo duong di

| N | nhan | n mau | p50 (ms) | p95 (ms) | vuot p95 | ra plan |
|---:|---|---:|---:|---:|---:|---:|
| 1 | chitchat | 3 | 293 | 406 | 0/3 | 0/3 |
| 1 | dieu_khien | 6 | 249 | 324 | 0/6 | 3/6 |
| 1 | planner | 9 | 15419 | 28626 | 9/9 | 5/9 |
| 1 | so_tay | 6 | 895 | 1275 | 0/6 | 0/6 |
| 2 | chitchat | 3 | 620 | 678 | 0/3 | 0/3 |
| 2 | dieu_khien | 6 | 370 | 528 | 0/6 | 3/6 |
| 2 | planner | 9 | 21713 | 32439 | 9/9 | 3/9 |
| 2 | so_tay | 6 | 1393 | 1775 | 0/6 | 0/6 |
| 3 | chitchat | 3 | 737 | 857 | 0/3 | 0/3 |
| 3 | dieu_khien | 6 | 727 | 1097 | 0/6 | 3/6 |
| 3 | planner | 9 | 5881 | 35119 | 6/9 | 1/9 |
| 3 | so_tay | 6 | 2662 | 4536 | 1/6 | 0/6 |

## Doc bang the nao

1. **Cot 'Tong hop' so ngang duoc giua cac muc N** — moi vong chay DU bo ca, chia thanh lo N. Truoc 2026-08-25 thi khong: ti le ca doi theo N, va p50 o N=3 tung THAP HON p50 o N=2 chi vi N=3 roi trung nhieu cau re hon.
2. **Tach theo nhan truoc khi ket luan.** `dieu_khien` khong cham SLM chut nao (router tat dinh), `so_tay` cham classify roi di RAG, `planner` la duong dat nhat va khong co loi vong. Tron chung thi duong re che mat duong dat.
3. **Cot `bi tu choi` phai doc TRUOC cot p50.** Sau ADR-030, luot qua tai tra ve gan nhu tuc thi kem cau 'dang ban'. No la HTTP 200 va rat nhanh, nen no KEO p50 XUONG. Mot bang co p50 dep va `bi tu choi` cao khong phai he nhanh len — la mot phan nguoi dung khong duoc phuc vu. So sanh hai run phai so ca hai cot.
4. **Cot `ra plan` tach 'cham' khoi 'hong'.** Mot luot planner 28 giay roi tra ve clarify van la HTTP 200, nen no dem la thanh cong o bang tong hop. `ra plan` dem so luot THAT SU sinh duoc ke hoach. `0/3` nghia la duong do khong chay, khong phai chay cham.
5. **`cat cut` > 0** thi moi so trong dong do la CAN DUOI, khong phai gia tri.
6. **Che do `text` la CAN DUOI cua luot thoai that** — khong co STT, khong co TTS.
7. **`loi` khac 0 sau khi them van SLM la du kien**, khong phai su co: do chinh la 'tu choi nhanh' dang lam viec. Doc `ban_ghi` (chay voi `--giu-ban-ghi`) de tach 'bi tu choi' khoi 'that su hong'.

## Diem mu

- **ghep_lo_van_khong_phai_ngau_nhien** - Moi vong chay du bo ca, cat thanh lo N, va bo ca duoc XOAY theo vong de cac ca khac nhau co dip dung chung lo. Nhung voi `--vong` nho thi so to hop van it: `--vong 3` tren 6 ca chi cho 3 cach ghep. Doc cot `cung_lo` trong ban_ghi truoc khi ket luan mot nhan 'khong bi anh huong' — co the no chua bao gio chay chung lo voi `planner`.
- **p95_o_mau_nho_chinh_la_max** - Bang 'tach theo duong di' chia mau cho 4-6 nhan, nen nhieu o chi co 1-2 mau. Voi 1 mau thi 'p50' = 'p95' = 'max' = chinh gia tri do. Dung doc no nhu mot phan vi that; doc cot n_mau truoc.
- **mot_may_mot_lan** - MOT lan do tren MOT may. So de ra quyet dinh cau hinh, khong phai benchmark.
- **dong_thoi_khong_deu** - N request ban ra gan nhu cung luc, KHONG mo phong nguoi dung that (ho den rai rac). Day la ca XAU NHAT, co y: cho tran tren cua do tre, khong cho ky vong trung binh.
- **mot_tai_khoan_N_phien** - Tat ca N phien thuoc cung MOT tai khoan demo (src/services/auth.py chi co hai tai khoan hard-code). Do duoc tranh chap tai nguyen, KHONG do duoc tranh chap o tang auth hay pool xe theo nguoi dung.
- **wav_toan_lenh_dieu_khien** - CA 5 file trong tests/fixtures/voice/synthetic_commands deu la LENH DIEU KHIEN ('Bat dieu hoa', 'Mo cua so ben phu mot nua'...). Router tat dinh xu duoc het, nen che do voice do STT -> router -> executor -> TTS va KHONG BAO GIO cham SLM. Doc so cua no nhu 'san cua duong thoai', KHONG phai nhu bang chung ve tranh chap model. Muon do ca hai thi phai co WAV cua cau hoi so tay / cau truot luat — chua ai lam.
- **am_thanh_tong_hop** - Che do voice dung WAV Piper tong hop trong tests/fixtures/voice/. Do duoc DO TRE that, KHONG ket luan duoc gi ve WER nguoi noi that.
- **che_do_text_khong_co_stt_tts** - --che-do text bo qua STT va TTS. Ca hai co khoa toan cuc (voice.py:97, :192, num_threads=1) nen chung noi tiep bat ke van SLM dat bao nhieu. So cua che do text la CAN DUOI cua do tre luot thoai that.
- **lich_su_anh_huong_ket_qua** - Do tre phu thuoc slot nao dang giu tien to nao, tuc phu thuoc vai phut TRUOC do. Hai run cung cau hinh co the lech nhieu lan. Luon doc cau_hinh_llama trong manifest truoc khi so.
- **caddy_trong_duong_do** - Mac dinh do qua domain that, tuc CO Caddy va TLS trong duong. Dung --base-url http://127.0.0.1:8000/api/v1 de bo ra. Hai cach cho hai con so khac nhau; dung tron.
