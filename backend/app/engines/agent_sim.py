"""
Agent-Based Simulation Engine
------------------------------
Models individual actors making decisions under stress.

Agent types:
  RISK_AVERSE     — reroutes early at low stress thresholds; slow to commit
  RISK_SEEKING    — holds positions under stress; commits fast
  RULE_FOLLOWING  — follows escalation paths exactly; predictable
  CRISIS_MANAGER  — activates on multi-node failure; tries to restore connectivity
  OPPORTUNIST     — identifies reversion targets; moves toward them on failure

Each simulation step:
  1. Apply a stress event to one or more nodes
  2. Each agent observes its node's state
  3. Agent decides: HOLD | REROUTE | ESCALATE | ABSORB | EXPLOIT
  4. Network state updates based on decisions
  5. Repeat for N steps

Returns AgentSimResult with:
  - step-by-step narrative
  - final network state
  - which agents stabilised vs abandoned their positions
  - reversion opportunities identified
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import networkx as nx

from app.models.graph import Graph, NodeType


class AgentType(str, Enum):
    RISK_AVERSE = "risk_averse"
    RISK_SEEKING = "risk_seeking"
    RULE_FOLLOWING = "rule_following"
    CRISIS_MANAGER = "crisis_manager"
    OPPORTUNIST = "opportunist"


class AgentAction(str, Enum):
    HOLD = "hold"
    REROUTE = "reroute"
    ESCALATE = "escalate"
    ABSORB = "absorb"
    EXPLOIT = "exploit"
    ABANDON = "abandon"


@dataclass
class Agent:
    id: str
    name: str
    agent_type: AgentType
    node_id: str          # current position in the graph
    stress_tolerance: float   # 0-1, threshold before acting
    resources: float = 1.0    # 0-1, available capacity
    active: bool = True
    action_history: list[tuple[int, AgentAction, str]] = field(default_factory=list)

    def decide(self, node_stress: float, has_reroute: bool, step: int) -> AgentAction:
        """Choose an action based on agent type and current node stress."""
        if not self.active:
            return AgentAction.HOLD

        if self.agent_type == AgentType.RISK_AVERSE:
            if node_stress > self.stress_tolerance * 0.6:
                if has_reroute:
                    return AgentAction.REROUTE
                return AgentAction.ESCALATE
            return AgentAction.HOLD

        elif self.agent_type == AgentType.RISK_SEEKING:
            if node_stress > self.stress_tolerance:
                return AgentAction.ABSORB  # tries to absorb stress
            return AgentAction.HOLD

        elif self.agent_type == AgentType.RULE_FOLLOWING:
            if node_stress > self.stress_tolerance:
                return AgentAction.ESCALATE  # always escalates, never improvises
            return AgentAction.HOLD

        elif self.agent_type == AgentType.CRISIS_MANAGER:
            if node_stress > 0.7:
                if has_reroute:
                    return AgentAction.REROUTE
                return AgentAction.ESCALATE
            if node_stress > 0.4:
                return AgentAction.ABSORB
            return AgentAction.HOLD

        elif self.agent_type == AgentType.OPPORTUNIST:
            # Opportunist exploits disruption when stress is high elsewhere
            if node_stress < 0.3 and step > 2:
                return AgentAction.EXPLOIT  # move to gain from others' failure
            if node_stress > self.stress_tolerance:
                return AgentAction.REROUTE
            return AgentAction.HOLD

        return AgentAction.HOLD


@dataclass
class SimStep:
    step: int
    node_stresses: dict[str, float]     # node_id → stress level
    agent_actions: dict[str, AgentAction]   # agent_id → action
    events: list[str]
    failed_nodes: set[str] = field(default_factory=set)
    stabilised_nodes: set[str] = field(default_factory=set)


@dataclass
class AgentSimResult:
    n_steps: int
    simulation_type: str
    initial_stress_node: str
    agents: list[dict]
    steps: list[dict]       # serialisable step records
    final_failed_nodes: list[str]
    final_stabilised_nodes: list[str]
    reversion_opportunities: list[str]
    cascade_contained: bool
    narrative: str


def _node_stress(G: nx.DiGraph, node_id: str, base_stress: dict[str, float]) -> float:
    """Stress propagates from failed predecessors."""
    if node_id not in G:
        return 0.0
    s = base_stress.get(node_id, 0.0)
    # Add upstream stress (attenuated)
    for pred in G.predecessors(node_id):
        upstream = base_stress.get(pred, 0.0)
        edge_rel = G[pred][node_id].get("reliability", 1.0)
        s += upstream * (1 - edge_rel) * 0.3  # attenuation factor
    return min(1.0, s)


class AgentSimEngine:
    """Runs agent-based simulation on a graph."""

    def __init__(self, graph: Graph, seed: Optional[int] = None):
        self.graph = graph
        self.rng = random.Random(seed)
        self.G = self._build_nx()
        self._node_map = {n.id: n for n in graph.nodes}

    def _build_nx(self) -> nx.DiGraph:
        G = nx.DiGraph()
        for node in self.graph.nodes:
            G.add_node(node.id, label=node.label, node_type=node.node_type.value,
                       load=node.attributes.load, criticality=node.attributes.criticality)
        for edge in self.graph.edges:
            G.add_edge(edge.source, edge.target,
                       edge_type=edge.edge_type.value,
                       reliability=edge.attributes.reliability)
        return G

    def _default_agents(self) -> list[Agent]:
        """Generate one agent per person/team node, plus one crisis manager."""
        agents: list[Agent] = []
        persons = [n for n in self.graph.nodes
                   if n.node_type in (NodeType.PERSON, NodeType.TEAM)]
        for i, node in enumerate(persons[:8]):  # cap at 8 agents
            at = self.rng.choice(list(AgentType))
            agents.append(Agent(
                id=f"agent_{i}",
                name=node.label,
                agent_type=at,
                node_id=node.id,
                stress_tolerance=self.rng.uniform(0.4, 0.8),
            ))
        # Add crisis manager if not already one
        if not any(a.agent_type == AgentType.CRISIS_MANAGER for a in agents):
            critical = sorted(self.graph.nodes, key=lambda n: -n.attributes.criticality)
            if critical:
                agents.append(Agent(
                    id="agent_cm",
                    name="Crisis Manager",
                    agent_type=AgentType.CRISIS_MANAGER,
                    node_id=critical[0].id,
                    stress_tolerance=0.65,
                ))
        return agents

    def run(
        self,
        stress_node_id: str,
        n_steps: int = 8,
        initial_stress: float = 0.9,
        agents: Optional[list[Agent]] = None,
    ) -> AgentSimResult:
        if agents is None:
            agents = self._default_agents()

        node_stresses: dict[str, float] = {stress_node_id: initial_stress}
        failed_nodes: set[str] = set()
        stabilised_nodes: set[str] = set()
        step_records: list[dict] = []
        reversion_opps: list[str] = []

        # Identify reroute availability for each node
        reroute_cache: dict[str, bool] = {}
        for nid in self.G.nodes:
            preds = list(self.G.predecessors(nid))
            reroute_cache[nid] = len(preds) > 1

        for step in range(1, n_steps + 1):
            events: list[str] = []
            agent_actions: dict[str, AgentAction] = {}

            # Propagate stress
            new_stresses: dict[str, float] = {}
            for nid in self.G.nodes:
                s = _node_stress(self.G, nid, node_stresses)
                if s > 0.01:
                    new_stresses[nid] = s

            # Mark nodes as failed (stress > 0.85)
            for nid, s in new_stresses.items():
                if s > 0.85 and nid not in failed_nodes:
                    failed_nodes.add(nid)
                    label = self.G.nodes[nid].get("label", nid)
                    events.append(f"Step {step}: '{label}' failed (stress={s:.2f}).")

            # Agent decisions
            for agent in agents:
                if not agent.active:
                    continue
                nid = agent.node_id
                s = new_stresses.get(nid, 0.0)
                has_reroute = reroute_cache.get(nid, False) and nid not in failed_nodes
                action = agent.decide(s, has_reroute, step)
                agent_actions[agent.id] = action
                agent.action_history.append((step, action, nid))

                if action == AgentAction.REROUTE:
                    # Find a successor to reroute to
                    candidates = [n for n in self.G.successors(nid) if n not in failed_nodes]
                    if candidates:
                        new_node = self.rng.choice(candidates)
                        events.append(f"Step {step}: {agent.name} ({agent.agent_type.value}) rerouted from '{self.G.nodes[nid].get('label', nid)}' to '{self.G.nodes[new_node].get('label', new_node)}'.")
                        agent.node_id = new_node
                        stabilised_nodes.add(nid)
                    else:
                        events.append(f"Step {step}: {agent.name} attempted reroute but no path available.")

                elif action == AgentAction.ABSORB:
                    # Temporarily reduce stress at node
                    if nid in new_stresses:
                        new_stresses[nid] = max(0.0, new_stresses[nid] - 0.2)
                        events.append(f"Step {step}: {agent.name} absorbed stress at '{self.G.nodes[nid].get('label', nid)}' (reduced by 0.20).")
                        agent.resources -= 0.15

                elif action == AgentAction.ESCALATE:
                    label = self.G.nodes[nid].get("label", nid)
                    events.append(f"Step {step}: {agent.name} escalated from '{label}' — awaiting senior response.")

                elif action == AgentAction.EXPLOIT:
                    # Opportunist finds reversion target
                    targets = [n for n in nx.descendants(self.G, nid) if n not in failed_nodes]
                    if targets:
                        t = self.rng.choice(targets)
                        tl = self.G.nodes[t].get("label", t)
                        events.append(f"Step {step}: {agent.name} (opportunist) identified '{tl}' as reversion target.")
                        reversion_opps.append(tl)

                elif action == AgentAction.ABANDON:
                    agent.active = False
                    events.append(f"Step {step}: {agent.name} abandoned position.")

                # Deplete resources
                if agent.resources <= 0:
                    agent.active = False

            node_stresses = new_stresses

            step_records.append({
                "step": step,
                "node_stresses": {k: round(v, 3) for k, v in new_stresses.items()},
                "agent_actions": {k: v.value for k, v in agent_actions.items()},
                "failed_nodes": list(failed_nodes),
                "events": events,
            })

            # Early exit: cascade contained if stress is below threshold everywhere
            if all(s < 0.3 for s in new_stresses.values()):
                break

        # Build narrative
        stress_label = self.G.nodes.get(stress_node_id, {}).get("label", stress_node_id)
        cascade_contained = len(failed_nodes) <= 2 or any(
            a.agent_type == AgentType.CRISIS_MANAGER and a.active for a in agents
        )
        narrative_parts = [
            f"Agent simulation: stress event at '{stress_label}' (initial stress={initial_stress:.0%}).",
            f"{len(agents)} agents active across {len(self.G.nodes)} nodes.",
            f"After {len(step_records)} steps: {len(failed_nodes)} node(s) failed, {len(stabilised_nodes)} stabilised.",
        ]
        if reversion_opps:
            narrative_parts.append(f"Reversion opportunities identified: {', '.join(set(reversion_opps))}.")
        narrative_parts.append("Cascade contained." if cascade_contained else "Cascade not contained — system requires external intervention.")

        return AgentSimResult(
            n_steps=len(step_records),
            simulation_type="agent_based",
            initial_stress_node=stress_node_id,
            agents=[{
                "id": a.id, "name": a.name, "type": a.agent_type.value,
                "active": a.active, "resources": round(a.resources, 2),
                "final_node": a.node_id,
                "actions_taken": [(s, act.value, nid) for s, act, nid in a.action_history],
            } for a in agents],
            steps=step_records,
            final_failed_nodes=list(failed_nodes),
            final_stabilised_nodes=list(stabilised_nodes),
            reversion_opportunities=list(set(reversion_opps)),
            cascade_contained=cascade_contained,
            narrative=" ".join(narrative_parts),
        )
