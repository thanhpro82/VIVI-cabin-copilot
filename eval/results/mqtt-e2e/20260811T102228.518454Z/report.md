# Báo cáo MQTT End-to-End — run `20260811T102228.518454Z`

- Commit: `35d6254a1c2a` trên `test/mqtt-l3-two-process` (**cây làm việc bẩn**)
- Python 3.13.7 · Windows-11-10.0.26200-SP0
- Tầng đã chạy: L0-unit, L1-inmemory, L2-mosquitto, L3-two-process

## Tổng hợp

**173/173 pass**, 0 fail, 0 skip, 163.685s.

## Theo acceptance criteria

| AC | Pass | Fail | Skip |
|---|---:|---:|---:|
| AC1-chain | 69 | 0 | 0 |
| AC1-chain+AC2-topic | 12 | 0 | 0 |
| AC1-chain+AC3-idempotency | 12 | 0 | 0 |
| AC1-chain+AC3-realtime | 5 | 0 | 0 |
| AC2-schema | 7 | 0 | 0 |
| AC3-idempotency | 14 | 0 | 0 |
| AC3-realtime | 6 | 0 | 0 |
| AC3-stale | 23 | 0 | 0 |
| AC3-state_version | 25 | 0 | 0 |

## Theo tầng

| Tầng | Pass | Fail | Skip | Giây |
|---|---:|---:|---:|---:|
| L0-unit | 36 | 0 | 0 | 0.067 |
| L1-inmemory | 120 | 0 | 0 | 30.195 |
| L2-mosquitto | 12 | 0 | 0 | 86.842 |
| L3-two-process | 5 | 0 | 0 | 46.581 |

## Điểm mù — bộ test này KHÔNG chứng minh được gì

- **L0-unit**: Không nói gì về vận chuyển: không broker, không serialize.
- **L1-inmemory**: InMemoryBroker gọi handler đồng bộ ngay trong publish nên hoàn toàn tất định — 0 flaky, nhưng cũng KHÔNG BAO GIỜ tạo ra xen kẽ thời gian thật. Không chứng minh được: QoS 1 duplicate của broker thật, retain qua restart, ACL, Last Will, clean_session, hay reconnect.
- **L2-mosquitto**: Broker thật nhưng vẫn trong một tiến trình pytest: không có HTTP/WS thật, không có backend và simulator chạy như hai tiến trình riêng.
- **L3-two-process**: Hai tiến trình thật nhưng CÙNG một máy, cùng một venv, cùng loopback. KHÔNG chứng minh: image Docker, topology docker-compose, hành vi khi mạng phân mảnh hay có độ trễ, và nhiều xe cùng lúc. Thời gian khởi động ghi ở đây là số đo một lần trên máy dev — nó phụ thuộc nặng vào việc model STT/TTS có sẵn hay chưa (backend warm singleton trong lifespan).

## Case thất bại

Không có.

---

> Thời gian trong case_results.jsonl là số đo MỘT lần chạy trên máy dev, KHÔNG phải benchmark. Không dùng làm bằng chứng hiệu năng.
>
> Bằng chứng thô: `junit.xml` trong cùng thư mục. Thư mục run là bất biến —
> muốn số mới thì chạy lại script, không sửa file cũ.
