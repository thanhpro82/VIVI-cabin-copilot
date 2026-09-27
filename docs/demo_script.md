# Five-Minute Offline Demo Script

## Preconditions

This is a **Planned** script. Use only the simulator and local artifacts whose manifests/checksums have passed preflight. Before the clock, `/healthz` must report all eight required components ready: `backend`, `llm`, `mqtt`, `vehicle_simulator`, `stt`, `tts`, `rag_index`, and `sqlite`. Model selection in ADR-005 remains **Not Yet**; the fail-closed sample cannot reach demo readiness until benchmark evidence selects and configures a manifested profile/path.

## Timed flow

| Time | Presenter action | Required evidence |
|---|---|---|
| 0:00–0:30 | Disable external network access. Log in as Driver. | Offline indicator, Driver role, and local health are visible. |
| 0:30–1:15 | Nói: “Tìm quán cà phê gần đây, đặt điều hòa 24 độ rồi dẫn đường tới đó.” | S0 local POI produces one observable persisted, non-executable `PlanningResolution` terminal outcome before admission. Only the POI candidate step is removed and its `destination_ref` rewritten in the in-memory candidate; the canonical S1-only HVAC + navigation plan then executes without HITL. |
| 1:15–1:55 | Hỏi: “Đèn cảnh báo áp suất lốp này có nghĩa là gì?”, mở citation, rồi hỏi một câu không có evidence để thấy grounded refusal. | Citation identifies local document/section/page/`chunk_id` and supported excerpt; fallback says it lacks sufficient grounded evidence. |
| 1:55–2:35 | Đặt simulator speed 0, gear P. Nói: “Mở kính bên lái 30%.” Khi card xuất hiện, nói trong một turn mới: “Đồng ý.” | S2 card is the session's only pending approval. The new voice turn emits typed `approval.intent.detected` handoff and completes once without committing; IVI calls REST `/api/v1/approvals/{approval_id}/decision`, then state-version/admission and MQTT transition are shown on the original turn. |
| 2:35–3:05 | Đặt simulator speed 30, gear D. Nói: “Mở cửa bên lái.” | Candidate/planned tool is `set_door_state`, deterministic policy assigns S3, executed tools remain empty, and no approval/MQTT/state transition occurs. |
| 3:05–4:10 | Switch to the minimal read-only Engineer view. | Safe trace shows route/stage/admission; metrics show per-stage latency, model tokens/s + RSS/profile, MQTT latency/errors, groundedness/abstention, safety/approval and action-audit aggregates. No raw prompt/audio/secret/unrestricted transcript is present. |
| 4:10–5:00 | Show metrics and saved evidence. | Offline drill record, latency/eval evidence, action audit, checksums/versions, and ADR-005 decision of **Not Yet** unless evidence has changed it. |

No HVAC command requires approval in this flow. S1 is direct; S2 is voice-first approval; S3 is blocked.

## Fallbacks

| Failure | Safe fallback |
|---|---|
| Voice/STT fails | Chỉ khi simulator xác nhận xe đang đỗ và backend `ui_policy.allow_text_input=true`, nhập cùng yêu cầu bằng text; khi moving thì không mở text fallback. Luôn giữ trace và safety policy. |
| Coffee/POI returns zero results | Explain that only the versioned local fixture is in scope; clarify the destination and show that no navigation or HVAC side effect occurred for that intent. |
| Citation unavailable | Show the grounded refusal; do not answer from unsupported memory. |
| Voice approval is ambiguous or no approval is pending | Show the approval-intent turn's failed/canceled terminal state; do not call REST or execute. |
| REST approval is rejected, expired, state/plan-invalidated, or predicate-failed | Terminalize the original command once with the matching reason; show zero consume/group/MQTT and require a new plan when appropriate. |
| MQTT/simulator heartbeat fails | Keep controls read-only and show the health/triage state. |
| LLM is unavailable | Demonstrate deterministic routes and explicit degradation; do not fabricate an agent result. |
| External network appears reachable | Stop the demo claim, re-disable it, and restart the offline drill. |

## Presenter checks

- Confirm the active Driver or Engineer role before showing role-scoped data.
- Do not present a planned Compose command, model profile, evaluation result, or OTA capability as implemented without linked evidence.
- Narrate the difference between policy admission and execution: the moving-door request is blocked before approval, while the stationary-window request is admitted only after voice approval and fresh state validation.
