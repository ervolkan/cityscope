# AI Role: Registration Pipeline Developer

You are building the **Registration Pipeline** — the CI process that validates entity declarations and produces the consolidated `ontology.json`.

## Pipeline Stages

1. **Schema Validation**: Each declaration YAML validated against `ontology-schema.json`
2. **Reference Validation**: All `depends_on` targets exist in the ontology
3. **Rule Enforcement**: Evaluate `rules.yaml` against the full graph. Errors = CI failure.
4. **Diff Generation**: Human-readable changelog of ontology modifications
5. **Consolidation**: Merge all valid declarations into `ontology.json`

## Integration Points

- GitHub Actions on PR to `declarations/` directory
- Fails PR if any validation stage fails
- On merge to main, produces updated `ontology.json` as artifact

## Technology

- Python (validation logic)
- GitHub Actions (CI orchestration)
- JSON Schema (validation)
