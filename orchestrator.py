"""Adaptive swarm: shared batched evidence, then deterministic decisions.

The older LangGraph builder is retained for explicit experiments, but the web
and compatibility entry points no longer run a per-listing LLM graph.
"""
from functools import lru_cache
from typing import TypedDict, Optional, overload, Literal
from langgraph.graph import StateGraph, END

from schemas import Listing, ContextAnalysis, VisionCheck, StrategistDecision
from agents import context_analyst, vision_authenticator, lead_strategist


class SwarmState(TypedDict):
    listing: Listing
    resale_estimate: float
    analysis: Optional[ContextAnalysis]
    vision: Optional[VisionCheck]
    decision: Optional[StrategistDecision]
    reanalysis_done: bool


def node_analyst(state: SwarmState) -> SwarmState:
    state["analysis"] = context_analyst.analyze(state["listing"])
    return state


def node_vision(state: SwarmState) -> SwarmState:
    state["vision"] = vision_authenticator.check(state["listing"])
    return state


def node_reanalyst(state: SwarmState) -> SwarmState:
    """Loop-back target: re-read the description now with vision context attached."""
    listing = state["listing"]
    enriched_desc = listing.description + f"\n\n[Vision agent found: {', '.join(state['vision'].mismatches) or 'no mismatches'}]"
    enriched_listing = listing.model_copy(update={"description": enriched_desc})
    state["analysis"] = context_analyst.analyze(enriched_listing)
    state["reanalysis_done"] = True
    return state


def node_strategist(state: SwarmState) -> SwarmState:
    state["decision"] = lead_strategist.decide(
        state["listing"], state["analysis"], state["vision"], state["resale_estimate"]
    )
    return state


def route_after_vision(state: SwarmState) -> str:
    """The one loop-back: only re-query Analyst once, and only if it flagged low confidence."""
    if state["analysis"].needs_clarification and not state["reanalysis_done"]:
        return "reanalyst"
    return "strategist"


@lru_cache(maxsize=1)
def build_graph():
    graph = StateGraph(SwarmState)
    graph.add_node("analyst", node_analyst)
    graph.add_node("vision", node_vision)
    graph.add_node("reanalyst", node_reanalyst)
    graph.add_node("strategist", node_strategist)

    graph.set_entry_point("analyst")
    graph.add_edge("analyst", "vision")
    graph.add_conditional_edges("vision", route_after_vision, {
        "reanalyst": "reanalyst",
        "strategist": "strategist",
    })
    graph.add_edge("reanalyst", "strategist")
    graph.add_edge("strategist", END)
    return graph.compile()


@overload
def run_swarm(listing: Listing, resale_estimate: float, include_evidence: Literal[False] = False, *, cost_aware: bool = False, analysis: ContextAnalysis | None = None) -> StrategistDecision: ...


@overload
def run_swarm(
    listing: Listing, resale_estimate: float, include_evidence: Literal[True], *, cost_aware: bool = False, analysis: ContextAnalysis | None = None
) -> tuple[StrategistDecision, ContextAnalysis, VisionCheck]: ...


def run_swarm(listing: Listing, resale_estimate: float, include_evidence: bool = False, *, cost_aware: bool = False, analysis: ContextAnalysis | None = None):
    """Compatibility facade: one shared evidence pass, deterministic economics.

    Web search supplies its batch result. Legacy callers get a cached one-item
    batch, never the old context/vision/strategy/reanalysis fan-out.
    """
    evidence_reviewed = analysis is not None
    if analysis is None:
        if cost_aware:
            analysis = context_analyst._deterministic(listing)
        else:
            from agents.batch_analyst import analyze_shortlist, offer_id
            result = analyze_shortlist([listing], listing.title)
            key = offer_id(listing)
            analysis = result.analyses[key]
            evidence_reviewed = (result.statuses[key] in {'ai_completed', 'cache_reused'}
                                 and result.findings[key].relevance == 'match'
                                 and not analysis.needs_clarification)
    vision = VisionCheck(consistency_score=None, mismatches=['No per-listing vision call. Photo searches have separate bounded visual evidence.'], images_checked=0)
    decision = lead_strategist.decide(listing, analysis, vision, resale_estimate, use_ai=False)
    if listing.source != 'demo_cache' and not evidence_reviewed:
        decision.is_profitable = False
        decision.risk_level = 'high'
        decision.negotiation_message = None
        decision.reasoning = 'Needs verification: no validated matching AI evidence review. Displayed profit is hypothetical, not a buy signal.'
    return (decision, analysis, vision) if include_evidence else decision
