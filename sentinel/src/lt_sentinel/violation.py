"""Per-event violation judgement (DESIGN.md §11.9 gray-area decision).

A violation feeds the binary OER signal that EWMA / CUSUM consume.
We deliberately keep the function dependency-free and pure so the same
function can replay over historical audit logs to recompute baselines.

Inputs are the raw LT audit-log Entry fields (from `internal/audit/logger.go`):
    metadata      → *inspector.PromptMetadata  (risk_score, contains_*, target_*)
    mismatches    → []metadata.Mismatch         (severity ∈ critical/warning/info)
    action        → policy.Action               (ALLOW / DENY / HUMAN_REVIEW / ...)
    direction     → "ingress" or "egress"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ViolationVerdict:
    violation: bool
    reasons: tuple[str, ...]
    severity_score: float  # 0..1, weight for future CUSUM signal-shaping


# Risk-score cutoffs (chosen against LT's default risk_score scaling, which is
# 0..1 composite per `internal/inspector/risk.go`). These are NOT the SPC tier
# thresholds — those live in config.SPCParams.
_RISK_BAND_CRITICAL = 0.70
_RISK_BAND_MEDIUM = 0.40


def _count_critical(mismatches: Any) -> int:
    if not mismatches:
        return 0
    if not isinstance(mismatches, Iterable):
        return 0
    return sum(
        1
        for m in mismatches
        if isinstance(m, dict) and str(m.get("severity", "")).lower() == "critical"
    )


def _count_warning(mismatches: Any) -> int:
    if not mismatches:
        return 0
    if not isinstance(mismatches, Iterable):
        return 0
    return sum(
        1
        for m in mismatches
        if isinstance(m, dict) and str(m.get("severity", "")).lower() == "warning"
    )


def _has_non_intent_critical(mismatches: Any) -> bool:
    """A critical mismatch on a structural field — paths, commands, or domains.

    Intent-only mismatches are noisy (declared natural-language description vs.
    LT's single-token category); structural mismatches are real evidence the
    agent's declared boundaries don't match what DPI extracted.
    """
    if not mismatches or not isinstance(mismatches, Iterable):
        return False
    for m in mismatches:
        if not isinstance(m, dict):
            continue
        if str(m.get("severity", "")).lower() != "critical":
            continue
        if str(m.get("field", "")).lower() in {"paths", "commands", "domains"}:
            return True
    return False


def judge(entry: dict[str, Any]) -> ViolationVerdict:
    """Decide whether a single LT audit-log entry counts as a chain violation.

    Composite rule (each term is a clear, defensible reason):
      1. LT's own action is DENY / HUMAN_REVIEW / QUARANTINE                 → violation
      2. risk_score ≥ 0.70                                                   → violation
      3. ≥ 1 critical mismatch on a STRUCTURAL field (paths/commands/domains)→ violation
      4. risk_score ≥ 0.40 AND ≥ 1 critical mismatch (intent included)       → violation
      5. risk_score ≥ 0.40 AND ≥ 1 warning mismatch                          → violation

    Intent-only critical mismatches WITHOUT a corresponding risk signal are
    treated as classifier noise — the agent's natural-language declared_intent
    rarely matches LT's single-token IntentCategory token exactly.

    Everything else (including plain ALLOW with low risk) is not a violation.
    """

    metadata = entry.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    risk_score = float(metadata.get("risk_score") or 0.0)
    action = str(entry.get("action") or "ALLOW").upper()
    mismatches = entry.get("mismatches") or []
    n_critical = _count_critical(mismatches)
    n_warning = _count_warning(mismatches)
    has_structural_critical = _has_non_intent_critical(mismatches)

    reasons: list[str] = []

    if action in {"DENY", "HUMAN_REVIEW", "QUARANTINE"}:
        reasons.append(f"action={action}")

    if risk_score >= _RISK_BAND_CRITICAL:
        reasons.append(f"risk_score={risk_score:.2f}>=critical({_RISK_BAND_CRITICAL})")

    if has_structural_critical:
        reasons.append("mismatches.critical_on_paths_commands_or_domains")

    if risk_score >= _RISK_BAND_MEDIUM and n_critical >= 1 and not has_structural_critical:
        # Intent critical only counts when it's corroborated by elevated risk.
        reasons.append(
            f"risk_score={risk_score:.2f}>=medium({_RISK_BAND_MEDIUM}) AND intent_critical={n_critical}"
        )

    if risk_score >= _RISK_BAND_MEDIUM and n_warning >= 1:
        reasons.append(
            f"risk_score={risk_score:.2f}>=medium({_RISK_BAND_MEDIUM}) AND warning_mismatches={n_warning}"
        )

    # Severity score, used only for richer logging and future signal shaping.
    severity_score = min(
        1.0,
        risk_score
        + (0.3 if has_structural_critical else 0.1 * n_critical)
        + 0.05 * n_warning
        + (0.3 if action in {"DENY", "QUARANTINE"} else 0.0),
    )

    return ViolationVerdict(
        violation=bool(reasons),
        reasons=tuple(reasons),
        severity_score=severity_score,
    )
