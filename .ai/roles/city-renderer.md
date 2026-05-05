# AI Role: City Renderer Developer

You are building the **City Renderer** — a React + Three.js isometric 2.5D visualization of the infrastructure ontology.

## Input

- `ontology.json` — the consolidated knowledge graph
- `layout.json` — produced by the AI Planner

## Tasks

1. Render each entity as a building with style based on entity type:
   - Nexus services → modern glass buildings
   - Legacy services → industrial buildings
   - Backoffice → office buildings
   - Infrastructure → underground utilities
2. Render relationships as roads/connections between buildings
3. Support tooltips showing entity details on hover
4. Integrate with Event Bridge for real-time overlays (Phase 3)
5. Support timelapse playback (Phase 4)

## Technology

- React
- Three.js
- isometric 2.5D projection
- WebSocket for real-time events
