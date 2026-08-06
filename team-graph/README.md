# Team Workflow Graph Visualizer

Live visualization of agent team workflows, similar to n8n's node-based view.

## What It Shows

- **Nodes**: Agents (Planner, Developer, Reviewer), Tasks, Actions, Data
- **Edges**: Data flow between nodes
- **Live Updates**: Real-time status changes via WebSocket
- **Execution**: Watch the workflow execute step-by-step

## Quick Start

```bash
cd team-graph
pip install -r requirements.txt
python graph_server.py
```

Open http://127.0.0.1:5000 in your browser.

## Commands

- **Run Workflow** - Starts a simulated execution through the graph
- **Reset** - Resets all nodes to idle state

## Files

- `graph_engine.py` - Core graph data structures (nodes, edges, workflow)
- `graph_server.py` - Flask + SocketIO server
- `templates/graph.html` - Live visualization using vis.js

## Architecture

```
┌─────────────┐      WebSocket       ┌──────────────┐
│ graph_server │ ◄──────────────────► │  graph.html  │
│   (Flask)    │                      │  (vis.js)    │
└──────┬──────┘                      └──────────────┘
       │
       │ uses
       ▼
┌─────────────┐
│graph_engine │
│  (Python)   │
└─────────────┘
```
