"""
Planning pipeline for orchestrator discovery-to-itinerary processing.

This module orchestrates the planning pipeline that transforms raw discovery
results into a validated itinerary:

    Discovery (parallel) -> Aggregator -> Budget -> Route -> Validator

Per design doc Three-Phase Workflow and Pipeline Execution with Gap Awareness sections.
"""

# Import pipeline types first (these don't depend on agents)
from src.orchestrator.planning.pipeline import (
    DiscoveryContext,
    DiscoveryGap,
    DiscoveryStatus,
    PlanningPipeline,
    PlanningResult,
    ValidationGap,
    ValidationResult,
    build_gaps,
    run_planning_pipeline,
)

# Import agent types second (these depend on pipeline types)
from src.orchestrator.planning.agents import (
    AggregatedResults,
    AgentResultEntry,
    AggregatorAgent,
)

# Import modification types (for selective agent re-runs)
from src.orchestrator.planning.modification import (
    ModificationPlan,
    ModificationResult,
    analyze_modification,
    execute_modification,
)

__all__ = [
    # Agents
    "AggregatedResults",
    "AgentResultEntry",
    "AggregatorAgent",
    # Pipeline types
    "DiscoveryContext",
    "DiscoveryGap",
    "DiscoveryStatus",
    "PlanningPipeline",
    "PlanningResult",
    "ValidationGap",
    "ValidationResult",
    "build_gaps",
    "run_planning_pipeline",
    # Modification types
    "ModificationPlan",
    "ModificationResult",
    "analyze_modification",
    "execute_modification",
]
