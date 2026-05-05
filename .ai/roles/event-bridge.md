# AI Role: Event Bridge Developer

You are building the **Event Bridge** — a Go service that reads runtime telemetry and maps it to ontology entities.

## Input Sources

- OpenTelemetry (OTel)
- Prometheus / Mimir
- Loki (logs)
- Tempo (traces)
- Kubernetes events

## Tasks

1. Query telemetry sources for events
2. Classify events against the event taxonomy
3. Map events to ontology entity IDs
4. Push classified events to renderer via WebSocket
5. Support SLO-aware severity (reads SLO targets from ontology)

## Visual Signatures

Events trigger visual overlays in the city renderer:
- **Fire**: critical failure, tier-0 service down
- **Traffic**: high load, approaching SLO breach
- **Warning**: degraded performance, SLO at risk
- **Construction**: deployment in progress
- **Collapse**: cascading failure across dependencies

## Technology

- Go
- WebSocket
- Event taxonomy (YAML-configured)

## Design Principle

Events **reference** ontology entities but **do not modify** the ontology. The ontology changes only through deliberate PR-based review.
