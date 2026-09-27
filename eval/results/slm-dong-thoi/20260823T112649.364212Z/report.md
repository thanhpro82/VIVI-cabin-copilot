# llama-server duoi tai dong thoi

- Run id: `20260823T112649.364212Z`
- Commit: `unknown` (dirty: False)
- Endpoint: `http://host.docker.internal:8093`, model `qwen2.5-3b-instruct-q4_k_m`
- **So slot doc duoc tu `/slots`: 4**
- Nguong cau hinh: classify 3.5s, planner 20.0s
- Tran dung khi do: 30.0s (co y noi, de do duoc do tre THAT)

## Vai `classify`

| N dong thoi | p50 (ms) | p95 (ms) | max (ms) | vuot tran | ti le |
|---:|---:|---:|---:|---:|---:|
| 1 | 1776 | 1892 | 1892 | 0/2 | 0% |
| 2 | 12184 | 21823 | 21823 | 2/4 | 50% |
| 3 | 13062 | 22706 | 22706 | 4/6 | 67% |

## Doc bang the nao

Chi so quyet dinh la **ti le vuot tran theo N**, khong phai tok/s. Nguoi dung khong cam nhan tok/s; ho cam nhan luot hong. Vuot tran classify = am tham roi ve nhanh so tay (`graph.py:333`), khong bao loi.

## Diem mu

- **mot_may_mot_lan** - MOT lan do tren MOT may. So de ra quyet dinh cau hinh, khong phai benchmark.
- **dong_thoi_that_su_khong_deu** - N request ban ra gan nhu cung luc bang ThreadPoolExecutor, KHONG phai mo phong nguoi dung that (ho den rai rac). Day la ca XAU NHAT, co y - no cho tran tren cua do tre, khong cho ky vong trung binh.
- **prefix_cache_lam_dep_so** - `cache_prompt: True` va tien to tinh nghia la vong sau re hon vong dau rat nhieu. Luot ham nong bi loai khoi thong ke, nhung cac vong con lai VAN huong loi tu KV cache am. Tren may vua restart llama-server, so that se te hon.
- **khong_do_STT_TTS** - Chi do llama-server. Mot luot that con qua STT/TTS - ca hai co khoa toan cuc (`voice.py:97`, `:192`, num_threads=1) nen cung noi tiep. Tong do tre nhieu nguoi se te hon con so o day.
- **tran_doi_chieu_la_cau_hinh_hien_tai** - Ti le vuot tran tinh theo `slm_classify_timeout_s`/`slm_timeout_s` DANG dat. Doi tran la doi ti le - doc `nguong_doi_chieu` trong metrics truoc khi so hai run.
