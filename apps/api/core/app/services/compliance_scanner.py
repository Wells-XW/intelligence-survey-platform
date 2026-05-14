"""Compliance scanner — rule-based ethics & regulatory checks for surveys.

Performs deterministic checks (no LLM) for:
- PIPL (Personal Information Protection Law) baseline
- GDPR baseline
- Bias detection (via sqp_evaluator)
- Sensitive information detection
- Informed consent verification

AI-assisted deep review is handled by the API layer using execute_ai_call.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from ..core.sqp_evaluator import evaluate_survey_quality
from ..schemas.compliance import ComplianceFinding, ComplianceSuggestion


# ── Sensitive Information Lexicon ───────────────────────────────────────

# Personal Identifiable Information (PII) keywords
_SENSITIVE_PII_ZH = [
    "身份证", "身份证号", "身份证号码",  # National ID
    "手机号", "手机号码", "联系电话",  # Phone numbers
    "银行卡", "银行卡号", "银行账号",  # Bank account
    "家庭住址", "详细地址", "门牌号",  # Precise address
    "护照号", "护照号码",  # Passport
    "车牌号", "驾驶证号",  # Vehicle / driver's license
    "微信号", "QQ号",  # Social media IDs
    "电子邮箱",  # Email (may be necessary for follow-up, flag as warning)
]

_SENSITIVE_SPECIAL_ZH = [  # PIPL Art.28 sensitive personal info
    "宗教信仰", "宗教", "信什么教",  # Religion
    "政治观点", "政治立场", "政治面貌",  # Political views (special: 政治面貌 is CCP standard)
    "性取向", "性行为",  # Sexual orientation
    "族裔", "民族成分",  # Ethnicity
    "生物特征", "指纹", "人脸", "面部识别",  # Biometrics
    "健康", "病史", "病历", "就诊", "残疾", "精神疾病",  # Health
    "行踪轨迹", "定位", "GPS", "地理位置",  # Location tracking
    "犯罪记录", "刑事处罚",  # Criminal records
]

_SENSITIVE_PII_EN = [
    "national id", "social security number", "ssn",
    "passport number", "driver's license",
    "credit card", "bank account",
    "phone number", "mobile number",
    "home address", "mailing address",
    "date of birth", "birth date",
]

_SENSITIVE_SPECIAL_EN = [  # GDPR Art.9 special categories
    "religion", "religious belief", "faith",
    "political opinion", "political affiliation",
    "sexual orientation", "sex life",
    "racial", "ethnic origin", "ethnicity",
    "biometric", "fingerprint", "facial recognition",
    "health", "medical record", "medical history", "disability",
    "genetic data", "genetic",
    "trade union membership",
    "criminal conviction", "criminal record",
]

# Combined regex patterns
_PII_PATTERNS_ZH = re.compile(
    "|".join(re.escape(kw) for kw in _SENSITIVE_PII_ZH + _SENSITIVE_SPECIAL_ZH),
    re.IGNORECASE,
)
_PII_PATTERNS_EN = re.compile(
    "|".join(re.escape(kw) for kw in _SENSITIVE_PII_EN + _SENSITIVE_SPECIAL_EN),
    re.IGNORECASE,
)


# ── PIPL Compliance Checklist ───────────────────────────────────────────

_PIPL_CHECKS = [
    {
        "id": "pipl_consent",
        "article": "PIPL Art.13-14",
        "name": "知情同意声明",
        "description": "问卷开头是否包含明确的知情同意段落？",
        "severity": "error",
    },
    {
        "id": "pipl_minimization",
        "article": "PIPL Art.6",
        "name": "数据最小化",
        "description": "是否仅收集必要个人信息？有无身份证号、精确地址等非必要字段？",
        "severity": "error",
    },
    {
        "id": "pipl_storage_period",
        "article": "PIPL Art.19",
        "name": "数据存储期限",
        "description": "是否声明数据存储期限？",
        "severity": "warning",
    },
    {
        "id": "pipl_cross_border",
        "article": "PIPL Art.38",
        "name": "数据跨境传输",
        "description": "如数据可能出境，是否说明跨境传输机制？",
        "severity": "warning",
    },
    {
        "id": "pipl_rights",
        "article": "PIPL Art.44-47",
        "name": "受访者权利说明",
        "description": "是否说明查阅、更正、删除、撤回同意的权利？",
        "severity": "warning",
    },
    {
        "id": "pipl_sensitive_extra",
        "article": "PIPL Art.28",
        "name": "敏感个人信息额外保护",
        "description": "如收集敏感个人信息（宗教/健康/行踪等），是否有额外保护措施？",
        "severity": "error",
    },
]

# ── GDPR Checklist ──────────────────────────────────────────────────────

_GDPR_CHECKS = [
    {
        "id": "gdpr_legal_basis",
        "article": "GDPR Art.6",
        "name": "Legal Basis Statement",
        "description": "Does the survey state the legal basis for processing "
        "(consent, legitimate interest, etc.)?",
        "severity": "error",
    },
    {
        "id": "gdpr_controller",
        "article": "GDPR Art.13",
        "name": "Data Controller Identity",
        "description": "Is the data controller clearly identified with contact details?",
        "severity": "error",
    },
    {
        "id": "gdpr_dpo",
        "article": "GDPR Art.37",
        "name": "DPO Contact",
        "description": "Is a Data Protection Officer contact provided "
        "(if required by the nature of processing)?",
        "severity": "warning",
    },
    {
        "id": "gdpr_complaint",
        "article": "GDPR Art.77",
        "name": "Right to Lodge Complaint",
        "description": "Is the right to lodge a complaint with a supervisory "
        "authority mentioned?",
        "severity": "warning",
    },
    {
        "id": "gdpr_transfer",
        "article": "GDPR Art.44-49",
        "name": "International Transfer",
        "description": "If data may be transferred internationally, "
        "is the mechanism stated (adequacy decision, SCCs)?",
        "severity": "warning",
    },
]


# ── Consent Verification Patterns ───────────────────────────────────────

_CONSENT_KEYWORDS_ZH = [
    "知情同意", "同意参加", "自愿参与", "自愿参加",
    "隐私保护", "个人信息保护", "数据保护",
    "匿名", "保密", "退出", "撤回",
]

_CONSENT_KEYWORDS_EN = [
    "informed consent", "voluntary participation",
    "privacy", "data protection", "confidential",
    "anonymous", "right to withdraw", "opt out",
]


# ── Scanner Class ───────────────────────────────────────────────────────


class ComplianceScanner:
    """Rule-based compliance scanner for survey JSON content.

    Performs deterministic checks across 6 dimensions:
    PIPL baseline, GDPR baseline, bias detection, sensitive info,
    informed consent, and data minimization.
    """

    def __init__(self, survey_json: dict, language: str = "zh"):
        """Initialize with a parsed SurveyJS JSON survey definition.

        Args:
            survey_json: Full SurveyJS survey JSON (pages, elements, etc.)
            language: Primary language of the survey ("zh" or "en")
        """
        self.survey = survey_json
        self.language = language.lower()
        self._extract_texts()

    def _extract_texts(self) -> None:
        """Extract all textual content from the survey JSON for scanning."""
        self.all_text: str = ""
        self.question_texts: list[dict] = []  # [{name, title, type, choices}]

        for page in self.survey.get("pages", []):
            for elem in page.get("elements", []):
                if elem.get("type") == "panel":
                    for nested in elem.get("elements", []):
                        self._process_element(nested)
                else:
                    self._process_element(elem)

    def _process_element(self, elem: dict) -> None:
        """Process a single survey element, extracting text."""
        name = elem.get("name", "")
        title = elem.get("title", "")
        qtype = elem.get("type", "")
        choices = elem.get("choices", [])

        self.all_text += " " + title
        if "description" in elem:
            self.all_text += " " + elem["description"]
        if "commentText" in elem:
            self.all_text += " " + elem["commentText"]

        # Collect choices text
        for c in choices:
            choice_text = c.get("text", "")
            self.all_text += " " + choice_text

        self.question_texts.append({
            "name": name,
            "title": title,
            "type": qtype,
            "choices": choices,
        })

    # ─── Public Scan Methods ─────────────────────────────────────────

    def scan_pipl(self) -> tuple[list[ComplianceFinding], list[ComplianceSuggestion]]:
        """Run PIPL compliance checklist."""
        findings: list[ComplianceFinding] = []
        suggestions: list[ComplianceSuggestion] = []

        text_lower = self.all_text.lower()

        for check in _PIPL_CHECKS:
            passed = self._evaluate_pipl_check(check["id"], text_lower)
            if passed:
                findings.append(ComplianceFinding(
                    dimension="pipl",
                    issue=f"✅ {check['name']}",
                    severity="info",
                    reference=check["article"],
                ))
            else:
                findings.append(ComplianceFinding(
                    dimension="pipl",
                    issue=f"❌ {check['name']}：{check['description']}",
                    severity=check["severity"],
                    reference=check["article"],
                ))
                suggestions.append(ComplianceSuggestion(
                    priority="high" if check["severity"] == "error" else "medium",
                    title=f"添加{check['name']}",
                    description=check["description"],
                    reference=check["article"],
                ))

        return findings, suggestions

    def _evaluate_pipl_check(self, check_id: str, text_lower: str) -> bool:
        """Evaluate a single PIPL check against the survey text."""
        if check_id == "pipl_consent":
            return any(
                kw in text_lower for kw in _CONSENT_KEYWORDS_ZH
            )
        elif check_id == "pipl_minimization":
            hit = self._count_pii_matches()
            return hit == 0  # Fail if any PII keywords detected
        elif check_id == "pipl_storage_period":
            return any(
                kw in text_lower for kw in ["存储期限", "保存期限", "保留期限", "保存至", "保留至"]
            )
        elif check_id == "pipl_cross_border":
            # Not required for domestic-only surveys; pass if no cross-border mention
            has_cross = any(
                kw in text_lower
                for kw in ["跨境", "境外", "国外服务器", "overseas", "cross-border"]
            )
            if not has_cross:
                return True  # No cross-border concern
            return any(
                kw in text_lower
                for kw in ["安全评估", "标准合同", "认证", "影响评估", "adequacy", "SCC"]
            )
        elif check_id == "pipl_rights":
            return any(
                kw in text_lower
                for kw in ["查阅", "更正", "删除", "撤回", "复制", "投诉", "举报"]
            )
        elif check_id == "pipl_sensitive_extra":
            special_hits = self._count_special_hits()
            if special_hits == 0:
                return True  # No special category data collected
            return any(
                kw in text_lower
                for kw in ["额外保护", "单独同意", "必要性说明", "impact assessment"]
            )
        return True

    def scan_gdpr(self) -> tuple[list[ComplianceFinding], list[ComplianceSuggestion]]:
        """Run GDPR compliance checklist."""
        findings: list[ComplianceFinding] = []
        suggestions: list[ComplianceSuggestion] = []

        text_lower = self.all_text.lower()

        for check in _GDPR_CHECKS:
            passed = self._evaluate_gdpr_check(check["id"], text_lower)
            if passed:
                findings.append(ComplianceFinding(
                    dimension="gdpr",
                    issue=f"✅ {check['name']}",
                    severity="info",
                    reference=check["article"],
                ))
            else:
                findings.append(ComplianceFinding(
                    dimension="gdpr",
                    issue=f"❌ {check['name']}: {check['description']}",
                    severity=check["severity"],
                    reference=check["article"],
                ))
                suggestions.append(ComplianceSuggestion(
                    priority="high" if check["severity"] == "error" else "medium",
                    title=f"Add {check['name']}",
                    description=check["description"],
                    reference=check["article"],
                ))

        return findings, suggestions

    def _evaluate_gdpr_check(self, check_id: str, text_lower: str) -> bool:
        """Evaluate a single GDPR check."""
        if check_id == "gdpr_legal_basis":
            return any(
                kw in text_lower
                for kw in ["legal basis", "lawful basis", "consent",
                           "legitimate interest", "public interest",
                           "contractual necessity", "vital interest"]
            )
        elif check_id == "gdpr_controller":
            return any(
                kw in text_lower
                for kw in ["data controller", "controller", "responsible for",
                           "institution", "university", "organization"]
            )
        elif check_id == "gdpr_dpo":
            return any(
                kw in text_lower
                for kw in ["data protection officer", "DPO", "dpo@", "privacy@"]
            )
        elif check_id == "gdpr_complaint":
            return any(
                kw in text_lower
                for kw in ["lodge a complaint", "supervisory authority",
                           "data protection authority", "right to complain"]
            )
        elif check_id == "gdpr_transfer":
            has_transfer = any(
                kw in text_lower
                for kw in ["transfer", "international", "outside the",
                           "third country", "cross-border", "overseas"]
            )
            if not has_transfer:
                return True
            return any(
                kw in text_lower
                for kw in ["adequacy decision", "standard contractual clauses",
                           "SCCs", "binding corporate rules", "BCRs"]
            )
        return True

    def scan_sensitive_info(self) -> tuple[
        list[ComplianceFinding], list[ComplianceSuggestion]
    ]:
        """Scan for sensitive personal information in questionnaire text."""
        findings: list[ComplianceFinding] = []
        suggestions: list[ComplianceSuggestion] = []

        pii_hits = self._count_pii_matches()
        special_hits = self._count_special_hits()

        # Per-question PII scan
        for qt in self.question_texts:
            qtext = qt["title"] + " " + str(qt.get("choices", ""))
            hits = []
            for kw in _SENSITIVE_PII_ZH + _SENSITIVE_SPECIAL_ZH:
                if kw in qtext:
                    hits.append(kw)
            if hits:
                findings.append(ComplianceFinding(
                    dimension="sensitive_info",
                    issue=f"问题 '{qt['name']}' 包含敏感信息关键词: {', '.join(hits[:5])}",
                    severity="warning" if len(hits) == 1 else "error",
                    evidence=qt["title"],
                ))
                suggestions.append(ComplianceSuggestion(
                    priority="high",
                    title=f"审查问题 '{qt['name']}'",
                    description=f"该问题可能涉及敏感个人信息收集（PIPL Art.28），"
                    f"请确认是否必要。检测到: {', '.join(hits[:5])}",
                    reference="PIPL Art.28 / GDPR Art.9",
                ))

        # Summary finding
        if special_hits > 0:
            findings.insert(0, ComplianceFinding(
                dimension="sensitive_info",
                issue=f"检测到 {special_hits} 处敏感个人信息提及 "
                f"（PIPL Art.28 保护类别）",
                severity="error",
                reference="PIPL Art.28 / GDPR Art.9",
            ))
            suggestions.insert(0, ComplianceSuggestion(
                priority="critical",
                title="敏感个人信息处理合规审查",
                description=f"问卷包含 PIPL Art.28 定义的敏感个人信息类别。"
                f"需要：1) 单独同意 2) 必要性说明 3) 影响评估（如适用）。"
                f"共检测到 {special_hits} 处。",
                reference="PIPL Art.28-32",
            ))

        return findings, suggestions

    def scan_consent(self) -> tuple[
        list[ComplianceFinding], list[ComplianceSuggestion]
    ]:
        """Verify informed consent presence and quality."""
        findings: list[ComplianceFinding] = []
        suggestions: list[ComplianceSuggestion] = []

        text_lower = self.all_text.lower()
        consent_matches = [
            kw for kw in _CONSENT_KEYWORDS_ZH + _CONSENT_KEYWORDS_EN
            if kw in text_lower
        ]

        if not consent_matches:
            findings.append(ComplianceFinding(
                dimension="consent",
                issue="❌ 未检测到知情同意相关内容",
                severity="error",
                reference="PIPL Art.13-14 / GDPR Art.7",
            ))
            suggestions.append(ComplianceSuggestion(
                priority="critical",
                title="添加知情同意段落",
                description="在问卷开头添加知情同意声明，包含："
                "研究目的、数据处理方式、自愿参与声明、退出权利。",
                reference="PIPL Art.13-14",
            ))
        elif len(consent_matches) < 3:
            findings.append(ComplianceFinding(
                dimension="consent",
                issue=f"⚠️ 知情同意内容不完整，仅检测到 {len(consent_matches)} 项关键要素",
                severity="warning",
                evidence=f"检测到: {', '.join(consent_matches)}",
                reference="PIPL Art.13-17",
            ))
            suggestions.append(ComplianceSuggestion(
                priority="medium",
                title="完善知情同意内容",
                description="建议补充：数据存储期限、受访者权利（查阅/更正/删除）、联系方式。",
                reference="PIPL Art.17",
            ))
        else:
            findings.append(ComplianceFinding(
                dimension="consent",
                issue=f"✅ 知情同意内容完整（{len(consent_matches)} 项要素）",
                severity="info",
                evidence=f"检测到: {', '.join(consent_matches[:5])}",
                reference="PIPL Art.13-17 / GDPR Art.7",
            ))

        return findings, suggestions

    def scan_bias(self) -> tuple[
        list[ComplianceFinding], list[ComplianceSuggestion]
    ]:
        """Run bias detection using the SQP evaluator."""
        findings: list[ComplianceFinding] = []
        suggestions: list[ComplianceSuggestion] = []

        try:
            report = evaluate_survey_quality(
                self.survey, survey_id="compliance_scan"
            )

            if report.total_flags > 0:
                findings.append(ComplianceFinding(
                    dimension="bias",
                    issue=f"检测到 {report.total_flags} 个方法论风险项",
                    severity="warning" if report.total_flags < 3 else "error",
                    evidence=f"SQP 质量分数: {report.overall_quality:.2f}",
                ))
                for item in report.items:
                    if item.flags:
                        findings.append(ComplianceFinding(
                            dimension="bias",
                            issue=f"问题 {item.item_id}: {', '.join(item.flags)}",
                            severity="warning",
                            evidence=item.suggestions[0] if item.suggestions else "",
                        ))
            else:
                findings.append(ComplianceFinding(
                    dimension="bias",
                    issue="✅ 未检测到显著方法论偏差",
                    severity="info",
                ))
        except Exception:
            findings.append(ComplianceFinding(
                dimension="bias",
                issue="⚠️ 偏差检测未能完成（问卷结构可能不标准）",
                severity="warning",
            ))

        return findings, suggestions

    # ─── Full Scan ───────────────────────────────────────────────────

    def scan_all(self) -> dict:
        """Run all compliance checks and return aggregated results.

        Returns:
            dict with findings, suggestions, and risk_score across all dimensions.
        """
        all_findings: list[ComplianceFinding] = []
        all_suggestions: list[ComplianceSuggestion] = []

        # Run all scans
        for scan_name, scan_fn in [
            ("pipl_baseline", self.scan_pipl),
            ("gdpr_baseline", self.scan_gdpr),
            ("sensitive_info", self.scan_sensitive_info),
            ("consent", self.scan_consent),
            ("bias", self.scan_bias),
        ]:
            f, s = scan_fn()
            all_findings.extend(f)
            all_suggestions.extend(s)

        # Compute risk score (0-100)
        severity_weights = {"info": 0, "warning": 10, "error": 25}
        total_score = sum(
            severity_weights.get(f.severity, 0)
            for f in all_findings
        )
        max_possible = len(all_findings) * 25
        risk_score = round(
            (total_score / max_possible * 100) if max_possible > 0 else 0, 1
        )

        risk_level = (
            "low" if risk_score <= 20
            else "medium" if risk_score <= 40
            else "high" if risk_score <= 60
            else "critical"
        )

        # Count statuses
        items_checked = len(all_findings)
        items_passed = sum(1 for f in all_findings if f.severity == "info")
        items_warning = sum(1 for f in all_findings if f.severity == "warning")
        items_failed = sum(1 for f in all_findings if f.severity == "error")

        return {
            "findings": all_findings,
            "suggestions": all_suggestions,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "items_checked": items_checked,
            "items_passed": items_passed,
            "items_warning": items_warning,
            "items_failed": items_failed,
        }

    # ─── Helpers ─────────────────────────────────────────────────────

    def _count_pii_matches(self) -> int:
        """Count total PII keyword matches in survey text."""
        zh_matches = len(_PII_PATTERNS_ZH.findall(self.all_text))
        en_matches = len(_PII_PATTERNS_EN.findall(self.all_text.lower()))
        return zh_matches + en_matches

    def _count_special_hits(self) -> int:
        """Count matches for special category data (Art.28 / Art.9)."""
        zh_hits = sum(
            1 for kw in _SENSITIVE_SPECIAL_ZH
            if kw in self.all_text
        )
        en_hits = sum(
            1 for kw in _SENSITIVE_SPECIAL_EN
            if kw in self.all_text.lower()
        )
        return zh_hits + en_hits
