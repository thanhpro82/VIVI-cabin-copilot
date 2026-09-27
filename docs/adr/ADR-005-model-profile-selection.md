# ADR-005: Offline Model Profile Selection

- Status: Not Yet — hai Q4 candidate đã chạy nhưng đều trượt hard gates
- Date opened: 2026-07-30
- Decision owner: WS1 Voice & Edge, co-reviewed by WS2/WS3/WS4

## Context

MVP cần một primary SLM và một fallback phù hợp CPU simulated-edge. Planning hypothesis là Qwen2.5-3B-Instruct Q4 cho planning/response và Qwen2.5-0.5B-Instruct Q4 cho fallback/router. SPIKE-001 đã benchmark hai profile trên cùng harness, 4 CPU threads, context 4.096 và 20 case control/NLU/plan.

## Alternatives under test

| Option | Intended role | Evidence required |
|---|---|---|
| Qwen2.5-0.5B-Instruct Q4_K_M | Primary nếu đủ quality hoặc fallback | 30-case PoC, cold/warm latency, peak RAM |
| Qwen2.5-3B-Instruct Q4_K_M | Primary candidate | Cùng protocol |
| Qwen2.5-3B-Instruct Q8_0 | Quality comparison | Chạy sau hai candidate bắt buộc |

## Decision rule

Candidate phải đạt offline, schema, citation và safety hard gates trong [`../tasks/SPIKE-001-offline-ai-vertical-slice.md`](../tasks/SPIKE-001-offline-ai-vertical-slice.md). Candidate vượt gates được xếp theo quality 40%, latency 25%, memory/size 15%, integration stability 10% và operational simplicity 10%.

## Evidence

| Profile | Run ID | Schema | Tool exact | p50 | p95 | Peak RSS | Kết quả |
|---|---|---:|---:|---:|---:|---:|---|
| Qwen2.5-0.5B Q4_K_M | `20260730T100805.585998Z` | 55% | 15% | 3.864 ms | 10.115 ms | 598,9 MiB | Fail |
| Qwen2.5-3B Q4_K_M | `20260730T101024.064499Z` | 70% | 30% | 11.193 ms | 40.272 ms | 2.088,1 MiB | Fail |

Raw evidence và voice results nằm trong [`../../eval/results/report.md`](../../eval/results/report.md). Cả hai model đều nằm dưới budget RAM 8 GiB nhưng trượt schema, tool exact và latency gates.

## Current decision

**Not Yet: chưa chọn primary hoặc fallback SLM.** 3B tốt hơn tương đối về schema/tool quality nhưng không đủ để được chấp nhận và chậm hơn đáng kể. 0.5B chưa được gán làm fallback vì cũng không đạt schema gate cho capability hiện tại. Không chạy Q8 trong vòng này: tăng precision không giải quyết nguyên nhân chính là planning contract quá rộng, exact-argument quality thấp và CPU latency cao.

Thử nghiệm kế tiếp được giới hạn như sau:

1. Dùng deterministic intent/slot routing cho các lệnh xe phổ biến, với schema một tool/lần.
2. Chỉ dùng 3B cho explanation/RAG composition hoặc plan hiếm sau router.
3. Rerun đúng 20 case và chỉ mở Q8 nếu Q4 mới đạt schema/tool gates nhưng còn thiếu quality biên.

## Required evidence before acceptance

- Run IDs và immutable manifests: **đã có cho LLM/STT/TTS**.
- Per-case tool/plan: **đã có cho 20 LLM cases**; RAG/safety real-model E2E còn mở.
- Cold/warm latency và peak RSS: **đã có**.
- Network-disabled trace: **chưa chạy; cần phê duyệt thay đổi network state**.
- Reviewer sign-off của WS2, WS3 và WS4.

## Consequences after acceptance

- Primary profile được pin theo release manifest.
- Fallback chỉ được giao tập capability đã vượt eval.
- Mỗi model/prompt/tool/index change phải chạy regression.
- Q4/Q8 claims chỉ dùng measured artifact results.
