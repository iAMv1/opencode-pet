import os

path = r'C:\Users\ItzP\projects\opencode-pet\team-graph\templates\graph.html'
os.makedirs(os.path.dirname(path), exist_ok=True)

lines = []
lines.append('<!DOCTYPE html>')
lines.append('<html>')
lines.append('<head>')
lines.append('<meta charset="UTF-8">')
lines.append('<title>Team Workflow Graph</title>')
lines.append('<script src="https://cdn.jsdelivr.net/npm/vis-network@9.1.6/dist/standalone/umd/vis-network.min.js"></script>')
lines.append('<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.4/socket.io.min.js"></script>')
