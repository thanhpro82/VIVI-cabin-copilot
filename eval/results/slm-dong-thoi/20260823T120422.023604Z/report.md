# llama-server duoi tai dong thoi

- Run id: `20260823T120422.023604Z`
- Commit: `0f0a31fde96a` (dirty: False)
- Endpoint: `http://host.docker.internal:8093`, model `qwen2.5-3b-instruct-q4_k_m`
- **So slot doc duoc tu `/slots`: 4**
- **Ghim slot: KHONG**
- Nguong cau hinh: classify 3.5s, planner 20.0s
- Tran dung khi do: 30.0s (co y noi, de do duoc do tre THAT)
- Nap nguoi = `timings.prompt_n` >= 100 token

## Vai `classify`

| N | p50 (ms) | p95 (ms) | max (ms) | vuot tran | nap nguoi | prompt_n p50/max | prefill max (ms) | slot | cat cut |
|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 1 | 1673 | 1878 | 1878 | 0/3 | **0/3** | 15/17 | 803.1 | {0: 3} | 0 |
| 2 | 3128 | 21938 | 21938 | 2/6 | **1/6** | 15.5/483 | 20407.4 | {0: 3, 1: 1, 2: 1, 3: 1} | 0 |
| 3 | 4562 | 24789 | 24789 | 9/9 | **1/9** | 15/485 | 22749.3 | {0: 3, 1: 1, 2: 3, 3: 2} | 0 |
| 5 | 5595 | 26722 | 26722 | 15/15 | **1/15** | 15/479 | 23085.7 | {0: 6, 1: 3, 2: 3, 3: 3} | 0 |

## Vai `tron`

| N | p50 (ms) | p95 (ms) | max (ms) | vuot tran | nap nguoi | prompt_n p50/max | prefill max (ms) | slot | cat cut |
|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 1 | 1571 | 1813 | 1813 | 0/3 | **0/3** | 15/17 | 785.6 | {0: 3} | 0 |
| 2 | 3873 | 8400 | 8400 | 0/6 | **0/6** | 10.0/17 | 1731.6 | {0: 1, 1: 2, 2: 1, 3: 2} | 0 |
| 3 | 4008 | 7600 | 7600 | 0/9 | **0/9** | 14/19 | 2037.0 | {0: 3, 1: 2, 2: 2, 3: 2} | 0 |
| 5 | 30066 | 30081 | 30081 | 15/15 | **0/15** | 15/15 | 817.3 | {0: 1} | 10 |

## Doc bang the nao

1. **`nap nguoi`** la cot quan trong nhat. `timings.prompt_n` chi dem token THAT SU phai tinh; phan trung KV cache khong duoc dem. Nen `prompt_n` lon = tien to khong nam trong slot do = phai prefill lai tu dau (~19,6 tok/s tren may nay).
2. **`vuot tran`** la thu nguoi dung cam nhan. Vuot tran classify = am tham roi ve nhanh so tay (`graph.py:333`), khong bao loi.
3. **`cat cut` > 0** thi moi so trong dong do la CAN DUOI, khong phai gia tri.
4. **`slot`** cho biet request roi vao rang nao. Ghim slot dung thi moi vai chi thay dung mot rang.

## Diem mu

- **mot_may_mot_lan** - MOT lan do tren MOT may. So de ra quyet dinh cau hinh, khong phai benchmark.
- **du_lieu_bi_cat_cut** - Luot cham tran 30s duoc danh dau `cat_cut`. Gia tri that la '>= 30s, chua biet'. Moi o co `so_cat_cut > 0` thi p50/p95/max va ti le vuot tran deu la CAN DUOI.
- **p95_o_mau_nho_chinh_la_max** - Voi `--vong 3`, muc N=1 chi co 3 mau nen 'p95' chinh la gia tri lon nhat. Dung doc no nhu mot phan vi that.
- **dong_thoi_khong_deu** - N request ban ra gan nhu cung luc, KHONG mo phong nguoi dung that (ho den rai rac). Day la ca XAU NHAT, co y: cho tran tren cua do tre, khong cho ky vong trung binh.
- **lich_su_anh_huong_ket_qua** - Do tre phu thuoc slot nao dang giu tien to nao, tuc phu thuoc vai phut TRUOC do. Hai run cung cau hinh co the lech 4x. Luon doc `so_lan_nap_nguoi` truoc khi so hai run.
- **khong_do_STT_TTS** - Chi do llama-server. Luot that con qua STT/TTS - ca hai co khoa toan cuc (`voice.py:97`, `:192`, num_threads=1) nen cung noi tiep. Tong do tre se te hon.
- **n_predict_la_literal** - `_N_PREDICT` chep tay tu `slm.py`. Doi n_predict o do ma quen o day thi script do mot cau hinh KHONG con ton tai. Kiem lai khi slm.py doi.
