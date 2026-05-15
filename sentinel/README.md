# LT-Sentinel — developer guide

Authoritative project README is one level up at [`../README.md`](../README.md).
Design spec: [`../DESIGN.md`](../DESIGN.md) (§11 + §12 are the locked decisions).

## Layout

| Path | Purpose |
|---|---|
| `src/lt_sentinel/` | the runtime package |
| `policies/` | three pre-written LT policy YAMLs (trust / observe / lockdown) |
| `scenarios/` | happy-path runner, three attack scripts, demo orchestrator, calibration, visualization |
| `tests/` | pytest suite (28 cases) |
| `data/` | runtime outputs (JSONL audit trails + chart PNGs); gitignored |

## Ports

| Process | Listen | Notes |
|---|---|---|
| Sentinel reverse proxy | `:8080` | what agents talk to (OpenAI-compatible) |
| LT-Trust    | `:18081` | loaded with `policies/policy_trust.yaml` |
| LT-Observe  | `:18082` | loaded with `policies/policy_observe.yaml` |
| LT-Lockdown | `:18083` | loaded with `policies/policy_lockdown.yaml` |
| Ollama (or any OpenAI-compatible) | `:11434` | upstream LLM backend |

## Run

```bash
# Install in editable mode (one time)
py -m pip install -e .[viz,dev]

# Foreground run (auto-spawns the 3 LT processes; Ctrl-C to stop)
py -m lt_sentinel.cli run

# Inspect resolved config (handy for debugging path issues)
py -m lt_sentinel.cli show-config

# Offline replay of an audit log to see what tier swaps would happen
py -m lt_sentinel.cli replay data/sentinel_events.jsonl
```

If a previous run was force-killed and orphaned `lobstertrap.exe` processes
remain, the next `lt_sentinel.cli run` automatically `taskkill /F /IM
lobstertrap.exe` before spawning fresh ones (Windows).

## Demo flow

```bash
# Terminal 1
py -m lt_sentinel.cli run

# Terminal 2 — drives traffic
py -m scenarios.demo_run                                # all 3 scenarios
# or individually:
py -m scenarios.happy_path --n 200 --model qwen2.5:7b   # baseline
py -m scenarios.attack_a_slow_injection --repeats 3
py -m scenarios.attack_b_trust_then_burst --n-warm 30
py -m scenarios.attack_c_tool_poisoning

# Calibration & visualization
py -m scenarios.calibrate                # writes data/calibration_report.json
py -m scenarios.visualize                # writes data/trust_timeseries.png
```

## Tests

```bash
py -m pytest tests/ -v
```

The 28 tests pin the SPC math (EWMA decay, CUSUM accumulation, TrustScore
boundaries, p-chart σ formula) plus the violation judge.

## Tuning knobs (all in `src/lt_sentinel/config.py`)

```
SPCParams(
    lambda_ewma           = 0.05,      # Lucas & Saccucci 1990 range floor
    k_cusum_sigma_mult    = 0.5,       # Page 1954
    h_cusum_sigma_mult    = 4.0,       # Hawkins & Olwell 1998
    window_size           = 30,        # Münz & Carle 2008
    tau_high              = 0.33,      # observe entry
    tau_low               = 0.10,      # lockdown entry
    mu_dev                = 0.05,      # ASB ICLR 2025 prior (low end)
    sigma_dev             = 0.040,     # √(0.05·0.95/30)
)
```

If you change `mu_dev` or `sigma_dev`, rerun `py -m scenarios.calibrate` —
it derives `h_concrete = 4σ` and `k_concrete = 0.5σ` automatically.

## Adding a new attack scenario

1. Drop a `scenarios/attack_X_xxx.py` next to the existing three.
2. Keep the same shape: imports `SentinelClient`, drives turns with
   `agent_id` + `declared_intent="general"` (or matched to LT category).
3. Add a line in `scenarios/demo_run.py` if it should run in the canonical sequence.

## Known limitations / future work

| Item | Why deferred |
|---|---|
| Per-identity policy switching | LT's policy YAML conditions don't accept `agent_id` as a field; needs either an upstream LT change or multiple LT instances per agent. Out of scope for hackathon submission. |
| OAuth / mTLS agent identity | `_lobstertrap.agent_id` is **declarative**. Production deployment should authenticate the calling agent before trusting that field. |
| Adaptive-attacker robustness | SPC is vulnerable to attackers tuning rate to stay just below the threshold (see DESIGN.md §7.4). RL-based detectors or randomised thresholds are the standard countermeasures; not implemented here. |
| Self-supervision of judge | The violation judge is hand-tuned (DESIGN.md §11.9). A learned classifier on labelled audit trails would be a natural v2. |
| Windows process-group orphans | If Sentinel is `kill -9`'d, the LT children can survive. We work around this with a `taskkill` on next start; a proper Job Object would be cleaner. |
