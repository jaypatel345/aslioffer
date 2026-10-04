"""
Investigation service package for AsliOffer.
Provides the unified contract-v1 pipeline entry point.
"""

from app.services.investigation.pipeline import investigate_case
from app.services.investigation.budget import InvestigationBudget, BudgetManager
from app.services.investigation.planner import InvestigationPlanner, PlanStep
from app.services.investigation.corroborator import (
    JobCorroborationService,
    JobCorroborationResult,
    is_public_job_reference,
    evaluate_application_destination,
    generate_confirmation_draft,
)

__all__ = [
    "investigate_case",
    "InvestigationBudget",
    "BudgetManager",
    "InvestigationPlanner",
    "PlanStep",
    "JobCorroborationService",
    "JobCorroborationResult",
    "is_public_job_reference",
    "evaluate_application_destination",
    "generate_confirmation_draft",
]
