<!--
marp: true
theme: default
size: 16:9
paginate: true
backgroundColor: #fafafa
header: 'LT-Sentinel · lablab TechEx · Track 1'
footer: '2026-05-19 · open-source · MIT'
style: |
  section { font-family: -apple-system, "Segoe UI", system-ui, sans-serif; }
  h1 { color: #1f3a93; }
  h2 { color: #1f3a93; border-bottom: 2px solid #1f3a93; padding-bottom: 4px; }
  code { background: #f0f0f5; padding: 2px 6px; border-radius: 3px; }
  pre { background: #1e1e2e; color: #eee; padding: 12px; border-radius: 6px; font-size: 18px; }
  table { font-size: 22px; }
  th { background: #1f3a93; color: white; }
  .small { font-size: 18px; color: #555; }
-->

# LT-Sentinel

### A long-term-attack monitoring layer for Veea Lobster Trap

<br>

**lablab.ai TechEx Hackathon · Track 1**
Agent Security & AI Governance · Powered by Veea Lobster Trap

<br>
<br>

<span class="small">2026-05-19 · MIT-licensed · single-engineer submission · built on top of Veea LT, not a fork</span>

---

## What Lobster Trap already does well

* Single-event deep prompt inspection (DPI) — sub-ms regex
* 8-action policy table (ALLOW / DENY / LOG / MODIFY / QUARANTINE / HUMAN_REVIEW / RATE_LIMIT / REDIRECT)
* First-match-wins, declared-vs-detected mismatches surfaced natively
* Drop-in OpenAI-compatible reverse proxy

## What LT doesn't have (by design)

LT is **stateless across events**. It can't see:

| Attack class | Why LT misses it |
|---|---|
| **A. Slow injection** | each turn alone is borderline |
| **B. Trust-then-burst** | 30 benign turns leave no trace |
| **C. Slow tool-result poisoning** | each tainted record looks like noise |

LT-Sentinel adds **cross-event memory** to LT.

---

## Sentinel in one diagram

```
agents → Sentinel reverse proxy (:8080)
            │ atomic current_tier_port
            ├─→ LT-Trust    :18081   policy_trust.yaml     (6 + 2 rules)
            ├─→ LT-Observe  :18082   policy_observe.yaml   (13 + 3 rules)
            └─→ LT-Lockdown :18083   policy_lockdown.yaml  (14 + 4 rules)
                  │   │   │
                  ▼   ▼   ▼  audit-log JSONL (append-only)
            Sentinel monitor (tail × 3, merge by ts)
                  │
                  ▼   per-event:   sentinel_events.jsonl
                       per-swap:   sentinel_mode_changes.jsonl
                       per-agent:  trust_history.jsonl
```

* 3 LT processes stay up the whole demo · no LT source change · zero downtime tier swap
* `agent_id` declarative (production needs OAuth/mTLS in front)

---

## The math (every constant cited)

| Param | Value | Source |
|---|---|---|
| EWMA λ | **0.05** | Lucas & Saccucci 1990, *Technometrics* 32:1 (range floor) |
| CUSUM k | 0.5 σ | Page 1954, *Biometrika* 41 |
| CUSUM h | 4 σ | Hawkins & Olwell 1998 (k=0.5σ → ARL₀ ≈ 168) |
| Window N | 30 | Münz & Carle 2008, *Traffic Anomaly Detection* |
| p-chart σ | √(μ(1−μ)/N) | Montgomery 2009 §7.2 |
| Baseline prior | μ = 0.05 | ASB ICLR 2025 (low end) |
| TrustScore | `clamp(1 − (EWMA_OER − μ) / (3σ), 0, 1)` | SPC control limits |
| Tier | trust ≥ 0.33 · observe ∈ \[0.10, 0.33\) · lockdown < 0.10 | fixed |

Measured `μ_dev = 0` on N=220 happy-path (judge rejects intent-classifier noise) → adopted prior, kept literature defaults; design doc transparent about both numbers.

---

## Live demo result (one Sentinel start, 184 events)

![bg right:55% fit](../sentinel/data/demo_canonical/chart_trust_timeseries.png)

| agent | scenario | final trust | final tier |
|---|---|---|---|
| finance | (control) | 1.000 | trust |
| router | A slow inject | 0.870 | trust |
| hr_agent | B trust-then-burst | 0.182 | **observe** |
| it_agent | C tool poison | 0.000 | **lockdown** |

2 tier swaps captured, each with full evidence trail.

---

## Audit trail — what a regulator sees

```json
{
  "from_tier": "observe",
  "to_tier": "lockdown",
  "trigger_agent": "it_agent",
  "trigger_trust_score": 0.025,
  "threshold_crossed": "τ_low=0.1",
  "all_agents_trust_snapshot": {
    "finance_agent": 1.0, "router": 0.87,
    "hr_agent": 0.18,    "it_agent": 0.025
  },
  "recent_violation_events": ["req-37","req-45","req-53",
                              "req-85","req-86","req-88",
                              "req-5","req-6","req-7"],
  "policy_yaml_applied": "policy_lockdown.yaml",
  "reason_summary": "it_agent TrustScore=0.025 crossed τ_low=0.1; transitioning observe → lockdown"
}
```

Every `req-N` chains into `sentinel_events.jsonl` → LT's own `lt_audit_*.jsonl`.

---

## Track 1 evaluation alignment

| Criterion | Where LT-Sentinel lands |
|---|---|
| **Application of Technology** | LT as floor (Veea's positioning); orthogonal stateful layer; non-trivial multi-process orchestration |
| **Originality** | OER from *Trust Paradox* (arxiv 2510.18563 / 2025); SPC framing for LLM agent governance — not off-the-shelf |
| **Business Value** | full regulator-readable chain in JSONL (the literal "audit trails a regulator could read" bonus) |
| **Presentation** | one chart visualises 4 agents × 3 attack types × 2 tier transitions |
| **Veea bonus** | declared-vs-detected mismatches surfaced per-agent + cumulative versions caught |

---

## What's NOT in scope

* not a fork of LT (vendored MIT-licensed source, untouched)
* not a single-event DPI (LT does that)
* not an identity / authn system (`agent_id` is declarative — production needs OAuth/mTLS)
* not per-identity policy: LT's current policy YAML doesn't accept `agent_id` as condition → tier change is **global** ("连坐制"). Per-identity policy is an upstream LT change away.
* not adaptive-attacker robust: SPC has a known blind spot for adversaries tuning rate just under threshold (DESIGN.md §7.4). v2 = randomised thresholds + RL-based detector.

---

## Repro in 4 commands

```bash
cd lobstertrap && go build -o lobstertrap.exe . && cd ..
cd sentinel && py -m pip install -e .[viz,dev]
py -m lt_sentinel.cli run        # terminal 1

py -m scenarios.demo_run         # terminal 2 (drives all 3 attacks)
py -m scenarios.visualize        # render the chart
```

Then inspect `sentinel/data/sentinel_mode_changes.jsonl` for the regulator-readable transition trail.

---

## Thanks

* **Veea** for open-sourcing Lobster Trap — the floor we built on
* **The Trust Paradox in LLM-Based Multi-Agent Systems** (arxiv 2510.18563, 2025) for the OER definition
* **Münz & Carle 2008** for the SPC-on-network-traffic prior we re-applied to LLM agents
* **Lucas & Saccucci 1990** / **Page 1954** / **Hawkins & Olwell 1998** / **Montgomery 2009** — the SPC literature anchoring every constant

GitHub: *(repo URL after submission push)*
Live demo URL: *(set when hosted — single-machine + Ollama)*
