# Báo cáo MQTT End-to-End — run `20260809T161533.418052Z`

- Commit: `19d874c37a28` trên `develop` (**cây làm việc bẩn**)
- Python 3.13.7 · Windows-11-10.0.26200-SP0
- Tầng đã chạy: L0-unit, L1-inmemory

## Tổng hợp

**148/148 pass**, 0 fail, 0 skip, 5.31s.

## Theo acceptance criteria

| AC | Pass | Fail | Skip |
|---|---:|---:|---:|
| AC1-chain | 66 | 0 | 0 |
| AC1-chain+AC2-topic | 12 | 0 | 0 |
| AC2-schema | 7 | 0 | 0 |
| AC3-idempotency | 14 | 0 | 0 |
| AC3-realtime | 6 | 0 | 0 |
| AC3-stale | 18 | 0 | 0 |
| AC3-state_version | 25 | 0 | 0 |

## Theo tầng

| Tầng | Pass | Fail | Skip | Giây |
|---|---:|---:|---:|---:|
| L0-unit | 31 | 0 | 0 | 0.054 |
| L1-inmemory | 117 | 0 | 0 | 5.256 |

## Điểm mù — bộ test này KHÔNG chứng minh được gì

- **L0-unit**: Không nói gì về vận chuyển: không broker, không serialize.
- **L1-inmemory**: InMemoryBroker gọi handler đồng bộ ngay trong publish nên hoàn toàn tất định — 0 flaky, nhưng cũng KHÔNG BAO GIỜ tạo ra xen kẽ thời gian thật. Không chứng minh được: QoS 1 duplicate của broker thật, retain qua restart, ACL, Last Will, clean_session, hay reconnect.

## Case thất bại

Không có.

---

> Thời gian trong case_results.jsonl là số đo MỘT lần chạy trên máy dev, KHÔNG phải benchmark. Không dùng làm bằng chứng hiệu năng.
>
> Bằng chứng thô: `junit.xml` trong cùng thư mục. Thư mục run là bất biến —
> muốn số mới thì chạy lại script, không sửa file cũ.
