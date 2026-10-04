"""
Contextual scam classification engine for AsliOffer (Task 6).

Distinguishes actual payment/credential demands from negated policies,
quoted anti-fraud advisories, ordinary platform mentions, and ambiguous wording.
Operates deterministically over raw text and structured contextual hints.
"""

import re
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple


# ============================================================================
# 1. Modality and Signal Data Structures
# ============================================================================

class ScamModality:
    ACTIVE_DEMAND = "active_demand"
    NEGATED_POLICY = "negated_policy"
    QUOTED_ADVISORY = "quoted_advisory"
    AMBIGUOUS = "ambiguous"


class ScamSignalCode:
    UPFRONT_FEE_DEMAND = "UPFRONT_FEE_DEMAND"
    UNLOCK_PAYMENT_DEMAND = "UNLOCK_PAYMENT_DEMAND"
    CREDENTIAL_THEFT_DEMAND = "CREDENTIAL_THEFT_DEMAND"
    UPI_PAYMENT_REQUEST = "UPI_PAYMENT_REQUEST"
    TELEGRAM_COMMUNICATION = "TELEGRAM_COMMUNICATION"
    WHATSAPP_RECRUITMENT_CHANNEL = "WHATSAPP_RECRUITMENT_CHANNEL"
    NEGATED_FEE_POLICY = "NEGATED_FEE_POLICY"
    QUOTED_SCAM_ADVISORY = "QUOTED_SCAM_ADVISORY"
    UNSUPPORTED_STRUCTURED_HINT = "UNSUPPORTED_STRUCTURED_HINT"


@dataclass
class SignalAssessment:
    signal_code: str
    modality: str  # active_demand | negated_policy | quoted_advisory | ambiguous
    severity: str  # CRITICAL | HIGH | MEDIUM | LOW | INFO
    explanation: str
    source_quote: Optional[str] = None
    source_span: Optional[Dict[str, Any]] = None
    contributes_to_verdict: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_code": self.signal_code,
            "modality": self.modality,
            "severity": self.severity,
            "explanation": self.explanation,
            "source_quote": self.source_quote,
            "source_span": self.source_span,
            "contributes_to_verdict": self.contributes_to_verdict,
        }


# ============================================================================
# 2. Secret Redaction & Sanitization
# ============================================================================

def sanitize_and_redact_secrets(text: str) -> str:
    """
    Sanitizes raw text to redact sensitive authentication secrets
    (OTPs, PINs, passwords) before logging, quoting, or storing.
    Guarantees that raw secret values are never retained in quotes or logs.
    """
    if not text:
        return ""

    sanitized = text

    # Redact numeric OTPs / PINs (4-8 digits) in secret-sharing contexts
    sanitized = re.sub(
        r'(?i)(\b(?:otp|pin|passcode|code)\s*(?:is|:|=|#|-)?\s*)(\d{4,8})\b',
        r'\1[REDACTED_OTP]',
        sanitized,
    )
    sanitized = re.sub(
        r'(?i)\b(\d{6})\s+(?=is\s+your\s+(?:bank\s+)?(?:verification\s+)?otp\b)',
        '[REDACTED_OTP] ',
        sanitized,
    )

    # Labelled values only; bare 'password with HR' must retain demand context.
    sanitized = re.sub(
        r"(?i)(\b(?:password|pin|otp|passcode)\s*(?:is\s+|[:=#-]\s*))([^\s,;]+)",
        r"\1[REDACTED_SECRET]", sanitized,
    )
    sanitized = re.sub(
        r"(?i)(\bpassword\s+)(?!with\b|and\b|or\b|immediately\b|to\b|for\b|must\b|should\b|required\b)([^\s,.;]+)",
        r"\1[REDACTED_PASSWORD]", sanitized,
    )

    return sanitized


# ============================================================================
# 3. Contextual Pattern Matchers
# ============================================================================

# Advisory framing words that indicate text is cautioning against external fraud
ADVISORY_PREFIX_PATTERNS = [
    r'\b(?:security\s+advisory|fraud\s+advisory|fraud\s+alert|anti[- ]scam|caution|warning)\b',
    r'\b(?:fraudsters|scammers|cyber[- ]criminals)\s+(?:are\s+)?(?:circulating|sending|asking|posing|demanding)\b',
    r'\bbeware\s+of\s+(?:fake|fraudulent|recruiters|unauthorized|third[- ]party)\b',
    r'\bwarning:\s*(?:fake|fraudulent|misusing|scam)\b',
    r'\bwe\s+have\s+been\s+alerted\s+to\s+fraudulent\b',
    r'\bdo\s+not\s+fall\s+for\s+(?:fake|fraudulent)\b',
]

# Negation terms indicating company anti-scam policies
POLICY_NEGATION_PATTERNS = [
    r'\b(?:fee|fees|deposit|payment|charge)\b.*?\b(?:not required|not mandatory|not payable|is optional|are optional)\b',
    r'\b(?:never|do\s+not|does\s+not|will\s+not|shall\s+not|cannot)\s+(?:charge|ask|solicit|require|demand|collect)\b',
    r'\bno\s+(?:fees?|charges?|deposits?|payments?)\s+(?:are\s+)?(?:charged|required|solicited|collected)\b',
    r'\b(?:free\s+of\s+charge|at\s+no\s+(?:cost|fee|charge)|without\s+any\s+(?:fee|deposit|charge))\b',
    r'\b(?:never|do\s+not)\s+(?:share|send|provide|forward|submit|pay|transfer|deposit|recharge)\b',
    r'\bdo\s+not\s+transfer\s+funds\b',
    r'\benter\s+the\s+otp\s+on\s+the\s+official\s+portal\s+yourself\b',
]

# Upfront fee terminology
UPFRONT_FEE_PATTERNS = [
    r'\b(?:registration|onboarding|training|laptop|equipment|document\s+verification|verification|interview|orientation|courier)\s+(?:fee|fees|deposit|deposits|charge|charges|cost)\b',
    r'\b(?:refundable\s+)?security\s+deposit\b',
    r'\brefundable\s+(?:fee|deposit|charge)\b',
    r'\bsecurity\s+clearance\s+charges?\b',
    r'\blaptop\s+security\b',
]

# Unlock / withdrawal / release extortion terminology
UNLOCK_EARNINGS_PATTERNS = [
    r'\bto\s+(?:withdraw|unlock|release)\s+.*?\b(?:pay|deposit|transfer|recharge)\b',
    r'\b(?:unlock|release)\s+(?:your\s+)?(?:earnings|job|tasks?|wages?|balance|funds?|commissions?|account|wallet)\b',
    r'\bwallet\s+release\s+(?:charge|fee)\b',
    r'\bclearing\s+(?:agent\s+)?(?:charge|fee)\b',
    r'\b(?:pay|deposit|transfer|recharge)\s+.*?\bto\s+(?:unlock|withdraw|release|activate\s+payout)\b',
    r'\brecharge\s+(?:your\s+)?wallet\s+to\s+withdraw\b',
    r'\bpay\s+.*?\bwallet\s+release\b',
]

# Credential / OTP / password theft terminology
CREDENTIAL_THEFT_PATTERNS = [
    r'\b(?:share|provide|send|forward|submit)\s+(?:your\s+)?(?:bank\s+)?(?:verification\s+)?otp\b',
    r'\b(?:share|provide|send|forward|submit)\s+(?:your\s+)?(?:(?:net[- ]banking|login|account)\s+)?password\b',
    r'\b(?:share|provide|send|forward|submit)\s+(?:your\s+)?(?:atm\s+)?pin\b',
    r'\bshare\s+your\s+bank\s+otp\s+and\s+net[- ]banking\b',
    r'\botp\s+and\s+.*?\bpassword\s+immediately\s+with\s+hr\b',
    r'\bshare\s+.*?\botp\b.*?\bwith\s+(?:hr|recruiter|payroll|clearing\s+agent)\b',
]

# Self-service OTP directions (legitimate, non-theft)
SELF_SERVICE_OTP_PATTERNS = [
    r'\benter\s+the\s+otp\s+(?:on|in)\s+the\s+official\s+portal\b',
    r'\benter\s+(?:the\s+)?otp\s+yourself\b',
    r'\benter\s+the\s+otp\s+sent\s+to\s+your\s+(?:registered\s+)?mobile\s+on\s+the\s+(?:portal|page)\b',
    r'\bdo\s+not\s+share\s+your\s+otp\b',
]

# UPI and mobile payment rail patterns
UPI_PATTERNS = [
    r'\b(?:via|through|using|to)\s+upi\b',
    r'\b(?:upi\s+id|gpay|phonepe|paytm)\b',
    r'@(?:okaxis|okhdfcbank|okhdfc|okicici|oksbi|upi|ybl|ibl|paytm)\b',
]

# Salary direction patterns (employer to candidate, not a fee demand)
SALARY_CREDIT_PATTERNS = [
    r'\bsalary\s+(?:will\s+be\s+credited|is\s+paid|transfer|credit)\s+(?:through|via|by|using)\b',
    r'\bdirect[- ]deposit\s+salary\s+account\b',
    r'\bearnings\s+plus\s+release\s+fee\s+will\s+be\s+credited\b',
    r'\bcredited\s+within\s+\d+\s+minutes\b',
]


# ============================================================================
# 4. Contextual Classifier Implementation
# ============================================================================

class ScamClassifier:
    """
    Deterministic contextual classifier for recruitment scam signals.
    Evaluates individual clauses and sentences with localized negation,
    quoted advisory attribution, and payment direction analysis.
    """

    def __init__(self):
        pass

    def split_into_clauses(self, text: str) -> List[Tuple[str, int, int]]:
        """
        Splits text into sentences/clauses, returning (clause_text, start_offset, end_offset).
        """
        clauses: List[Tuple[str, int, int]] = []
        if not text:
            return clauses

        # Split on sentence boundaries and line breaks
        pattern = re.compile(r'.+?(?:[.!?](?=\s|$)|[;\n]+|\s+(?:but|however|yet)\s+|[, ]+and\s+(?=(?:please\s+)?(?:pay|transfer|share|send|provide|recharge)\b)|$)', re.I)
        for match in pattern.finditer(text):
            clause = match.group().strip()
            if clause:
                clauses.append((clause, match.start(), match.end()))

        return clauses

    def classify(
        self,
        raw_text: str,
        demanded_fee: Optional[str] = None,
        payment_method: Optional[str] = None,
        flags: Optional[List[str]] = None,
    ) -> List[SignalAssessment]:
        """
        Analyzes the submitted offer text and structured hints to produce
        granular, evidence-backed SignalAssessments.
        """
        flags = flags or []
        sanitized_text = sanitize_and_redact_secrets(raw_text)
        clauses = self.split_into_clauses(sanitized_text)

        assessments: List[SignalAssessment] = []

        # 1. Analyze clauses for raw-text grounded signals
        for clause, start_pos, end_pos in clauses:
            clause_lower = clause.lower()

            # A. Check for Quoted Advisory Context
            is_quoted_advisory = self._is_quoted_advisory_clause(clause, sanitized_text)

            # B. Check for Negated Policy Context
            is_negated_policy = self._is_negated_policy_clause(clause_lower)

            # C. Check for Credential Theft Demands
            self._evaluate_credential_signals(
                clause, clause_lower, start_pos, end_pos,
                is_negated_policy, is_quoted_advisory, sanitized_text, assessments
            )

            # D. Check for Unlock-Earnings Demands
            self._evaluate_unlock_signals(
                clause, clause_lower, start_pos, end_pos,
                is_negated_policy, is_quoted_advisory, sanitized_text, assessments
            )

            # E. Check for Upfront Fee Demands
            self._evaluate_upfront_fee_signals(
                clause, clause_lower, start_pos, end_pos,
                is_negated_policy, is_quoted_advisory, sanitized_text, assessments
            )

            # F. Check for UPI Payment Channel Request
            self._evaluate_upi_signals(
                clause, clause_lower, start_pos, end_pos,
                is_negated_policy, is_quoted_advisory, sanitized_text, assessments
            )

            # G. Check for Platform Mentions (Telegram / WhatsApp)
            self._evaluate_platform_signals(
                clause, clause_lower, start_pos, end_pos,
                is_negated_policy, is_quoted_advisory, sanitized_text, assessments
            )

        # 2. Evaluate Structured Hints vs Document Evidence
        self._evaluate_structured_hints(
            sanitized_text, demanded_fee, payment_method, flags, assessments
        )

        return assessments

    def _is_quoted_advisory_clause(self, clause: str, full_text: str) -> bool:
        """
        Determines whether a clause is framed as an anti-scam warning or security advisory.
        Quotation marks alone do not suppress a demand unless framed by advisory context.
        """
        lower = clause.lower()
        if any(re.search(pat, lower) for pat in ADVISORY_PREFIX_PATTERNS):
            return True
        start = full_text.find(clause)
        prefix = full_text[max(0, start - 160):start].strip().lower()
        if clause.lstrip().startswith(('"', '“', '‘')) and prefix.endswith((':', 'example.')):
            return any(re.search(pat, prefix) for pat in ADVISORY_PREFIX_PATTERNS)
        return False

    def _is_negated_policy_clause(self, clause_lower: str) -> bool:
        """
        Checks if the clause expresses an explicit negative policy (e.g. 'We never charge a deposit').
        """
        for pat in POLICY_NEGATION_PATTERNS:
            if re.search(pat, clause_lower):
                return True
        return False

    def _make_span(self, sanitized_text: str, quote: str) -> Optional[Dict[str, Any]]:
        """
        Creates a verified span guaranteed to match the sanitized buffer substring.
        """
        if not quote:
            return None
        start = sanitized_text.find(quote)
        if start == -1 or sanitized_text.count(quote) != 1:
            return None
        return {
            "start_offset": start,
            "end_offset": start + len(quote),
            "target_text": "sanitized_buffer",
        }

    def _evaluate_credential_signals(
        self, clause: str, clause_lower: str, start_pos: int, end_pos: int,
        is_negated: bool, is_advisory: bool, sanitized_text: str, assessments: List[SignalAssessment]
    ):
        # Check self-service directions first
        for pat in SELF_SERVICE_OTP_PATTERNS:
            if re.search(pat, clause_lower):
                assessments.append(
                    SignalAssessment(
                        signal_code="SELF_SERVICE_OTP_DIRECTION",
                        modality=ScamModality.NEGATED_POLICY,
                        severity="INFO",
                        explanation="Candidate instructed to enter OTP directly on official portal; not credential sharing.",
                        source_quote=clause,
                        source_span=self._make_span(sanitized_text, clause),
                        contributes_to_verdict=False,
                    )
                )
                return

        # Check for credential theft solicitation
        has_cred_theft = any(re.search(pat, clause_lower) for pat in CREDENTIAL_THEFT_PATTERNS)
        if has_cred_theft:
            if is_negated:
                assessments.append(
                    SignalAssessment(
                        signal_code="NEGATED_CREDENTIAL_POLICY",
                        modality=ScamModality.NEGATED_POLICY,
                        severity="INFO",
                        explanation="Security disclaimer reminding candidate not to share OTPs or passwords.",
                        source_quote=clause,
                        source_span=self._make_span(sanitized_text, clause),
                        contributes_to_verdict=False,
                    )
                )
            elif is_advisory:
                assessments.append(
                    SignalAssessment(
                        signal_code=ScamSignalCode.QUOTED_SCAM_ADVISORY,
                        modality=ScamModality.QUOTED_ADVISORY,
                        severity="LOW",
                        explanation="Quoted advisory warning against OTP/password credential solicitation.",
                        source_quote=clause,
                        source_span=self._make_span(sanitized_text, clause),
                        contributes_to_verdict=False,
                    )
                )
            else:
                # Active credential theft demand
                assessments.append(
                    SignalAssessment(
                        signal_code=ScamSignalCode.CREDENTIAL_THEFT_DEMAND,
                        modality=ScamModality.ACTIVE_DEMAND,
                        severity="CRITICAL",
                        explanation="Direct solicitation of candidate's bank OTP, banking login password, or account secrets.",
                        source_quote=clause,
                        source_span=self._make_span(sanitized_text, clause),
                        contributes_to_verdict=True,
                    )
                )

    def _evaluate_unlock_signals(
        self, clause: str, clause_lower: str, start_pos: int, end_pos: int,
        is_negated: bool, is_advisory: bool, sanitized_text: str, assessments: List[SignalAssessment]
    ):
        has_unlock = any(re.search(pat, clause_lower) for pat in UNLOCK_EARNINGS_PATTERNS)

        if has_unlock and (is_negated or is_advisory or self._payment_request(clause_lower)):
            if is_negated:
                assessments.append(
                    SignalAssessment(
                        signal_code=ScamSignalCode.NEGATED_FEE_POLICY,
                        modality=ScamModality.NEGATED_POLICY,
                        severity="INFO",
                        explanation="Negated policy regarding task earnings release charges.",
                        source_quote=clause,
                        source_span=self._make_span(sanitized_text, clause),
                        contributes_to_verdict=False,
                    )
                )
            elif is_advisory:
                assessments.append(
                    SignalAssessment(
                        signal_code=ScamSignalCode.QUOTED_SCAM_ADVISORY,
                        modality=ScamModality.QUOTED_ADVISORY,
                        severity="LOW",
                        explanation="Quoted warning regarding task scam wallet recharge demands.",
                        source_quote=clause,
                        source_span=self._make_span(sanitized_text, clause),
                        contributes_to_verdict=False,
                    )
                )
            else:
                assessments.append(
                    SignalAssessment(
                        signal_code=ScamSignalCode.UNLOCK_PAYMENT_DEMAND,
                        modality=ScamModality.ACTIVE_DEMAND,
                        severity="CRITICAL",
                        explanation="Predatory extortion demand requiring payment or recharge to unlock task earnings or job wages.",
                        source_quote=clause,
                        source_span=self._make_span(sanitized_text, clause),
                        contributes_to_verdict=True,
                    )
                )

    def _evaluate_upfront_fee_signals(
        self, clause: str, clause_lower: str, start_pos: int, end_pos: int,
        is_negated: bool, is_advisory: bool, sanitized_text: str, assessments: List[SignalAssessment]
    ):
        has_fee_term = any(re.search(pat, clause_lower) for pat in UPFRONT_FEE_PATTERNS)

        if has_fee_term:
            if is_negated:
                assessments.append(
                    SignalAssessment(
                        signal_code=ScamSignalCode.NEGATED_FEE_POLICY,
                        modality=ScamModality.NEGATED_POLICY,
                        severity="INFO",
                        explanation="Anti-fraud policy disclaimer stating company does not charge recruitment or security fees.",
                        source_quote=clause,
                        source_span=self._make_span(sanitized_text, clause),
                        contributes_to_verdict=False,
                    )
                )
            elif is_advisory:
                assessments.append(
                    SignalAssessment(
                        signal_code=ScamSignalCode.QUOTED_SCAM_ADVISORY,
                        modality=ScamModality.QUOTED_ADVISORY,
                        severity="LOW",
                        explanation="Quoted fee language within an anti-scam security advisory cautioning candidates.",
                        source_quote=clause,
                        source_span=self._make_span(sanitized_text, clause),
                        contributes_to_verdict=False,
                    )
                )
            elif re.search(r"\b(?:we|company|employer)\s+(?:will\s+)?(?:pay|cover|reimburse|refund)\b", clause_lower):
                assessments.append(SignalAssessment(
                    signal_code="EMPLOYER_PAYMENT_DIRECTION", modality="informational", severity="INFO",
                    explanation="Employer covers or reimburses the fee; no candidate remittance is established.",
                    source_quote=clause, source_span=self._make_span(sanitized_text, clause),
                    contributes_to_verdict=False,
                ))
            elif not self._payment_request(clause_lower):
                assessments.append(SignalAssessment(
                    signal_code=ScamSignalCode.UPFRONT_FEE_DEMAND,
                    modality=ScamModality.AMBIGUOUS, severity="LOW",
                    explanation="Fee terminology is present without a clear candidate payment demand.",
                    source_quote=clause, source_span=self._make_span(sanitized_text, clause),
                    contributes_to_verdict=True,
                ))
            else:
                # Active upfront fee demand
                assessments.append(
                    SignalAssessment(
                        signal_code=ScamSignalCode.UPFRONT_FEE_DEMAND,
                        modality=ScamModality.ACTIVE_DEMAND,
                        severity="CRITICAL",
                        explanation="Direct demand for mandatory advance fee, security deposit, or equipment payment.",
                        source_quote=clause,
                        source_span=self._make_span(sanitized_text, clause),
                        contributes_to_verdict=True,
                    )
                )

    def _evaluate_upi_signals(
        self, clause: str, clause_lower: str, start_pos: int, end_pos: int,
        is_negated: bool, is_advisory: bool, sanitized_text: str, assessments: List[SignalAssessment]
    ):
        has_upi = any(re.search(pat, clause_lower) for pat in UPI_PATTERNS)
        if not has_upi:
            return

        # Check payment direction: Is employer paying salary to candidate?
        is_salary_credit = any(re.search(pat, clause_lower) for pat in SALARY_CREDIT_PATTERNS)
        if is_salary_credit and not any(re.search(pat, clause_lower) for pat in UPFRONT_FEE_PATTERNS + UNLOCK_EARNINGS_PATTERNS):
            assessments.append(
                SignalAssessment(
                    signal_code="SALARY_PAYMENT_DIRECTION",
                    modality="informational",
                    severity="INFO",
                    explanation="Payment channel mentioned in context of salary receipt from employer to candidate.",
                    source_quote=clause,
                    source_span=self._make_span(sanitized_text, clause),
                    contributes_to_verdict=False,
                )
            )
            return

        if is_negated:
            return
        if is_advisory:
            return

        # Check if tied to an active candidate-to-recruiter demand
        is_payment_demand = self._payment_request(clause_lower)

        if is_payment_demand:
            assessments.append(
                SignalAssessment(
                    signal_code=ScamSignalCode.UPI_PAYMENT_REQUEST,
                    modality=ScamModality.ACTIVE_DEMAND,
                    severity="HIGH",
                    explanation="Direct candidate-to-recruiter payment requested via UPI or mobile wallet channel.",
                    source_quote=clause,
                    source_span=self._make_span(sanitized_text, clause),
                    contributes_to_verdict=True,
                )
            )

    def _evaluate_platform_signals(
        self, clause: str, clause_lower: str, start_pos: int, end_pos: int,
        is_negated: bool, is_advisory: bool, sanitized_text: str, assessments: List[SignalAssessment]
    ):
        for platform, code in (("telegram", ScamSignalCode.TELEGRAM_COMMUNICATION),
                               ("whatsapp", ScamSignalCode.WHATSAPP_RECRUITMENT_CHANNEL)):
            if re.search(r"\b" + platform + r"\b", clause_lower):
                assessments.append(SignalAssessment(
                    signal_code=code, modality="informational", severity="INFO",
                    explanation="Communication channel mention alone does not establish a payment or credential demand.",
                    source_quote=clause, source_span=self._make_span(sanitized_text, clause),
                    contributes_to_verdict=False,
                ))

    @staticmethod
    def _payment_request(text: str) -> bool:
        # Employer paying/reimbursing the candidate is not candidate remittance.
        if re.search(r"\b(?:we|company|employer)\s+(?:will\s+)?(?:pay|cover|reimburse|refund)\b", text):
            return False
        return bool(re.search(
            r"\b(?:pay|transfer|remit|recharge|deposit|submit|send)\b.*?"
            r"\b(?:fee|deposit|charge|funds|money|amount|inr|rs|rupees|wallet|upi|gpay|phonepe|paytm|unlock|withdraw|release)\b"
            r"|\b(?:fee|deposit|charge|payment|recharge)\b.*?\b(?:required|mandatory|must|before|payable)\b"
            r"|\b(?:mandatory|required)\b.*?\b(?:fee|deposit|charge|payment)\b", text,
        ))

    def _evaluate_structured_hints(
        self,
        sanitized_text: str,
        demanded_fee: Optional[str],
        payment_method: Optional[str],
        flags: List[str],
        assessments: List[SignalAssessment],
    ):
        """
        Evaluates structured input hints against raw text.
        Structured hints must not force HIGH_RISK when raw text contradicts them
        or provides no supporting request.
        """
        active_fee_assessments = [a for a in assessments if a.signal_code == ScamSignalCode.UPFRONT_FEE_DEMAND and a.modality == ScamModality.ACTIVE_DEMAND]
        negated_policy_assessments = [a for a in assessments if a.signal_code == ScamSignalCode.NEGATED_FEE_POLICY]

        # Check demanded_fee hint
        has_fee_hint = bool(demanded_fee) or "DEMANDS_UPFRONT_FEE" in flags
        if has_fee_hint:
            if active_fee_assessments:
                # Corroborated by active demand in raw text
                pass
            elif negated_policy_assessments:
                # Explicitly contradicted by raw text negated policy
                assessments.append(
                    SignalAssessment(
                        signal_code=ScamSignalCode.UNSUPPORTED_STRUCTURED_HINT,
                        modality=ScamModality.NEGATED_POLICY,
                        severity="LOW",
                        explanation=f"Structured fee hint (fee indicator) is contradicted by explicit document policy stating company never charges fees.",
                        source_quote=negated_policy_assessments[0].source_quote,
                        source_span=negated_policy_assessments[0].source_span,
                        contributes_to_verdict=False,
                    )
                )
            else:
                # Uncorroborated hint: fee present in hint but completely missing from raw text
                assessments.append(
                    SignalAssessment(
                        signal_code=ScamSignalCode.UNSUPPORTED_STRUCTURED_HINT,
                        modality=ScamModality.AMBIGUOUS,
                        severity="MEDIUM",
                        explanation=f"Structured fee hint (fee indicator) is not corroborated by the submitted document text.",
                        source_quote=None,
                        source_span=None,
                        contributes_to_verdict=True,
                    )
                )

        # Check payment_method hint
        if payment_method and payment_method.upper() in {"UPI", "GPAY", "PHONEPE", "PAYTM"}:
            active_upi = [a for a in assessments if a.signal_code == ScamSignalCode.UPI_PAYMENT_REQUEST and a.modality == ScamModality.ACTIVE_DEMAND]
            if not active_upi and not active_fee_assessments and not any(a.signal_code == "SALARY_PAYMENT_DIRECTION" for a in assessments):
                if negated_policy_assessments:
                    assessments.append(
                        SignalAssessment(
                            signal_code=ScamSignalCode.UNSUPPORTED_STRUCTURED_HINT,
                            modality=ScamModality.NEGATED_POLICY,
                            severity="LOW",
                            explanation=f"Payment method '{payment_method}' in structured input is contradicted by explicit document policy.",
                            source_quote=negated_policy_assessments[0].source_quote,
                            source_span=negated_policy_assessments[0].source_span,
                            contributes_to_verdict=False,
                        )
                    )
                else:
                    assessments.append(
                        SignalAssessment(
                            signal_code=ScamSignalCode.UNSUPPORTED_STRUCTURED_HINT,
                            modality=ScamModality.AMBIGUOUS,
                            severity="LOW",
                            explanation=f"Payment method '{payment_method}' in structured input is uncorroborated by an active payment demand in the text.",
                            source_quote=None,
                            source_span=None,
                            contributes_to_verdict=True,
                        )
                    )
