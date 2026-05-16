"""Build the LT-Sentinel submission video — narrated slideshow.

Pipeline: edge-tts voiceover  ->  marp text slides + ffmpeg-composited shot
frames  ->  ffmpeg per-slide clips  ->  ffmpeg concat  ->  lt_sentinel_demo.mp4.

Two slide kinds:
  * "text"  — rendered by marp from video_slides.md (5 slides, dark theme).
  * "shot"  — a real screenshot / chart PNG, composited by ffmpeg onto a
              1920x1080 dark canvas with a caption bar. marp's split-background
              handling dropped the theme on image slides, so shots bypass marp.

Re-runnable: each stage skips work whose output already exists unless --force.
All narration text lives here so the script is the single source of truth.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
SLIDES = HERE / "slides"
CLIPS = HERE / "clips"
DECK = HERE / "video_slides.md"
FONT = HERE / "caption_font.ttf"
FINAL = HERE / "lt_sentinel_demo.mp4"
SRT = HERE / "lt_sentinel_demo.srt"
SUBBED = HERE / "lt_sentinel_demo_subtitled.mp4"

VOICE = "en-US-AndrewNeural"
RATE = "+6%"            # keeps the whole video safely under the 5-minute cap
TAIL_SILENCE = 0.5      # seconds of pad after each segment so cuts aren't abrupt
W, H = 1920, 1080
SHOT_AREA_H = 960       # screenshot fits in the top 960px; bottom 120px = caption

SHOTS = HERE.parent / "video_shots"
CHART = (HERE.parent.parent / "sentinel" / "data" / "demo_canonical"
         / "chart_trust_timeseries.png")

# Per video slide: kind + source.
#   ("text", marp_index)             -> slides/slide.{NNN}.png from video_slides.md
#   ("shot", screenshot_path, caption)
SLIDE_SPEC: dict[int, tuple] = {
    1:  ("text", 1),
    2:  ("text", 2),
    3:  ("text", 3),
    4:  ("shot", SHOTS / "shot1_config.png",
         "lt-sentinel show-config  -  every SPC constant cited to literature"),
    5:  ("shot", SHOTS / "shot2_startup.png",
         "lt-sentinel run  -  3 LT instances plus proxy, state replayed "
         "from audit log"),
    6:  ("shot", SHOTS / "shot3_demo_(1).png",
         "demo  -  warm-up, Scenario A slow injection, recovery"),
    7:  ("shot", SHOTS / "shot4_demo_(2).png",
         "demo  -  Scenario B trust-then-burst, Scenario C tool poisoning"),
    8:  ("shot", CHART,
         "per-agent TrustScore over time  -  4 agents, 5 tier transitions, "
         "2 recoveries"),
    9:  ("text", 4),
    10: ("text", 5),
}

# (video slide number, narration text). One entry per slide.
SEGMENTS: list[tuple[int, str]] = [
    (1, "This is LT-Sentinel — a sidecar that gives Veea's Lobster Trap "
        "something it doesn't have today: memory across events."),
    (2, "Lobster Trap is excellent at single-event deep prompt inspection — "
        "sub-millisecond regex, eight policy actions. But by design it is "
        "stateless across events. So it can't see three attack patterns that "
        "matter most in multi-agent systems. First, slow injection: an "
        "attacker drips pieces of 'ignore your rules' across many turns, and "
        "each turn alone looks benign. Second, trust-then-burst: an agent "
        "behaves perfectly for thirty turns, then makes one extraction "
        "attempt. Third, tool-result poisoning: each tainted tool return "
        "looks like noise, but the pattern accumulates. LT-Sentinel is the "
        "layer that catches all three."),
    (3, "Three Lobster Trap instances run in parallel, each loaded with one "
        "of three policies — Trust, Observe, and Lockdown. They never "
        "restart. Sentinel adds a reverse proxy on port 8080 that routes to "
        "whichever instance matches the current trust tier. It tails all "
        "three audit logs, computes a per-agent error rate over a thirty-"
        "event window, and feeds it through two statistical control charts. "
        "When the resulting trust score crosses a threshold, Sentinel "
        "atomically swings the proxy to the new tier. No restart, no source "
        "modification."),
    (4, "Every knob is anchored to literature. The smoothing factor comes "
        "from Lucas and Saccucci, 1990. The change-detection bounds from "
        "Page, 1954, and Hawkins and Olwell, 1998. The window size from Munz "
        "and Carle, 2008. The baseline prior from Agent Security Bench at "
        "ICLR 2025. Nothing here is a magic number."),
    (5, "On startup, three Lobster Trap instances come up — Trust, Observe, "
        "and Lockdown — alongside the Sentinel proxy. Notice the very first "
        "line: this is a restart — Sentinel rebuilt its state from an "
        "earlier run's audit log and resumed at the correct tier. That is "
        "why the startup clock here is later than the demo data you'll see "
        "in a moment. A crash in the middle of lockdown comes back up locked "
        "down — not at full trust."),
    (6, "The demo drives all three attacks through a real LangGraph "
        "multi-agent system. The warm-up turns pass clean — every agent "
        "allowed. Then Scenario A, slow injection: the router keeps "
        "classifying the payloads, and the prompt-injection rules start "
        "firing DENY. Through the recovery phase, benign turns flow again."),
    (7, "Scenario B, trust-then-burst: fifteen clean H-R turns, then a "
        "four-request burst — the first blocked by Lobster Trap itself, the "
        "next three progressively riskier and caught by Sentinel's tiers. "
        "Scenario C, tool poisoning: eight tool returns escalate, hitting "
        "data-exfiltration, obfuscation, P-I-I, and prompt-injection rules "
        "in turn."),
    (8, "Four agents, one chart. The green band is Trust, yellow is Observe, "
        "red is Lockdown. Finance stays pinned at one — it's the control, it "
        "never receives attack traffic. The router is the agent that moves. "
        "And here is the real finding: the router is the universal entry "
        "point — every user turn passes through it for classification "
        "first, so it accumulates exposure from all three scenarios and "
        "crosses every threshold first. Watch the middle of the chart — the "
        "router climbs back up, lockdown to observe to trust. That's the "
        "control chart decaying: once the attack window passes, clean "
        "traffic pulls the score back, with no manual reset."),
    (9, "This is what Veea's brief called audit trails a regulator could "
        "read. Each tier transition records the trigger agent — who tipped "
        "the system over — their trust score at the moment of crossing, and "
        "which threshold broke. It captures a full snapshot of every other "
        "agent's score, so you can prove they were not involved. It lists "
        "the violating request IDs as evidence, and each one chains back "
        "through the events log into Lobster Trap's own audit log. It "
        "records the exact policy file that became active, and a one-line "
        "human-readable summary. Recoveries are logged with the same shape."),
    (10, "Three hand-written policy files, a LangGraph multi-agent system, "
         "the Sentinel runtime, thirty-nine unit tests, two hundred and "
         "twenty calibration chains — everything in one open-source repo, on "
         "top of open-source Lobster Trap. Two resilience details worth a "
         "line: a dormant agent does not stay locked down forever — its "
         "trust score decays back toward baseline on a ten-minute half-life. "
         "And Sentinel rebuilds full state from its audit log on restart. "
         "Per-identity policy is the obvious next step, but it needs an "
         "upstream change in Lobster Trap. Thanks to Veea for open-sourcing "
         "the floor, and to lablab for the ceiling."),
]


# Caption font is copied from the OS at build time — never committed, since
# system fonts (Segoe UI etc.) are proprietary and can't ship in an MIT repo.
SYS_FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
]


def ensure_font() -> None:
    if FONT.exists():
        return
    for cand in SYS_FONT_CANDIDATES:
        if cand.exists():
            shutil.copy(cand, FONT)
            print(f"  caption font provisioned from {cand}")
            return
    sys.exit(f"no system font found; drop any .ttf at {FONT} and re-run")


def run(cmd, *, shell: bool = False, cwd: Path | None = None) -> None:
    printable = cmd if isinstance(cmd, str) else " ".join(str(c) for c in cmd)
    print(f"  $ {printable}")
    subprocess.run(cmd, check=True, shell=shell,
                   cwd=str(cwd) if cwd else None)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def step_tts(force: bool) -> None:
    print("\n=== 1/4  edge-tts voiceover ===")
    for idx, text in SEGMENTS:
        mp3 = AUDIO / f"s{idx:02d}.mp3"
        if mp3.exists() and not force:
            print(f"  s{idx:02d}.mp3 exists — skip")
            continue
        txt = AUDIO / f"s{idx:02d}.txt"
        txt.write_text(text, encoding="utf-8")
        run(["py", "-m", "edge_tts", "--voice", VOICE, "--rate", RATE,
             "-f", str(txt), "--write-media", str(mp3)])


def step_slides(force: bool) -> None:
    print("\n=== 2/4  marp text slides ===")
    existing = sorted(SLIDES.glob("slide.*.png"))
    if existing and not force:
        print(f"  {len(existing)} text-slide PNGs exist — skip")
        return
    for old in existing:
        old.unlink()
    run(f'marp "{DECK}" --images png --image-scale 1.5 --allow-local-files '
        f'-o "{SLIDES / "slide.png"}"', shell=True)


def vf_text() -> str:
    return (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0f1117,setsar=1")


def vf_shot(caption: str) -> str:
    # screenshot fits the top SHOT_AREA_H px, centred; caption bar below it.
    return (
        f"scale={W}:{SHOT_AREA_H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:({SHOT_AREA_H}-ih)/2:color=0x0f1117,"
        f"setsar=1,"
        f"drawtext=fontfile=caption_font.ttf:text='{caption}':"
        f"fontsize=34:fontcolor=0xe6e6ea:x=(w-text_w)/2:y=h-text_h-40:"
        f"box=1:boxcolor=0x161b29@0.95:boxborderw=22"
    )


def step_clips(force: bool) -> list[float]:
    print("\n=== 3/4  per-slide clips (ffmpeg) ===")
    durations: list[float] = []
    for idx, _ in SEGMENTS:
        spec = SLIDE_SPEC[idx]
        mp3 = AUDIO / f"s{idx:02d}.mp3"
        clip = CLIPS / f"clip{idx:02d}.mp4"
        if not mp3.exists():
            sys.exit(f"missing audio: {mp3}")

        if spec[0] == "text":
            src = SLIDES / f"slide.{spec[1]:03d}.png"
            vf = vf_text()
        else:
            src = Path(spec[1])
            vf = vf_shot(spec[2])
        if not src.exists():
            sys.exit(f"missing slide source: {src}")

        audio_dur = probe_duration(mp3)
        clip_dur = audio_dur + TAIL_SILENCE
        durations.append(clip_dur)
        if clip.exists() and not force:
            print(f"  clip{idx:02d}.mp4 exists ({clip_dur:5.1f}s) — skip")
            continue
        run([
            "ffmpeg", "-y", "-loop", "1", "-i", str(src),
            "-i", str(mp3),
            "-t", f"{clip_dur:.3f}",
            "-af", f"apad=pad_dur={TAIL_SILENCE}",
            "-vf", vf,
            "-c:v", "libx264", "-tune", "stillimage", "-r", "30",
            "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
            str(clip),
        ], cwd=HERE)
    return durations


def step_concat() -> None:
    print("\n=== 4/4  concat -> final MP4 ===")
    listfile = CLIPS / "concat.txt"
    listfile.write_text(
        "".join(f"file 'clip{idx:02d}.mp4'\n" for idx, _ in SEGMENTS),
        encoding="utf-8",
    )
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(listfile), "-c", "copy", str(FINAL)])


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?]) +", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _srt_time(t: float) -> str:
    h, rem = divmod(max(t, 0.0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def step_subtitles(durations: list[float]) -> None:
    """Build an SRT (sentence cues, time distributed by char length) and burn
    it into a separate _subtitled copy — the deliverable MP4 stays clean.
    """
    print("\n=== 5/5  subtitled review copy ===")
    cues: list[tuple[int, float, float, str]] = []
    clip_start = 0.0
    n = 1
    for (_, text), clip_dur in zip(SEGMENTS, durations):
        audio_dur = clip_dur - TAIL_SILENCE
        sents = _split_sentences(text)
        total = sum(len(s) for s in sents) or 1
        t = clip_start
        for s in sents:
            d = audio_dur * len(s) / total
            cues.append((n, t, t + d, s))
            t += d
            n += 1
        clip_start += clip_dur

    SRT.write_text(
        "".join(
            f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{txt}\n\n"
            for i, a, b, txt in cues
        ),
        encoding="utf-8",
    )
    print(f"  wrote {SRT.name}  ({len(cues)} cues)")

    style = ("Fontname=Segoe UI,Fontsize=15,PrimaryColour=&H00FFFFFF,"
             "BorderStyle=3,Outline=1,Shadow=0,BackColour=&HA0000000,"
             "MarginV=36")
    run([
        "ffmpeg", "-y", "-i", str(FINAL),
        "-vf", f"subtitles={SRT.name}:force_style='{style}'",
        "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p",
        "-c:a", "copy", str(SUBBED),
    ], cwd=HERE)
    print(f"  review copy: {SUBBED}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="rebuild every stage from scratch")
    ap.add_argument("--force-tts", action="store_true")
    ap.add_argument("--force-slides", action="store_true")
    args = ap.parse_args()

    for d in (AUDIO, SLIDES, CLIPS):
        d.mkdir(parents=True, exist_ok=True)
    ensure_font()

    step_tts(args.force or args.force_tts)
    step_slides(args.force or args.force_slides)
    durations = step_clips(args.force)
    step_concat()
    step_subtitles(durations)

    total = sum(durations)
    print("\n=== timing ===")
    for (idx, _), dur in zip(SEGMENTS, durations):
        kind = SLIDE_SPEC[idx][0]
        print(f"  slide {idx:2d} [{kind}]: {dur:6.2f}s")
    mm, ss = divmod(total, 60)
    print(f"  TOTAL : {total:6.2f}s  ({int(mm)}:{ss:05.2f})")
    cap = "OK — under 5:00" if total <= 300 else "OVER 5:00 — raise RATE"
    print(f"  5-min cap: {cap}")
    print(f"\nfinal video: {FINAL}")


if __name__ == "__main__":
    main()
