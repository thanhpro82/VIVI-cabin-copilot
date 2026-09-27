# RAM bien cua xe ao khi chay nhieu xe trong mot tien trinh

- Run id: `20260823T102021.980250Z`
- May: `Linux-6.8.0-138-generic-x86_64-with-glibc2.41`, Python `3.11.16`
- Commit: `unknown` (dirty: False)
- Che do: **khong_mqtt**, on dinh 0.2s moi moc

## So do

| So xe | RSS (MB) | Dinh (MB) |
|---:|---:|---:|
| 0 | 36.64 | 36.64 |
| 1 | 36.77 | 36.77 |
| 2 | 36.78 | 36.78 |

## Ket qua khop

- **RAM bien: 0.01 MB cho moi xe them vao**
- Diem chan (chi phi tra mot lan): 36.76 MB
- Suc chua uoc tinh: **~241653 xe** (MemAvailable 3452.2 MB x he so an toan 0.7)

## Diem mu

- **mot_may_mot_lan** - MOT lan lay mau tren MOT may, khong phai phan phoi. Day la so de lap ngan sach may, khong phai benchmark. Chay lai tren may dich truoc khi trich.
- **python_khong_tra_ram** - CPython gan nhu khong tra vung nho da cap ve cho OS, nen VmRSS chi tang. Vi vay do doc lay tu khop tuyen tinh tren NHIEU moc, khong phai hieu cua hai diem - hieu hai diem dinh ca nhieu allocator lan nhieu GC.
- **moi_xe_mot_ket_noi** - Moi xe o day co MQTT client rieng, giong het kien truc hien tai (mot tien trinh = mot xe = mot ket noi). Thiet ke multi-tenant co the dung CHUNG mot ket noi cho N xe, khi do do doc that con thap hon so nay. Nen day van la tran tren, chi la tran chat hon nhieu so voi con so 34,3 MiB/container.
- **chua_do_phia_backend** - Chi do phia XE AO. Backend cung ton them cho moi xe: mot VehicleStateCache (subscribe rieng), mot UiPolicyEmitter, va moi phien tai xe con keo theo mot checkpoint LangGraph InMemorySaver. Phan do nhieu kha nang LON HON phan nay va chua ai do. Dung lap ngan sach chi bang con so o day.
- **khong_co_tai** - Xe dung yen, chi co heartbeat - khong lenh, khong chu ky tu chay. Do luc co tai se cao hon, nhung phan chenh la buffer tam chu khong phai chi phi thuong truc, nen no khong doi ket luan ve suc chua.
