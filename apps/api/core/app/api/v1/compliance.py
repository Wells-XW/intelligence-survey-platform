"""Ethics & Compliance API endpoints.

Provides rule-based compliance scanning (PIPL, GDPR, bias, sensitive info,
consent) and AI-assisted deep review for survey questionnaires.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import check_survey_permission, get_current_user
from ...core.prompts import ETHICS_REVIEW_SYSTEM, build_ethics_review_prompt
from ...database import get_db
from ...models.compliance_check import ComplianceCheck
from ...models.survey import Survey
from ...models.user import User
from ...schemas.compliance import (
    AiReviewRequest,
    ComplianceCheckResponse,
    ComplianceFinding,
    ComplianceHistoryResponse,
    ComplianceReportResponse,
    ComplianceScanRequest,
    ComplianceSuggestion,
)
from ...services.compliance_scanner import ComplianceScanner

router = APIRouter(prefix="/surveys", tags=["compliance"])


# ── Helpers ──────────────────────────────────────────────────────────────


async def _get_survey_text(survey_id: str, db: AsyncSession) -> tuple[Survey, str]:
    """Fetch survey and extract its full text content."""
    result = await db.execute(select(Survey).where(Survey.id == survey_id))
    survey = result.scalar_one_or_none()
    if survey is None:
        raise HTTPException(status_code=404, detail="问卷不存在")

    # Extract all text from the survey JSON
    texts: list[str] = []
    for page in survey.json_content.get("pages", []):
        for elem in page.get("elements", []):
            if elem.get("type") == "panel":
                for nested in elem.get("elements", []):
                    texts.append(_elem_text(nested))
            else:
                texts.append(_elem_text(elem))

    return survey, " ".join(texts)


def _elem_text(elem: dict) -> str:
    """Extract text from a single survey element."""
    parts = [
        elem.get("title", ""),
        elem.get("description", ""),
        elem.get("commentText", ""),
    ]
    for c in elem.get("choices", []):
        parts.append(c.get("text", ""))
    return " ".join(p for p in parts if p)


def _build_report_markdown(
    survey_title: str,
    findings: list[ComplianceFinding],
    suggestions: list[ComplianceSuggestion],
    risk_score: float,
    risk_level: str,
    check_type: str,
) -> str:
    """Generate a Markdown compliance report."""
    lines = [
        f"# 伦理合规审查报告",
        f"",
        f"**问卷**: {survey_title}",
        f"**检查类型**: {check_type}",
        f"**综合风险评分**: {risk_score:.1f}/100",
        f"**风险等级**: {risk_level.upper()}",
        f"**生成时间**: {datetime.now(timezone.utc).isoformat()}",
        f"",
        f"---",
        f"",
        f"## 检查发现",
        f"",
    ]

    # Group by dimension
    from collections import defaultdict
    by_dimension: dict[str, list] = defaultdict(list)
    for f in findings:
        by_dimension[f.dimension].append(f)

    dim_names = {
        "pipl": "PIPL 合规",
        "gdpr": "GDPR 合规",
        "bias": "方法论偏差",
        "sensitive_info": "敏感信息",
        "consent": "知情同意",
        "minimization": "数据最小化",
    }

    for dim, items in by_dimension.items():
        dim_label = dim_names.get(dim, dim)
        lines.append(f"### {dim_label}")
        lines.append("")
        for item in items:
            prefix = {
                "info": "✅",
                "warning": "⚠️",
                "error": "❌",
            }.get(item.severity, "•")
            lines.append(f"- {prefix} {item.issue}")
            if item.evidence:
                lines.append(f"  > {item.evidence}")
            if item.reference:
                lines.append(f"  *参考: {item.reference}*")
        lines.append("")

    if suggestions:
        lines.append("---")
        lines.append("")
        lines.append("## 改进建议")
        lines.append("")
        for s in suggestions:
            lines.append(f"### [{s.priority.upper()}] {s.title}")
            lines.append(f"{s.description}")
            if s.reference:
                lines.append(f"*参考: {s.reference}*")
            lines.append("")

    return "\n".join(lines)


# ── Scan Endpoint ───────────────────────────────────────────────────────


@router.post(
    "/{survey_id}/compliance/scan",
    response_model=ComplianceCheckResponse,
)
async def run_compliance_scan(
    survey_id: UUID,
    body: ComplianceScanRequest = ComplianceScanRequest(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Run compliance scan (rule-based + optional AI review) on a survey."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    survey, _ = await _get_survey_text(sid, db)

    # Determine scan type
    if body.check_types:
        # Custom selection
        check_types = body.check_types
        check_type_label = "+".join(check_types)
    else:
        check_types = None
        check_type_label = "full_scan"

    # Run rule-based scan
    scanner = ComplianceScanner(survey.json_content)
    scan_result = scanner.scan_all()

    # AI-assisted review (if requested)
    if body.include_ai_review:
        try:
            from ...core.ai_router import execute_ai_call
            survey_text = " ".join([
                _elem_text(elem)
                for page in survey.json_content.get("pages", [])
                for elem in page.get("elements", [])
            ])
            user_prompt = build_ethics_review_prompt(
                survey_text=survey_text,
                focus_areas=check_types,
            )
            ai_result, _ = await execute_ai_call(
                system_prompt=ETHICS_REVIEW_SYSTEM,
                user_prompt=user_prompt,
                task="SENSITIVE_PIPL",
                has_chinese=True,
                has_sensitive_data=False,  # Survey text is not PII itself
            )
            # Parse AI findings and merge with rule-based results
            import json as _json
            try:
                ai_data = _json.loads(ai_result.content)
                for section in ai_data.get("sections", []):
                    scan_result["findings"].append(ComplianceFinding(
                        dimension=f"ai_{section.get('dimension', 'review')}",
                        issue=section.get("finding", ""),
                        severity=section.get("severity", "info"),
                        reference=section.get("reference"),
                    ))
                    scan_result["suggestions"].append(ComplianceSuggestion(
                        priority=section.get("severity", "medium"),
                        title=section.get("finding", "")[:80],
                        description=section.get("suggestion", ""),
                        reference=section.get("reference"),
                    ))
            except _json.JSONDecodeError:
                pass  # AI output not valid JSON, skip
        except Exception:
            pass  # AI review is best-effort

    # Persist check record
    check = ComplianceCheck(
        survey_id=sid,
        check_type=check_type_label,
        status="fail" if scan_result["items_failed"] > 0 else (
            "warning" if scan_result["items_warning"] > 0 else "pass"
        ),
        risk_level=scan_result["risk_level"],
        risk_score=scan_result["risk_score"],
        findings={
            "items": [
                {
                    "dimension": f.dimension,
                    "issue": f.issue,
                    "severity": f.severity,
                    "evidence": f.evidence,
                    "reference": f.reference,
                }
                for f in scan_result["findings"]
            ]
        },
        suggestions={
            "items": [
                {
                    "priority": s.priority,
                    "title": s.title,
                    "description": s.description,
                    "reference": s.reference,
                }
                for s in scan_result["suggestions"]
            ]
        },
        items_checked=scan_result["items_checked"],
        items_passed=scan_result["items_passed"],
        items_warning=scan_result["items_warning"],
        items_failed=scan_result["items_failed"],
        checked_by=user.id,
    )
    db.add(check)
    await db.commit()

    return ComplianceCheckResponse(
        id=check.id,
        survey_id=sid,
        check_type=check_type_label,
        status=check.status,
        risk_level=check.risk_level,
        risk_score=check.risk_score,
        findings=scan_result["findings"],
        suggestions=scan_result["suggestions"],
        items_checked=scan_result["items_checked"],
        items_passed=scan_result["items_passed"],
        items_warning=scan_result["items_warning"],
        items_failed=scan_result["items_failed"],
        checked_at=check.checked_at,
    )


# ── Report Endpoint ─────────────────────────────────────────────────────


@router.get(
    "/{survey_id}/compliance/report",
    response_model=ComplianceReportResponse,
)
async def get_compliance_report(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a compliance report from the latest scan result."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    survey, _ = await _get_survey_text(sid, db)

    # Get latest check
    result = await db.execute(
        select(ComplianceCheck)
        .where(ComplianceCheck.survey_id == sid)
        .order_by(ComplianceCheck.checked_at.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()

    if latest is None:
        # Run a quick scan if no prior check exists
        scanner = ComplianceScanner(survey.json_content)
        scan_result = scanner.scan_all()
        report_md = _build_report_markdown(
            survey.title,
            scan_result["findings"],
            scan_result["suggestions"],
            scan_result["risk_score"],
            scan_result["risk_level"],
            "quick_scan",
        )
        return ComplianceReportResponse(
            survey_id=sid,
            survey_title=survey.title,
            report_markdown=report_md,
            risk_score=scan_result["risk_score"],
            risk_level=scan_result["risk_level"],
            generated_at=datetime.now(timezone.utc),
        )

    # Convert stored findings/suggestions back to Pydantic models
    findings = [
        ComplianceFinding(**f) for f in (latest.findings or {}).get("items", [])
    ]
    suggestions = [
        ComplianceSuggestion(**s) for s in (latest.suggestions or {}).get("items", [])
    ]

    report_md = _build_report_markdown(
        survey.title,
        findings,
        suggestions,
        latest.risk_score,
        latest.risk_level,
        latest.check_type,
    )

    return ComplianceReportResponse(
        survey_id=sid,
        survey_title=survey.title,
        report_markdown=report_md,
        risk_score=latest.risk_score,
        risk_level=latest.risk_level,
        generated_at=datetime.now(timezone.utc),
    )


# ── History Endpoint ────────────────────────────────────────────────────


@router.get(
    "/{survey_id}/compliance/history",
    response_model=ComplianceHistoryResponse,
)
async def get_compliance_history(
    survey_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve past compliance checks for a survey."""
    sid = str(survey_id)
    await check_survey_permission(sid, user, "viewer", db)

    result = await db.execute(
        select(ComplianceCheck)
        .where(ComplianceCheck.survey_id == sid)
        .order_by(ComplianceCheck.checked_at.desc())
        .limit(20)
    )
    checks = result.scalars().all()

    check_responses = [
        ComplianceCheckResponse(
            id=c.id,
            survey_id=c.survey_id,
            check_type=c.check_type,
            status=c.status,
            risk_level=c.risk_level,
            risk_score=c.risk_score,
            findings=[
                ComplianceFinding(**f)
                for f in (c.findings or {}).get("items", [])
            ],
            suggestions=[
                ComplianceSuggestion(**s)
                for s in (c.suggestions or {}).get("items", [])
            ],
            items_checked=c.items_checked,
            items_passed=c.items_passed,
            items_warning=c.items_warning,
            items_failed=c.items_failed,
            checked_at=c.checked_at,
        )
        for c in checks
    ]

    latest_risk = check_responses[0].risk_score if check_responses else None
    latest_level = check_responses[0].risk_level if check_responses else None

    return ComplianceHistoryResponse(
        survey_id=sid,
        checks=check_responses,
        latest_risk_score=latest_risk,
        latest_risk_level=latest_level,
        total_checks=len(check_responses),
    )
