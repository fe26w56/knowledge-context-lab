"""Offline, evidence-preserving experiments for agent context retrieval.

Retrieval runs locally; model_eval and workflow_eval make explicitly requested
API calls. Retrieval metrics alone are not answer-quality, end-to-end cost, or
availability metrics.
"""

from .retrieval import BudgetTooSmallError, RetrievalEngine

__all__ = ["BudgetTooSmallError", "RetrievalEngine"]
