# Architecture Diagrams

## 1. System context

```mermaid
flowchart LR
    Driver(("Tài xế"))
    Engineer(("Kỹ sư hệ thống"))
    Copilot["VIVI Cabin Copilot\nOffline Edge Prototype"]
    Manual["Sổ tay xe\nđược phép sử dụng"]
    Models["Model files\nđã tải trước"]

    Driver -->|"Voice, text, approval"| Copilot
    Copilot -->|"Voice, state, citation"| Driver
    Engineer -->|"Configure, run eval"| Copilot
    Copilot -->|"Trace, metrics, report"| Engineer
    Manual -->|"Offline ingestion"| Copilot
    Models -->|"Offline inference"| Copilot
```

Runtime P0 không có external cloud actor. Việc tải model và tài liệu xảy ra trước offline drill.

## 2. Use case view

```mermaid
flowchart LR
    Driver((Tài xế))
    Engineer((Kỹ sư))
    subgraph VIVI["VIVI Cabin Copilot"]
        Speak["Ra lệnh bằng giọng nói"]
        Multi["Thực hiện nhiều bước"]
        Ask["Hỏi sổ tay có citation"]
        Control["Điều khiển simulator"]
        Approve["Approve/reject actuator"]
        Recover["Phục hồi khi không chắc"]
        Observe["Xem trace và latency"]
        Evaluate["Chạy golden eval"]
        Configure["Chọn model profile"]
    end
    Driver --> Speak
    Driver --> Multi
    Driver --> Ask
    Driver --> Control
    Driver --> Approve
    Driver --> Recover
    Engineer --> Observe
    Engineer --> Evaluate
    Engineer --> Configure
    Control -. "requires" .-> Approve
```

## 3. Container/component view

```mermaid
flowchart TB
    subgraph Browser["Host Browser"]
        DriverUI["Driver IVI"]
        EngineerUI["Engineering Dashboard"]
        Audio["Media capture/playback"]
    end

    subgraph Compose["Docker Compose — edge-cpu profile"]
        Web["Next.js Web"]
        API["FastAPI Gateway"]
        Voice["Voice Service"]
        Agent["LangGraph Agent"]
        Policy["Safety Policy"]
        Executor["Tool Executor"]
        LLM["llama.cpp Server"]
        RAG["RAG Service"]
        Eval["Eval Worker"]
        Broker["Mosquitto MQTT"]
        Vehicle["Vehicle Digital Twin"]
        DB[("SQLite")]
        Vector[("FAISS Index")]
        Files[("Models / Manuals / POI")]
    end

    DriverUI <--> Web
    EngineerUI <--> Web
    Audio <--> DriverUI
    Web <--> API
    API <--> Voice
    API <--> Agent
    API <--> DB
    Agent <--> LLM
    Agent <--> RAG
    Agent --> Policy
    Policy --> Executor
    Executor <--> Broker
    Broker <--> Vehicle
    RAG <--> Vector
    RAG --> Files
    LLM --> Files
    Voice --> Files
    Eval --> API
    Eval --> Files
```

## 4. Voice and agent data flow

```mermaid
flowchart LR
    PCM["PCM audio chunks"] --> VAD["VAD"]
    VAD --> STT["STT"]
    STT --> Transcript["TranscriptEvent"]
    Transcript --> Normalize["Normalize"]
    Normalize --> Router{"Router"}
    Router -->|"manual"| Knowledge["Knowledge subgraph"]
    Router -->|"control"| Control["Control subgraph"]
    Router -->|"mixed"| Planner["Multi-step planner"]
    Knowledge --> Merge["Merge response/plan"]
    Control --> Merge
    Planner --> Merge
    Merge --> Safety["Deterministic safety"]
    Safety -->|"S3"| Block["Block"]
    Safety -->|"S2"| HITL["Interrupt + approval"]
    Safety -->|"S0/S1"| Execute["Execute"]
    HITL -->|"approve"| Execute
    HITL -->|"reject/expire"| Compose["Compose result"]
    Execute --> Observe["MQTT observation"]
    Observe --> Compose
    Block --> Compose
    Compose --> TTS["TTS audio"]
```

## 5. RAG grounded flow

```mermaid
flowchart TB
    Query["User question"] --> Rewrite["Context-aware rewrite"]
    Rewrite --> Embed["query: embedding"]
    Embed --> Retrieve["FAISS top 8 + metadata filter"]
    Retrieve --> Grade["Relevance/evidence grade"]
    Grade --> Enough{"Evidence đủ?"}
    Enough -->|"No"| Refuse["Grounded refusal"]
    Enough -->|"Yes"| Generate["Answer only from evidence"]
    Generate --> Resolve["Citation resolver"]
    Resolve --> Valid{"Citation valid?"}
    Valid -->|"No"| Refuse
    Valid -->|"Yes"| Answer["Answer + document/section/page"]
```

## 6. Multi-step/HITL sequence

```mermaid
sequenceDiagram
    actor D as Tài xế
    participant UI as IVI
    participant V as Voice
    participant A as Agent
    participant S as Safety
    participant P as POI
    participant M as MQTT Simulator

    D->>UI: Nói yêu cầu hỗn hợp
    UI->>V: Audio stream
    V-->>A: TranscriptEvent
    A->>P: search_nearby(cafe)
    P-->>A: POI candidates
    A->>A: Tạo ActionPlan có dependency
    A->>S: validate(plan, vehicle_snapshot)
    S-->>UI: ApprovalRequest cho HVAC
    UI-->>D: Đọc và hiển thị thay đổi
    D->>UI: Đồng ý
    UI-->>A: resume(plan_id, approve)
    A->>M: set_hvac_temperature(24)
    M-->>A: ToolResult + state_version
    A->>M: set_navigation(destination_id)
    M-->>A: ToolResult + route state
    A-->>UI: Kết quả từng bước + timings
    UI-->>D: Phản hồi giọng nói
```

## 7. Safety decision flow

```mermaid
flowchart TD
    Plan["ActionPlan"] --> Schema{"Schema/range valid?"}
    Schema -->|"No"| Reject["Reject and log"]
    Schema -->|"Yes"| Snapshot{"Fresh vehicle state?"}
    Snapshot -->|"No"| Refresh["Refresh and re-plan"]
    Snapshot -->|"Yes"| Forbidden{"S3 invariant violated?"}
    Forbidden -->|"Yes"| Block["Block without approval"]
    Forbidden -->|"No"| Actuator{"Changes actuator?"}
    Actuator -->|"No"| Execute["Execute S0/S1"]
    Actuator -->|"Yes"| Approval["Create expiring ApprovalRequest"]
    Approval --> Decision{"Approve with same state version?"}
    Decision -->|"No/expired"| Cancel["Cancel"]
    Decision -->|"Yes"| Execute
```

## 8. Deployment view

```mermaid
flowchart TB
    subgraph Laptop["PC/Laptop — Windows or Linux"]
        Browser["Browser + microphone/speaker"]
        subgraph Docker["Docker Engine"]
            Frontend["ivi-web :3000"]
            Backend["api :8000"]
            Voice["voice internal"]
            Agent["agent internal"]
            LLM["llm :8080 internal"]
            MQTT["mqtt :1883"]
            Simulator["vehicle-simulator internal"]
            Eval["eval on-demand"]
        end
        Volumes[("Local volumes\nmodels, index, db, reports")]
    end

    Browser <--> Frontend
    Frontend <--> Backend
    Backend <--> Voice
    Backend <--> Agent
    Agent <--> LLM
    Agent <--> MQTT
    MQTT <--> Simulator
    Eval --> Backend
    Voice --> Volumes
    Agent --> Volumes
    LLM --> Volumes
    Eval --> Volumes
```

## Component responsibility summary

| Component | Owns | Does not own |
|---|---|---|
| Voice | Audio/STT/TTS và timing | Intent, tool hoặc safety |
| Agent | Routing, plan, RAG orchestration | Quyền cuối cho actuator |
| Safety | Policy, state guard, approval requirement | Natural-language planning |
| Executor | Idempotent tool calls và observations | Chọn tool |
| Simulator | Vehicle invariants và state transition | User intent |
| IVI | Interaction và rendering | Business authorization |
| API | Auth, validation, sessions, event routing | Model reasoning |
| Eval | Measurement và reports | Thay đổi production config tự động |

