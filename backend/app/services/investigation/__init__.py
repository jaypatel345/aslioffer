"""
Investigation service package for AsliOffer.
Provides the unified contract-v1 pipeline entry point.
"""

from app.services.investigation.pipeline import investigate_case

__all__ = ["investigate_case"]
