# agent-debate Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          USER PROMPT                                │
│         "Should we use REST or gRPC for the new API?"               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                                 │
│                    (Claude via Agent SDK)                            │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│  │   Config     │  │   Personas   │  │   Prompt Templates       │   │
│  │  providers   │  │  JSON files  │  │  Round 1 / Debate /      │   │
│  │  timeouts    │  │  auto-assign │  │  Dedup / Synthesis       │   │
│  │  max_rounds  │  │  or explicit │  │                          │   │
│  └─────────────┘  └──────────────┘  └──────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
┌───────────────────┐ ┌──────────────┐ ┌──────────────────┐
│  Claude Code      │ │   Codex      │ │   Gemini CLI     │
│  (Agent SDK)      │ │ (subprocess) │ │  (subprocess)    │
│                   │ │              │ │                  │
│  🔒 security      │ │ ⚡ performance│ │ 🏗️ architecture   │
│                   │ │              │ │                  │
│  "Use gRPC for    │ │ "gRPC-Web   │ │ "REST for        │
│   internal, REST  │ │  handles    │ │  everything.     │
│   for public"     │ │  browsers"  │ │  Start simple."  │
└────────┬──────────┘ └──────┬───────┘ └────────┬─────────┘
         │                   │                  │
         └───────────────────┼──────────────────┘
                             │
              PHASE 1: OPENING STATEMENTS
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    DEDUP & ANALYSIS                                  │
│                    (Claude Haiku)                                    │
│                                                                     │
│  Findings:                                                          │
│  ├─ ⚠️  Schema-first design essential (all 3 agents)                │
│  ├─ ⚠️  gRPC superior for internal comms (Claude, Codex)            │
│  └─ ℹ️  Team REST familiarity (Claude, Gemini)                      │
│                                                                     │
│  Disagreements Found:                                               │
│  └─ ❌ Public API format                                            │
│       Claude: REST gateway    Codex: gRPC-Web    Gemini: REST only  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                    disagreements? ──── no ───▶ skip to synthesis
                               │
                              yes
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    TARGETED DEBATE                                   │
│              (same agents, addressing contradictions)                │
│                                                                     │
│  💬 Claude: "REST gateway is pragmatic — third-party devs           │
│             expect OpenAPI docs and curl examples"                   │
│                                                                     │
│  💬 Codex:  "I'll concede partially. If you have external           │
│             consumers, a gateway makes sense."                       │
│                                                                     │
│  💬 Gemini: "I'll revise — protos from day one is reasonable        │
│             for a greenfield project."                               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
              PHASE 3: AGENTS RESPOND TO EACH OTHER
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      SYNTHESIS                                      │
│                    (Claude Sonnet)                                   │
│                                                                     │
│  Recommendation: gRPC-internal, REST-external                       │
│                                                                     │
│  Next Steps:                                                        │
│  1. Define proto schemas first                                      │
│  2. gRPC for internal service calls                                 │
│  3. gRPC-Gateway for public REST                                    │
│  4. Evaluate ConnectRPC for frontends                               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       OUTPUTS                                       │
│                                                                     │
│  📄 debate.json        Structured transcript for web viewer         │
│  📝 Markdown reports   Per-agent responses, dedup, synthesis        │
│  🌐 Web UI             agent-debate ui → browse & explore           │
│  📊 Langfuse traces    Optional observability                       │
└─────────────────────────────────────────────────────────────────────┘


                    ┌─────────────────────┐
                    │   WEB VIEWER (UI)   │
                    │                     │
                    │  Landing Page       │
                    │  ├─ Past debates    │
                    │  ├─ Personas grid   │
                    │  └─ Add persona     │
                    │                     │
                    │  Transcript View    │
                    │  ├─ Opening cards   │
                    │  ├─ Findings table  │
                    │  ├─ Chat debate 💬  │
                    │  └─ Synthesis ✨     │
                    └─────────────────────┘
```
