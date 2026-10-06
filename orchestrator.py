"""Phase 2: The Multi-Agent Swarm, wired with LangGraph.
Analyst -> Vision -> Strategist, with ONE conditional loop-back:
if Analyst's confidence is low, Strategist can bounce it back for a re-read
with the vision findings as extra context, before deciding."""
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
def run_swarm(listing: Listing, resale_estimate: float, include_evidence: Literal[False] = False) -> StrategistDecision: ...


@overload
def run_swarm(
    listing: Listing, resale_estimate: float, include_evidence: Literal[True]
) -> tuple[StrategistDecision, ContextAnalysis, VisionCheck]: ...


def run_swarm(listing: Listing, resale_estimate: float, include_evidence: bool = False):
    app = build_graph()
    initial: SwarmState = {
        "listing": listing,
        "resale_estimate": resale_estimate,
        "analysis": None,
        "vision": None,
        "decision": None,
        "reanalysis_done": False,
    }
    final_state = app.invoke(initial)
    if include_evidence:
        return final_state["decision"], final_state["analysis"], final_state["vision"]
    return final_state["decision"]
