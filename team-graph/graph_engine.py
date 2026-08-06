"""Team Graph Engine - Models agents, tasks, and workflow execution.

Similar to n8n: nodes (agents), edges (data flow), and execution tracking.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class NodeType(Enum):
    AGENT = "agent"
    TASK = "task"
    ACTION = "action"
    DATA = "data"


class NodeStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    WAITING = "waiting"


@dataclass
class GraphNode:
    """A node in the workflow graph."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    type: NodeType = NodeType.AGENT
    status: NodeStatus = NodeStatus.IDLE
    data: Dict[str, Any] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    logs: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "status": self.status.value,
            "data": self.data,
            "x": self.x,
            "y": self.y,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "logs": self.logs[-10:],
            "duration": (self.finished_at - self.started_at) if self.started_at and self.finished_at else None
        }


@dataclass
class GraphEdge:
    """Connection between nodes."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source_id: str = ""
    target_id: str = ""
    label: str = ""
    active: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source_id,
            "target": self.target_id,
            "label": self.label,
            "active": self.active
        }


class WorkflowGraph:
    """Manages the entire workflow graph."""
    
    def __init__(self):
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: Dict[str, GraphEdge] = {}
        self.execution_log: List[Dict[str, Any]] = []
    
    def add_node(self, name: str, node_type: NodeType = NodeType.AGENT,
                 x: float = 0, y: float = 0, **data) -> GraphNode:
        node = GraphNode(name=name, type=node_type, x=x, y=y, data=data)
        self.nodes[node.id] = node
        return node
    
    def add_edge(self, source_id: str, target_id: str, label: str = "") -> GraphEdge:
        edge = GraphEdge(source_id=source_id, target_id=target_id, label=label)
        self.edges[edge.id] = edge
        return edge
    
    def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self.nodes.get(node_id)
    
    def update_node_status(self, node_id: str, status: NodeStatus, log_msg: str = ""):
        node = self.nodes.get(node_id)
        if not node:
            return
        node.status = status
        if status == NodeStatus.RUNNING:
            node.started_at = time.time()
        elif status in (NodeStatus.SUCCESS, NodeStatus.ERROR) and node.started_at:
            node.finished_at = time.time()
        if log_msg:
            node.logs.append(f"[{time.strftime('%H:%M:%S')}] {log_msg}")
    
    def activate_edge(self, edge_id: str, active: bool = True):
        edge = self.edges.get(edge_id)
        if edge:
            edge.active = active
    
    def export_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges.values()]
        }
    
    def reset(self):
        for node in self.nodes.values():
            node.status = NodeStatus.IDLE
            node.started_at = None
            node.finished_at = None
            node.logs = []
        for edge in self.edges.values():
            edge.active = False


def create_team_workflow() -> WorkflowGraph:
    """Create a sample team workflow graph."""
    graph = WorkflowGraph()
    
    planner = graph.add_node("Planner", NodeType.AGENT, x=100, y=200, role="planning")
    developer = graph.add_node("Developer", NodeType.AGENT, x=400, y=100, role="coding")
    reviewer = graph.add_node("Reviewer", NodeType.AGENT, x=400, y=300, role="review")
    
    analyze = graph.add_node("Analyze", NodeType.TASK, x=250, y=200)
    implement = graph.add_node("Implement", NodeType.TASK, x=600, y=200)
    test = graph.add_node("Test", NodeType.TASK, x=800, y=150)
    complete = graph.add_node("Complete", NodeType.ACTION, x=1000, y=200)
    
    requirements = graph.add_node("Requirements", NodeType.DATA, x=0, y=200)
    
    graph.add_edge(requirements.id, planner.id, "input")
    graph.add_edge(planner.id, analyze.id, "starts")
    graph.add_edge(analyze.id, developer.id, "ready")
    graph.add_edge(analyze.id, reviewer.id, "ready")
    graph.add_edge(developer.id, implement.id, "works on")
    graph.add_edge(implement.id, test.id, "input")
    graph.add_edge(test.id, reviewer.id, "needs review")
    graph.add_edge(test.id, complete.id, "passes")
    
    return graph
