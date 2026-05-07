"""
CityScope Bootstrap + Zoning Integration
==========================================
Runs the full pipeline:
  1. bootstrap_real.py → raw entities + edges (Pass 1: signal extraction)
  2. enrichment.py → graph enrichment (missing edges)
  3. engine.py → zoning rules (Pass 2: tier, domain, type, boundaries)
  4. Output → enriched ontology.json

Usage:
    python run_pipeline.py --infra ../infra/terraform --cd ../betcorewin-cd --output ontology.json
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from bootstrap_real import (
    parse_helm_values,
    parse_terraform,
    discover_implicit,
    normalize_entity_id,
)
from src.zoning.enrichment import enrich_graph
from src.zoning.engine import run_zoning, extract_signals


def run_pipeline(infra_path: str | None, cd_path: str | None, output_path: str):
    print("CityScope Full Pipeline: Bootstrap → Enrichment → Zoning")
    print("=" * 60)

    all_entities: dict[str, dict] = {}  # {id: entity_declaration}
    all_edges: list[dict] = []          # [{source, target, type, ...}]
    tf_contents: list[str] = []         # raw .tf file contents

    # ── Step 1: Bootstrap — raw entity extraction ──
    print("\n[1/4] Bootstrap: extracting entities from IaC...")

    # Terraform
    if infra_path:
        for tf_file in Path(infra_path).rglob("*.tf"):
            content = tf_file.read_text(encoding="utf-8", errors="replace")
            tf_contents.append(content)
            tf_entities = parse_terraform(content, tf_file.name)
            for entity in tf_entities:
                decl = entity.to_declaration()
                all_entities[entity.id] = decl
                print(f"  [TF] {entity.id} ({entity.entity_type})")

    # Helm values
    if cd_path:
        env_dir = Path(cd_path) / "environments" / "prod"
        if env_dir.exists():
            for vf in sorted(env_dir.glob("*-values.yaml")):
                entity = parse_helm_values(vf.name, vf.read_text(encoding="utf-8"))
                if entity:
                    decl = entity.to_declaration()
                    all_entities[entity.id] = decl

                    # Extract edges from depends_on
                    for dep in decl["spec"].get("depends_on", []):
                        all_edges.append({
                            "source": entity.id,
                            "target": dep.get("target", ""),
                            "type": dep.get("type", "sync"),
                            "protocol": dep.get("protocol", ""),
                            "critical": dep.get("critical", False),
                            "description": dep.get("description", ""),
                        })

                    print(f"  [HELM] {entity.id} (deps={len(entity.depends_on)})")

    # Implicit entities (from dependency targets not yet in entities)
    from bootstrap_real import Entity
    entity_objects = []
    for eid, e in all_entities.items():
        eo = Entity(
            id=eid,
            name=e["metadata"]["name"],
            entity_type=e["spec"]["type"],
            depends_on=e["spec"].get("depends_on", []),
        )
        entity_objects.append(eo)
    implicit = discover_implicit(entity_objects)
    for ie in implicit:
        all_entities[ie.id] = ie.to_declaration()

    print(f"\n  Bootstrap total: {len(all_entities)} entities, {len(all_edges)} edges")
    print(f"  (including {len(implicit)} implicit infrastructure entities)")

    # ── Step 2: Graph Enrichment — add missing edges ──
    print("\n[2/4] Graph Enrichment: discovering implicit edges...")

    before_edges = len(all_edges)
    all_entities, all_edges = enrich_graph(tf_contents, all_entities, all_edges)
    new_edges = len(all_edges) - before_edges

    print(f"  Added {new_edges} enrichment edges")
    # Summarize by type
    enrichment_types: dict[str, int] = {}
    for edge in all_edges:
        et = edge.get("_enrichment", "bootstrap")
        enrichment_types[et] = enrichment_types.get(et, 0) + 1
    for et, count in sorted(enrichment_types.items()):
        print(f"    {et}: {count} edges")

    # ── Step 3: Zoning — apply structural rules ──
    print("\n[3/4] Zoning Engine: applying structural classification rules...")

    # Transfer enrichment signals to entity metadata
    for eid, e in all_entities.items():
        esig = e.get("_enrichment_signals", {})
        if esig:
            if "receives_external_traffic" not in e.get("metadata", {}).get("labels", {}):
                if esig.get("receives_external_traffic"):
                    if "labels" not in e.get("metadata", {}):
                        e["metadata"]["labels"] = {}
                    e["metadata"]["labels"]["external_traffic"] = "true"

    all_entities = run_zoning(all_entities, all_edges)

    # Count changes
    tier_dist: dict[int, int] = {}
    domain_dist: dict[str, int] = {}
    type_dist: dict[str, int] = {}
    absorbed = 0

    for eid, e in all_entities.items():
        t = e["spec"]["tier"]
        d = e["metadata"]["domain"]
        tp = e["spec"]["type"]
        tier_dist[t] = tier_dist.get(t, 0) + 1
        domain_dist[d] = domain_dist.get(d, 0) + 1
        type_dist[tp] = type_dist.get(tp, 0) + 1

    print(f"\n  After zoning: {len(all_entities)} entities")
    print(f"  Tier distribution: { {f'T{k}': v for k, v in sorted(tier_dist.items())} }")
    print(f"  Type distribution: {dict(sorted(type_dist.items()))}")
    print(f"  Domain distribution: {dict(sorted(domain_dist.items()))}")

    # ── Step 4: Output ──
    print(f"\n[4/4] Writing output...")

    ontology = {
        "apiVersion": "cityscope.dev/v1",
        "kind": "Ontology",
        "metadata": {
            "name": "cityscope-ontology",
            "entity_count": len(all_entities),
            "generated_by": "run_pipeline.py",
            "pipeline": "bootstrap → enrichment → zoning",
        },
        "entities": {
            eid: e for eid, e in sorted(all_entities.items(), key=lambda x: (x[1]["spec"]["tier"], x[0]))
        },
    }

    out = Path(output_path)
    out.write_text(json.dumps(ontology, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Ontology written to: {out}")
    print(f"  Total entities: {len(all_entities)}")

    # Write individual declarations (without _signals for clean YAML)
    import yaml
    decl_dir = out.parent / "declarations_zoned"
    decl_dir.mkdir(exist_ok=True)
    for eid, e in all_entities.items():
        clean = {k: v for k, v in e.items() if not k.startswith("_")}
        (decl_dir / f"{eid}.yaml").write_text(
            yaml.dump(clean, default_flow_style=False, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    print(f"  Declarations written to: {decl_dir}/")

    print(f"\n{'='*60}")
    print("Pipeline complete.")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="CityScope Full Pipeline")
    p.add_argument("--infra", help="Path to Terraform directory")
    p.add_argument("--cd", help="Path to betcorewin-cd repo")
    p.add_argument("--output", "-o", default="ontology.json")
    args = p.parse_args()

    if not args.infra and not args.cd:
        print("Provide at least one of --infra or --cd")
        sys.exit(1)

    run_pipeline(args.infra, args.cd, args.output)
