# llama-server duoi tai dong thoi

- Run id: `20260823T113821.667870Z`
- Commit: `0f0a31fde96a` (dirty: False)
- Endpoint: `http://host.docker.internal:8093`, model `qwen2.5-3b-instruct-q4_k_m`
- **So slot doc duoc tu `/slots`: 4**
- Nguong cau hinh: classify 3.5s, planner 20.0s
- Tran dung khi do: 30.0s (co y noi, de do duoc do tre THAT)

## Vai `classify`

| N dong thoi | p50 (ms) | p95 (ms) | max (ms) | vuot tran | ti le |
|---:|---:|---:|---:|---:|---:|
| 1 | 1561 | 1963 | 1963 | 0/3 | 0% |
| 2 | 2688 | 2943 | 2943 | 0/6 | 0% |
| 3 | 4184 | 4476 | 4476 | 9/9 | 100% |
| 5 | 6062 | 26193 | 26193 | 15/15 | 100% |
| 8 | 7370 | 9441 | 9664 | 22/24 | 92% |

## Vai `planner`

| N dong thoi | p50 (ms) | p95 (ms) | max (ms) | vuot tran | ti le |
|---:|---:|---:|---:|---:|---:|
| 1 | 7410 | 29326 | 29326 | 1/3 | 33% |
| 2 | 8743 | 11368 | 11368 | 0/6 | 0% |
| 3 | 12777 | 14020 | 14020 | 0/9 | 0% |
| 5 | 30068 | 30082 | 30082 | 11/15 | 73% |
| 8 | 30093 | 30107 | 30114 | 24/24 | 100% |

## Vai `tron`

| N dong thoi | p50 (ms) | p95 (ms) | max (ms) | vuot tran | ti le |
|---:|---:|---:|---:|---:|---:|
| 1 | 1639 | 26327 | 26327 | 1/3 | 33% |
| 2 | 4521 | 8365 | 8365 | 0/6 | 0% |
| 3 | 4260 | 8301 | 8301 | 0/9 | 0% |
| 5 | 30064 | 30071 | 30071 | 13/15 | 87% |
| 8 | 30086 | 30116 | 30129 | 24/24 | 100% |

## Doc bang the nao

Chi so quyet dinh la **ti le vuot tran theo N**, khong phai tok/s. Nguoi dung khong cam nhan tok/s; ho cam nhan luot hong. Vuot tran classify = am tham roi ve nhanh so tay (`graph.py:333`), khong bao loi.

## Diem mu

- **mot_may_mot_lan** - MOT lan do tren MOT may. So de ra quyet dinh cau hinh, khong phai benchmark.
- **dong_thoi_that_su_khong_deu** - N request ban ra gan nhu cung luc bang ThreadPoolExecutor, KHONG phai mo phong nguoi dung that (ho den rai rac). Day la ca XAU NHAT, co y - no cho tran tren cua do tre, khong cho ky vong trung binh.
- **prefix_cache_lam_dep_so** - `cache_prompt: True` va tien to tinh nghia la vong sau re hon vong dau rat nhieu. Luot ham nong bi loai khoi thong ke, nhung cac vong con lai VAN huong loi tu KV cache am. Tren may vua restart llama-server, so that se te hon.
- **khong_do_STT_TTS** - Chi do llama-server. Mot luot that con qua STT/TTS - ca hai co khoa toan cuc (`voice.py:97`, `:192`, num_threads=1) nen cung noi tiep. Tong do tre nhieu nguoi se te hon con so o day.
- **tran_doi_chieu_la_cau_hinh_hien_tai** - Ti le vuot tran tinh theo `slm_classify_timeout_s`/`slm_timeout_s` DANG dat. Doi tran la doi ti le - doc `nguong_doi_chieu` trong metrics truoc khi so hai run.
