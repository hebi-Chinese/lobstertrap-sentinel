<!--
marp: true
theme: default
size: 16:9
paginate: false
backgroundColor: #0f1117
color: #e6e6ea
style: |
  section {
    font-family: "Segoe UI", system-ui, sans-serif;
    padding: 56px 64px;
  }
  h1 { color: #6ea8ff; font-size: 52px; margin-bottom: 8px; }
  h2 { color: #6ea8ff; font-size: 38px; border-bottom: 2px solid #2a3550; padding-bottom: 6px; }
  h3 { color: #9db4d8; font-weight: 500; }
  strong { color: #ffd166; }
  code { background: #1c2233; color: #8be9c0; padding: 2px 7px; border-radius: 4px; }
  pre { background: #161b29; color: #d6dae6; padding: 18px; border-radius: 8px; font-size: 21px; line-height: 1.45; }
  table { font-size: 25px; }
  th { background: #1f3a93; color: #fff; }
  td { background: #161b29; }
  .cap { color: #9db4d8; font-size: 24px; }
  .tag { color: #6ea8ff; font-size: 22px; letter-spacing: 1px; }
  .big { font-size: 30px; line-height: 1.5; }
  ul { font-size: 27px; line-height: 1.6; }
-->

<!-- marp slide 1 of 5  ->  video slide 1 (Title) -->

<span class="tag">LABLAB.AI TECHEX HACKATHON · TRACK 1 — AGENT SECURITY & AI GOVERNANCE</span>

# LT-Sentinel

### A long-term-attack monitoring layer for Veea Lobster Trap

<br>

<span class="big">A sidecar that gives Lobster Trap something it doesn't have today —
<strong>memory across events</strong>.</span>

<br>

<span class="cap">single-engineer submission · MIT-licensed · built on top of Veea LT, not a fork</span>

---

<!-- marp slide 2 of 5  ->  video slide 2 (Problem) -->

## The gap: single-event inspection is blind to slow attacks

Lobster Trap does **single-event deep prompt inspection** brilliantly — sub-ms regex,
8 policy actions. But it is **stateless across events**.

| Attack class | Why LT alone misses it |
|---|---|
| **A · Slow injection** | `ignore your rules` dripped across many turns — each turn looks benign |
| **B · Trust-then-burst** | 30 perfect turns leave no trace, then 1 extraction attempt |
| **C · Tool-result poisoning** | each tainted tool return looks like noise — the pattern accumulates |

<span class="big">LT-Sentinel adds the **cross-event memory** that catches all three.</span>

---

<!-- marp slide 3 of 5  ->  video slide 3 (Architecture) -->

## Architecture — 3 LT instances, 1 atomic proxy

```
user → LangGraph Router → HR / Finance / IT worker → ToolNode (Chroma RAG)
                                │
                                ▼
        Sentinel reverse proxy  :8080   (atomic current-tier pointer)
              ├─→ LT-Trust     :18081   policy_trust.yaml
              ├─→ LT-Observe   :18082   policy_observe.yaml
              └─→ LT-Lockdown  :18083   policy_lockdown.yaml
                    │   │   │
                    ▼   ▼   ▼   audit-log JSONL  ──►  Sentinel monitor
                                       per-agent OER → EWMA → CUSUM → TrustScore
```

- 3 LT processes stay up the whole run — **no restart, no LT source change**
- TrustScore crosses a threshold → proxy pointer swings atomically → **zero-downtime tier swap**

---

<!-- marp slide 4 of 5  ->  video slide 9 (Audit trail) -->

## Audit trail — what a regulator reads

```json
{
  "from_tier": "trust",  "to_tier": "lockdown",
  "trigger_agent": "router",
  "trigger_trust_score": 0.047,
  "threshold_crossed": "τ_low=0.1",
  "all_agents_trust_snapshot": {
    "router": 0.047, "finance_agent": 1.0,
    "hr_agent": 0.762, "it_agent": 1.0 },
  "recent_violation_events": ["req-39","req-52","req-53", "..."],
  "policy_yaml_applied": "policy_lockdown.yaml",
  "reason_summary": "router TrustScore=0.047 crossed τ_low=0.1 ..."
}
```

Every `req-N` chains into `sentinel_events.jsonl` → LT's own audit log. Recoveries logged with the same shape.

---

<!-- marp slide 5 of 5  ->  video slide 10 (Wrap) -->

## Built, tested, open-source

| | |
|---|---|
| **Application of Tech** | LT as floor; orthogonal stateful SPC layer; multi-process orchestration |
| **Originality** | OER (*Trust Paradox*, 2025) + SPC control charts for LLM-agent governance |
| **Business Value** | full regulator-readable audit chain in JSONL |
| **Veea bonus** | declared-vs-detected mismatches surfaced per-agent |

39 unit tests · 220 calibration chains · idle-decay (10-min half-life) · startup replay

<span class="cap">Thanks to **Veea** for open-sourcing the floor, and to **lablab** for the ceiling.</span>
