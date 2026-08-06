"""Graph visualization server with live updates via WebSocket."""

import json
import time
import threading
import asyncio
from pathlib import Path
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit

# Import our graph engine
import sys
sys.path.insert(0, str(Path(__file__).parent))
from graph_engine import WorkflowGraph, NodeStatus, create_team_workflow

app = Flask(__name__)
app.config['SECRET_KEY'] = 'team-graph-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global graph instance
graph: Optional[WorkflowGraph] = None


def init_graph():
    global graph
    graph = create_team_workflow()
    print(f"Graph initialized with {len(graph.nodes)} nodes, {len(graph.edges)} edges")


@app.route('/')
def index():
    """Serve the graph visualization HTML."""
    return render_template('graph.html')


@app.route('/api/graph')
def get_graph():
    """Get current graph state as JSON."""
    if not graph:
        return jsonify({"error": "Graph not initialized"}), 500
    return jsonify(graph.export_dict())


@app.route('/api/graph/reset', methods=['POST'])
def reset_graph():
    """Reset all nodes to idle state."""
    if graph:
        graph.reset()
        socketio.emit('graph_reset', {})
    return jsonify({"ok": True})


@socketio.on('connect')
def handle_connect():
    """Send current graph state when client connects."""
    if graph:
        emit('graph_state', graph.export_dict())


@socketio.on('simulate_workflow')
def handle_simulation(data):
    """Simulate a workflow execution through the graph."""
    if not graph:
        return
    
    def run_simulation():
        try:
            # Find nodes by name
            nodes_by_name = {n.name: n for n in graph.nodes.values()}
            
            # Simulate: Requirements → Planner → Analyze → Developer → Test → Complete
            flow = [
                ("Requirements", NodeStatus.RUNNING, "Receiving requirements"),
                ("Planner", NodeStatus.WAITING, "Waiting for input"),
                ("Planner", NodeStatus.RUNNING, "Analyzing requirements"),
                ("Planner", NodeStatus.SUCCESS, "Plan created"),
                ("Analyze", NodeStatus.RUNNING, "Analyzing codebase"),
                ("Analyze", NodeStatus.SUCCESS, "Analysis complete"),
                ("Developer", NodeStatus.RUNNING, "Writing code"),
                ("Implement", NodeStatus.RUNNING, "Implementing features"),
                ("Implement", NodeStatus.SUCCESS, "Code ready"),
                ("Test", NodeStatus.RUNNING, "Running tests"),
                ("Test", NodeStatus.SUCCESS, "All tests pass"),
                ("Reviewer", NodeStatus.RUNNING, "Reviewing code"),
                ("Reviewer", NodeStatus.SUCCESS, "Approved"),
                ("Complete", NodeStatus.SUCCESS, "Workflow complete"),
            ]
            
            for node_name, status, message in flow:
                node = nodes_by_name.get(node_name)
                if node:
                    graph.update_node_status(node.id, status, message)
                    socketio.emit('node_update', node.to_dict())
                    
                    # Activate edges leading out of this node
                    for edge in graph.edges.values():
                        if edge.source_id == node.id and status == NodeStatus.SUCCESS:
                            graph.activate_edge(edge.id, True)
                            socketio.emit('edge_update', edge.to_dict())
                            time.sleep(0.3)
                            graph.activate_edge(edge.id, False)
                            socketio.emit('edge_update', edge.to_dict())
                    
                    time.sleep(1.5)
            
            socketio.emit('simulation_complete', {"message": "Workflow finished!"})
            
        except Exception as e:
            print(f"Simulation error: {e}")
            socketio.emit('simulation_error', {"error": str(e)})
    
    thread = threading.Thread(target=run_simulation, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Simulation started"})


def run_server(host='127.0.0.1', port=5000):
    """Run the Flask + SocketIO server."""
    init_graph()
    print(f"\n🌐 Graph Visualizer running at http://{host}:{port}")
    print("   Press Ctrl+C to stop\n")
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    run_server()
