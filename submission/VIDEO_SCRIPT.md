# Video Presentation Script — LT-Sentinel

**Target**: lablab Track 1 submission. Max **5 minutes**, MP4.
**Style**: screencast with voiceover. No talking head.
**Tools**: OBS Studio (free) or Windows Game Bar for capture; any editor for trimming. Voice can be recorded in audacity then mixed.

---

## Opening shot

**0:00 – 0:10 — Title card (static slide)**

* On-screen text:
  > **LT-Sentinel** — a long-term-attack monitoring layer on top of Veea Lobster Trap
  > Lablab.ai TechEx Hackathon · Track 1 (Agent Security & AI Governance)

Voiceover (read in ~10s):

> "This is LT-Sentinel — a sidecar that gives Veea's Lobster Trap something it doesn't have today: memory."

---

## Problem framing

**0:10 – 0:50 — Slide: the gap (animated diagram or static)**

On-screen: split screen.
* Left half: "Single-event DPI" — a row of green checkmarks blocking ⚠️ icons.
* Right half: "Cross-event patterns invisible to DPI" — 30 small benign icons followed by 1 attack icon at the end; or 20 small benign icons each with a tiny red dot that accumulate.

Voiceover (~40s):

> "Lobster Trap is excellent at single-event deep prompt inspection. Sub-millisecond regex DPI, eight policy actions, P4-style match-action tables. But by design, it's stateless. So it can't see three attack patterns that matter most in multi-agent systems."
>
> "First — slow injection. An attacker drips little pieces of *ignore your rules* across many turns; each turn alone looks benign. Second — trust-then-burst. An agent behaves perfectly for thirty turns, then makes one extraction attempt. Third — slow tool-result poisoning. Each tainted tool return looks like noise, but the pattern accumulates."
>
> "LT alone misses these. LT-Sentinel is the layer that catches them."

---

## Architecture in one diagram

**0:50 – 1:30 — Slide: architecture diagram**

On-screen: the ASCII diagram from README.md, rendered cleanly:

```
agents → Sentinel reverse proxy (:8080)
              │
              ├─→ LT-Trust :18081 (baseline policy)
              ├─→ LT-Observe :18082 (heightened policy)
              └─→ LT-Lockdown :18083 (strictest policy)
                    │   │   │
                    ▼   ▼   ▼  audit-log JSONL
              Sentinel monitor
                    │
                    ▼  sentinel_events + mode_changes + trust_history
```

Voiceover (~40s):

> "Three Lobster Trap instances run in parallel, each loaded with one of three policy YAMLs — Trust, Observe, Lockdown. They never restart. Sentinel adds a tiny reverse proxy on port 8080 that routes traffic to whichever LT instance corresponds to the current trust tier."
>
> "Sentinel tails all three audit logs, computes a per-agent OER over a sliding 30-event window, runs that through an EWMA — Lucas and Saccucci's 1990 control chart — and a CUSUM. The result is a per-agent TrustScore. If any agent's TrustScore crosses a threshold, Sentinel atomically swings the reverse-proxy pointer to the new tier. In-flight requests against the old tier finish; new requests instantly route through the new policy. No LT restart, no source modification."

---

## Live demo

**1:30 – 3:30 — Terminal + chart**

Setup: split screen — left side a terminal running `lt-sentinel run`, right side the chart updating live (or a pre-rendered chart that you scrub through).

Talk track and visible commands:

* **(1:30)** Switch to terminal: run `lt-sentinel show-config`. Read out the SPC parameters briefly. Voiceover:
  > "Every knob is anchored to literature. λ from Lucas and Saccucci 1990, k and h from Page 1954 and Hawkins and Olwell 1998, window from Münz and Carle 2008, baseline prior from Agent Security Bench at ICLR 2025."

* **(1:50)** Run `lt-sentinel run`. As the three LT processes spawn:
  > "Three Lobster Trap instances coming up. Trust on 18081, Observe on 18082, Lockdown on 18083. Sentinel proxy on 8080."

* **(2:05)** In a second terminal, run `py -m scenarios.demo_run --qps 8`.

  * Show first few warm-up turns scrolling past (all green `verdict=ALLOW`).
  * As Scenario A turns roll: point out the `block_prompt_injection` DENYs.
  * As Scenario B turns roll: 20 benign HR turns, then the 4-burst ladder — first burst LT-DENY'd, next 3 progressively riskier.
  * As Scenario C turns roll: 8 tool returns escalating, multiple different rules hit.

* **(3:05)** Cut to the rendered chart PNG (`sentinel/data/demo_canonical/chart_trust_timeseries.png`). Pan across it left to right.
  > "Four agents, one chart. Green band is Trust. Yellow is Observe. Red is Lockdown."
  > "Finance stays at one — control. Router slow-injects — saw-tooth. HR holds at one for thirty turns then drops in four steps and crosses τ_high. IT poisons through and lands in Lockdown."
  > "Two dashed lines mark the global tier swaps. Sentinel labelled each one with which agent triggered it."

---

## Audit-trail story (the Veea bonus)

**3:30 – 4:20 — Show JSONL records**

Open `sentinel/data/demo_canonical/sentinel_mode_changes.jsonl` in a viewer or terminal. Highlight one record at a time.

Voiceover (~50s):

> "This is what Veea's brief called *audit trails a regulator could read*."
>
> "Each tier transition records the trigger agent — who tipped the system over. The trigger's TrustScore at the moment of crossing. Which threshold was crossed. A complete snapshot of every other agent's TrustScore at that instant — so you can prove the other agents weren't involved. The list of recent violating request IDs as evidence — those chain back through `sentinel_events.jsonl` into Lobster Trap's own audit log. The exact policy YAML that became active. And a one-line human-readable summary."
>
> "Open one of those request IDs in the events log — risk score, mismatches, rule name, the action LT took. That's the chain of evidence."

---

## Wrap

**4:20 – 5:00 — Slide: Track 1 alignment + what's next**

On-screen bullets:

* Application of Technology — LT as foundation; orthogonal cross-event layer
* Originality — OER (Trust Paradox 2025) + SPC framing for LLM agent governance
* Business Value — full audit chain in JSONL, regulator-readable
* Veea bonus — native declared-vs-detected mismatches surfaced per-agent
* Future work — OAuth/mTLS identity, per-identity policy, adaptive-attacker robustness

Voiceover (~40s):

> "Forty lines of Python policy YAML, six hundred lines of Sentinel runtime, twenty-eight unit tests, two hundred and twenty calibration chains. Everything in one MIT-licensed repo, on top of MIT-licensed Lobster Trap."
>
> "Per-identity policy switching is the obvious next step but it needs an upstream change in Lobster Trap to accept `agent_id` as a policy condition field. We flagged that explicitly in the design doc."
>
> "Thanks to Veea for open-sourcing the floor, and to lablab for the ceiling."

---

## Production checklist

* [ ] Pre-render the canonical chart (it's already at `sentinel/data/demo_canonical/chart_trust_timeseries.png`).
* [ ] Pre-cache the demo run output so the screencast can rerun cleanly (Ollama can be slow — record at QPS 8, edit dead air out).
* [ ] Voice: clear, fast-paced, no filler. Practise the whole thing once unrecorded.
* [ ] Edit: cut to ≤ 5:00. Add chapter markers at 0:00 / 0:50 / 1:30 / 3:30 / 4:20 if the editor supports them.
* [ ] Export H.264 MP4, 1080p, ≤ 100 MB if possible (lablab accepts MP4, no size hard cap published but reviewers stream from web).
* [ ] Verify audio levels and no system notifications leaked into the recording.

---

## Backup plan

If recording stalls and time is short:
1. Render a slide deck PDF (next file `SLIDES.md` → marp / google slides → PDF).
2. Use Loom or Vimeo to capture a single-take walkthrough.
3. Don't aim for cinematics — Track 1 evaluators mark Presentation on clarity, not polish.
