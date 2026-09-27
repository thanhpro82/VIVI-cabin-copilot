# Báo cáo MQTT End-to-End — run `20260820T040612.369313Z`

- Commit: `e45f4c83c341` trên `feat/issue-183-kenh-harness-toc-do` (**cây làm việc bẩn**)
- Python 3.11.9 · Windows-10-10.0.26200-SP0
- Tầng đã chạy: L0-unit, L1-inmemory, L2-mosquitto, L3-two-process

## Tổng hợp

**209/209 pass**, 0 fail, 0 skip, 157.685s.

## Theo acceptance criteria

| AC | Pass | Fail | Skip |
|---|---:|---:|---:|
| AC1-chain | 73 | 0 | 0 |
| AC1-chain+AC2-topic | 12 | 0 | 0 |
| AC1-chain+AC3-idempotency | 13 | 0 | 0 |
| AC1-chain+AC3-realtime | 5 | 0 | 0 |
| AC2-schema | 7 | 0 | 0 |
| AC3-idempotency | 14 | 0 | 0 |
| AC3-realtime | 6 | 0 | 0 |
| AC3-stale | 23 | 0 | 0 |
| AC3-state_version | 44 | 0 | 0 |
| unmapped | 12 | 0 | 0 |

## Theo tầng

| Tầng | Pass | Fail | Skip | Giây |
|---|---:|---:|---:|---:|
| L0-unit | 49 | 0 | 0 | 0.076 |
| L1-inmemory | 130 | 0 | 0 | 28.394 |
| L2-mosquitto | 13 | 0 | 0 | 94.367 |
| L3-two-process | 5 | 0 | 0 | 34.736 |
| unmapped | 12 | 0 | 0 | 0.112 |

## Điểm mù — bộ test này KHÔNG chứng minh được gì

- **L0-unit**: Không nói gì về vận chuyển: không broker, không serialize.
- **L1-inmemory**: InMemoryBroker gọi handler đồng bộ ngay trong publish nên hoàn toàn tất định — 0 flaky, nhưng cũng KHÔNG BAO GIỜ tạo ra xen kẽ thời gian thật. Không chứng minh được: QoS 1 duplicate của broker thật, retain qua restart, ACL, Last Will, clean_session, hay reconnect.
- **L2-mosquitto**: Broker thật nhưng vẫn trong một tiến trình pytest: không có HTTP/WS thật, không có backend và simulator chạy như hai tiến trình riêng.
- **L3-two-process**: Hai tiến trình thật nhưng CÙNG một máy, cùng một venv, cùng loopback. KHÔNG chứng minh: image Docker, topology docker-compose, hành vi khi mạng phân mảnh hay có độ trễ, và nhiều xe cùng lúc. Thời gian khởi động ghi ở đây là số đo một lần trên máy dev — nó phụ thuộc nặng vào việc model STT/TTS có sẵn hay chưa (backend warm singleton trong lifespan).

## Case thất bại

Không có.

## Case chưa được phân loại

12 case thuộc file chưa khai trong `_FILE_MAP` của `scripts/report_mqtt_e2e.py` — bảng theo AC ở trên **chưa tính** chúng:

- `test_sim_harness.py`

---

> Thời gian trong case_results.jsonl là số đo MỘT lần chạy trên máy dev, KHÔNG phải benchmark. Không dùng làm bằng chứng hiệu năng.
>
> Bằng chứng thô: `junit.xml` trong cùng thư mục. Thư mục run là bất biến —
> muốn số mới thì chạy lại script, không sửa file cũ.
