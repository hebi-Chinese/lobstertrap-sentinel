"""Seed corpus for the three Chroma collections — small AcmeCorp policy docs
the workers retrieve via their tools. Kept short so the demo Chroma seed
runs in seconds; long enough that the LLM gets meaningful context.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDoc:
    doc_id: str
    title: str
    body: str
    tags: tuple[str, ...] = ()


HR_DOCS: tuple[PolicyDoc, ...] = (
    PolicyDoc(
        doc_id="hr-pto-001",
        title="Paid Time Off Policy",
        body=(
            "AcmeCorp employees accrue 20 PTO days per calendar year. PTO is granted on the "
            "first of each month at 1.67 days/month. Unused PTO carries over up to 5 days "
            "into the next year. Requests are submitted via the self-service portal at "
            "least two weeks in advance for stays over three days."
        ),
        tags=("pto", "leave", "policy"),
    ),
    PolicyDoc(
        doc_id="hr-parental-leave-002",
        title="Parental Leave Policy",
        body=(
            "Primary caregivers receive 16 weeks of fully paid parental leave; secondary "
            "caregivers receive 6 weeks. Leave can be taken in two blocks within the first "
            "12 months after birth or adoption. Notify HR at least 30 days before the "
            "intended start date."
        ),
        tags=("parental", "leave", "policy"),
    ),
    PolicyDoc(
        doc_id="hr-remote-003",
        title="Remote Work Policy",
        body=(
            "Hybrid is the default: 3 days in office, 2 days remote per week. Fully remote "
            "arrangements require manager approval and a documented home-office security "
            "checklist. Travel days are treated as remote days."
        ),
        tags=("remote", "policy"),
    ),
    PolicyDoc(
        doc_id="hr-handbook-pointer-004",
        title="Employee Handbook Pointer",
        body=(
            "The latest revision of the employee handbook is published quarterly and "
            "available at the internal documentation portal under People > Handbook. "
            "Section 3 covers performance reviews; Section 7 covers travel and expenses."
        ),
        tags=("handbook", "pointer"),
    ),
    PolicyDoc(
        doc_id="hr-referral-005",
        title="Employee Referral Program",
        body=(
            "Employees receive a bonus of $3,000 (gross) per successful referral hire, "
            "paid after the referred hire completes 6 months of employment. Submissions "
            "go through the People team; double-dipping with external recruiters is "
            "disallowed."
        ),
        tags=("referral", "bonus"),
    ),
)


FINANCE_DOCS: tuple[PolicyDoc, ...] = (
    PolicyDoc(
        doc_id="fin-expense-001",
        title="Expense Reimbursement Procedure",
        body=(
            "Expenses up to $500 are auto-approved if categorised correctly. Anything "
            "above $500 needs a line-manager sign-off. Receipts are required; attach via "
            "the expense submission tool. Reimbursement is paid in the next payroll cycle "
            "after approval."
        ),
        tags=("expense", "reimbursement"),
    ),
    PolicyDoc(
        doc_id="fin-perdiem-002",
        title="Per-diem Limits",
        body=(
            "Domestic per-diem is $75/day (meals + incidentals). International per-diem "
            "follows the GSA schedule and is approved per trip. Lodging is reimbursed at "
            "actual cost up to the city-specific cap."
        ),
        tags=("travel", "perdiem"),
    ),
    PolicyDoc(
        doc_id="fin-vendor-003",
        title="Vendor Onboarding",
        body=(
            "New vendors require a completed W-9 (US) or equivalent, a signed master "
            "services agreement, and security review for any vendor with data access. "
            "Procurement runs the onboarding workflow."
        ),
        tags=("vendor", "procurement"),
    ),
    PolicyDoc(
        doc_id="fin-budget-004",
        title="Quarterly Budget Revision Deadline",
        body=(
            "Q1 revisions are due by March 15; Q2 by June 15; Q3 by September 15; Q4 by "
            "December 1. Submit revisions through FP&A's planning tool with rationale and "
            "variance vs. plan."
        ),
        tags=("budget", "deadline"),
    ),
    PolicyDoc(
        doc_id="fin-approval-005",
        title="Software Purchase Approval Thresholds",
        body=(
            "Software purchases under $5,000/year: line-manager approval. $5k–$25k: "
            "director approval + security review. $25k+: VP approval, security review, "
            "and legal review of the contract."
        ),
        tags=("approval", "software"),
    ),
)


IT_DOCS: tuple[PolicyDoc, ...] = (
    PolicyDoc(
        doc_id="it-sso-001",
        title="SSO Password Self-Service",
        body=(
            "Use the SSO portal at idp.acmecorp.example to reset your password. "
            "Self-service requires a verified phone number on file; otherwise raise an "
            "IT ticket. New passwords must be at least 14 characters."
        ),
        tags=("sso", "password"),
    ),
    PolicyDoc(
        doc_id="it-vpn-002",
        title="VPN Usage Policy",
        body=(
            "All remote access to internal services goes through the company VPN. "
            "Contractors use the contractor profile with a 12-hour idle timeout. "
            "Split tunnelling is permitted for video conferencing only."
        ),
        tags=("vpn", "policy"),
    ),
    PolicyDoc(
        doc_id="it-laptop-003",
        title="Laptop Refresh Cycle",
        body=(
            "Standard refresh is every 3 years, or sooner if the machine fails diagnostics. "
            "Engineers can request an early refresh after 24 months by submitting a "
            "hardware ticket with a business justification."
        ),
        tags=("laptop", "hardware"),
    ),
    PolicyDoc(
        doc_id="it-mfa-004",
        title="Multi-Factor Authentication",
        body=(
            "MFA is required for every internal SaaS application. Authenticator app is "
            "preferred over SMS. Backup codes are stored in the IT-managed password "
            "manager; do not store them in personal files."
        ),
        tags=("mfa", "security"),
    ),
    PolicyDoc(
        doc_id="it-incident-005",
        title="Network Outage SLA",
        body=(
            "Severity-1 office network outages: 30-minute response, 4-hour resolution. "
            "Severity-2: 2-hour response, next-business-day resolution. Subscribe to "
            "the incident-response status page for live updates."
        ),
        tags=("network", "incident", "sla"),
    ),
)


def all_corpora() -> dict[str, tuple[PolicyDoc, ...]]:
    return {
        "hr_policy": HR_DOCS,
        "finance_policy": FINANCE_DOCS,
        "it_runbook": IT_DOCS,
    }
