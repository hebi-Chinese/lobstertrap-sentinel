# Lablab Track 1 — submission worksheet

Fill these fields into the lablab submission form at
https://lablab.ai/ai-hackathons/techex-intelligent-enterprise-solutions-hackathon/hebee/submission
before **2026-05-19 08:00 China Standard Time**.

---

## Project Title

`LT-Sentinel — long-term-attack monitoring layer for Veea Lobster Trap`

(≤ 60 chars works in the lablab UI; keep this verbatim.)

## Short Description (one-line, ~140 chars)

> Adds cross-event statistical monitoring (OER · EWMA · CUSUM) on top of Veea Lobster Trap to catch attacks that single-event DPI misses.

## Long Description (paragraph, ~600 chars)

> LT-Sentinel is a sidecar that gives Veea Lobster Trap something it doesn't have today: memory across events. It tails Lobster Trap's audit log, maintains a per-agent OER / EWMA / CUSUM TrustScore, and atomically swings traffic between three pre-warmed Lobster Trap instances loaded with three escalating policies (Trust, Observe, Lockdown). Tier change is a pointer flip in Sentinel's reverse proxy — zero downtime, no Lobster Trap source change. Every tier transition writes a regulator-readable JSONL record with trigger agent, full per-agent snapshot, and evidence request IDs that chain back into Lobster Trap's own audit log. Single Python process, MIT-licensed.

## Technology / Category Tags

Recommended tags (pick whichever the lablab form accepts):

* AI Agent Security
* Multi-agent Governance
* Audit Trails / Observability
* Statistical Process Control
* Veea Lobster Trap
* Ollama (or whatever local LLM you use in the demo video)
* Python · Go · YAML
* Open Source · MIT

## Cover Image

* **Use** `../sentinel/data/demo_canonical/chart_trust_timeseries.png` cropped to a 16:9 banner with the project title overlaid.
* Quick recipe in any image editor: open the chart, add a 60-px black bar at the top, write "LT-Sentinel · Track 1" in white. Export at 1280×720 PNG.

## Video Presentation

* Max **5 minutes**, MP4 format (verified 2026-05-15 on https://lablab.ai/delivering-your-hackathon-solution).
* Script in [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md).
* Production hints in the same file (recording tool, audio levels, export format).

## Slide Presentation

* Source in [`SLIDES.md`](SLIDES.md) (marp/markdown).
* Export to PDF before upload: `marp SLIDES.md --pdf` (after `npm i -g @marp-team/marp-cli`), or paste into Google Slides and File → Download → PDF.

## Public GitHub Repository

* Create a public repo named **`lt-sentinel`** under your GitHub account.
* From the project root: `git remote add origin git@github.com:<YOUR_USER>/lt-sentinel.git && git push -u origin main`.
* Confirm `LICENSE`, `README.md`, and `sentinel/data/demo_canonical/chart_trust_timeseries.png` are all visible on the rendered repo page.

## Demo Application Platform

* Platform = "local-only" (single-machine Ollama-backed deployment).
* If lablab insists on a hosted URL, the closest substitute is a recorded demo or a ngrok tunnel against your own machine (set in `lt_sentinel.cli run` and expose `:8080` for the form duration).

## Application URL

* If you set up an ngrok or cloudflare tunnel: paste the URL here.
* Otherwise: paste the GitHub repo URL again (lablab accepts either, but reviewers may prefer a live one).

---

## Pre-flight checklist before clicking *Submit*

* [ ] `git status` is clean and `git log` shows ≥ 1 commit
* [ ] Public GitHub repo created and pushed
* [ ] README.md renders correctly on github.com (open it and check the chart image loads)
* [ ] Video is **MP4**, **≤ 5 min**, audio audible, no system notifications visible
* [ ] Slide PDF is uploaded and readable
* [ ] Cover image is 16:9, has project title
* [ ] All tech tags are filled
* [ ] Discord linked (`lablab.ai` server) — submitters are usually required to be enrolled
* [ ] Submission timestamp is **before 2026-05-19 08:00 CST**
* [ ] Live on-stage pitching slot reserved (2026-05-20 03:45 CST) if proceeding to finals
