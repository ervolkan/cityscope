"""
CityScope Real Bootstrap Pipeline
==================================
Reads BetCoreWin/infra (Terraform) and BetCoreWin/betcorewin-cd (Helm values)
via GitHub API and generates a real ontology.json from actual IaC sources.

Usage (GitHub mode - no local clone needed):
    python bootstrap_real.py --github --output ontology.json

Usage (local clones):
    python bootstrap_real.py --local-infra ../infra --local-cd ../betcorewin-cd --output ontology.json

Requirements: pip install pyyaml requests
"""

import json
import re
import sys
import base64
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field

import yaml

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    id: str
    name: str
    entity_type: str
    tier: int = 2
    domain: str = ""
    team: str = ""
    description: str = ""
    lifecycle: str = "active"
    protocols: list = field(default_factory=list)
    depends_on: list = field(default_factory=list)
    scaling: dict = field(default_factory=dict)
    slo: dict = field(default_factory=dict)
    image: str = ""
    source_file: str = ""
    labels: dict = field(default_factory=dict)

    def to_declaration(self) -> dict:
        decl = {
            "apiVersion": "cityscope.dev/v1",
            "kind": "Entity",
            "metadata": {
                "id": self.id,
                "name": self.name,
                "domain": self.domain,
                "team": self.team,
                "description": self.description,
            },
            "spec": {
                "type": self.entity_type,
                "tier": self.tier,
                "lifecycle": self.lifecycle,
                "protocols": self.protocols,
                "depends_on": self.depends_on,
            },
        }
        if self.image:
            decl["spec"]["image"] = self.image
        if self.scaling:
            decl["spec"]["scaling"] = self.scaling
        if self.slo:
            decl["spec"]["slo"] = self.slo
        if self.labels:
            decl["metadata"]["labels"] = self.labels
        return decl


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

DOMAIN_RULES = [
    (r"(customer|payment|wallet|bonus|store|betting|odds)", "nexus-core"),
    (r"(ai-|recommender|ml-|inference)", "nexus-ai"),
    (r"(grafana|prometheus|loki|tempo|otel|alloy|alertmanager|pyroscope|monitoring)", "nexus-observability"),
    (r"(compliance|audit|kyc|fraud|risk)", "nexus-compliance"),
    (r"(alb|cloudflare|ingress|gateway|proxy|cdn|loadbalancer)", "nexus-gateway"),
    (r"(^bo-|backoffice|management|admin|dashboard|cms|hr|support|parameter)", "nexus-backoffice"),
    (r"(casino-bridge|thirdparty|bridge|provider)", "nexus-integration"),
    (r"(vpc|subnet|eks|docdb|s3-|redis|rabbitmq|mssql|postgres|backup|nat|igw|sg-|security)", "nexus-infra"),
    (r"(betticket|betdata|betflow|betcashout|betrisk|streamnet|sportsbook|ticket)", "nexus-core"),
    (r"(identity|ids|auth|session)", "nexus-core"),
    (r"(datahub|datasource|localization|log)", "nexus-core"),
    (r"^nexus-", "nexus-core"),
]

TIER_RULES = [
    (r"(identity|customer|wallet|payment|betticket|streamnet|betdata|casino$)", 0),
    (r"(bonus|betting|odds|compliance|fraud|risk|notification|betcashout|betflow|betrisk)", 1),
    (r"(prod-eks|prod-vpc|prod-alb|docdb|rabbitmq)", 1),
    (r"(admin|dashboard|reporting|backoffice|bo-|management|settings|operator|docs|localization|log)", 2),
    (r"(s3-|backup|monitoring|grafana|loki|tempo|prometheus|otel)", 2),
    (r"(n8n|test|fixture|sample)", 3),
]

TEAM_RULES = [
    (r"(nexus-|^nexus)", "nexus-backend"),
    (r"(^bo-|management)", "nexus-backoffice"),
    (r"(^srv-|betticket|betdata|streamnet|betflow|betcashout|betrisk|casino-service|branch-grpc|customer-grpc|parameters-grpc|datasource)", "wincore-backend"),
    (r"(identity|ids)", "wincore-identity"),
    (r"(grafana|loki|tempo|prometheus|otel|alloy|monitoring)", "platform-sre"),
    (r"(vpc|eks|alb|cloudflare|s3|subnet|docdb|backup)", "platform-infra"),
    (r"(sd-log)", "wincore-backend"),
]


def classify_domain(eid: str) -> str:
    for p, d in DOMAIN_RULES:
        if re.search(p, eid, re.I): return d
    return "nexus-core"

def classify_tier(eid: str) -> int:
    for p, t in TIER_RULES:
        if re.search(p, eid, re.I): return t
    return 2

def classify_team(eid: str) -> str:
    for p, t in TEAM_RULES:
        if re.search(p, eid, re.I): return t
    return "platform"


# ---------------------------------------------------------------------------
# Helm Values Parser
# ---------------------------------------------------------------------------

def normalize_entity_id(raw: str) -> str:
    name = re.sub(r"^prod-", "", raw)
    name = re.sub(r"-values$", "", name)
    name = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
    return re.sub(r"-+", "-", name)


def parse_dotnet_cs(cs: str) -> dict:
    result = {}
    for part in cs.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip().lower()] = v.strip()
    return result


def extract_host(value: str) -> Optional[str]:
    m = re.search(r"mongodb://[^@]+@([^:/]+)", value)
    if m: return m.group(1)
    m = re.search(r"https?://([^:/]+)", value)
    if m:
        h = m.group(1)
        if not ("." in h and any(c.isalpha() for c in h.split(".")[-1]) and len(h.split(".")[-1]) > 2):
            return h
        return None
    p = parse_dotnet_cs(value)
    return p.get("host") or p.get("server")


def _is_ip(h: str) -> bool:
    return bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", h))

def _ip_to_id(ip: str) -> str:
    return ip.replace(".", "-")

def _proto(port: int, name: str) -> str:
    nl = name.lower()
    if "grpc" in nl: return "grpc"
    if "orleans" in nl: return "orleans"
    if port in (80, 8080) or "http" in nl or "api" in nl: return "http"
    if port == 443: return "https"
    if port == 8181: return "grpc"
    return "tcp"


def parse_helm_values(filename: str, content: str) -> Optional[Entity]:
    try:
        values = yaml.safe_load(content)
    except Exception:
        return None
    if not values or not isinstance(values, dict):
        return None

    no = values.get("nameOverride", "")
    eid = normalize_entity_id(no) if no else normalize_entity_id(filename.replace("-values.yaml", ""))
    if not eid or len(eid) < 3: return None

    # Image
    ic = values.get("image", {})
    image = ""
    if isinstance(ic, dict):
        reg = ic.get("registry", "")
        repo = ic.get("repository", "")
        tag = ic.get("tag", "latest")
        image = f"{reg}/{repo}:{tag}" if reg and repo else (f"{repo}:{tag}" if repo else "")

    # Protocols
    protocols = []
    for p in (values.get("ports") or []):
        if isinstance(p, dict):
            port = p.get("containerPort") or p.get("port")
            name = p.get("name", "")
            if port:
                protocols.append({"name": _proto(port, name), "port": port, "description": name or f"port {port}"})

    # Dependencies
    deps = []
    seen = set()
    env = values.get("env", {})
    if isinstance(env, dict):
        for vn, vv in env.items():
            vv = str(vv)
            vnl = vn.lower()

            # gRPC/HTTP hosts
            if ("grpchost" in vnl or "servicehost" in vnl) or ("host" in vnl and ("grpc" in vnl or "service" in vnl)):
                h = extract_host(vv)
                if h and not _is_ip(h):
                    t = normalize_entity_id(h)
                    if t and t not in seen and t != eid:
                        seen.add(t)
                        deps.append({"target": t, "type": "sync", "protocol": "grpc" if "grpc" in vnl else "http", "critical": False, "description": f"from {vn}"})

            # MongoDB/DocumentDB
            if "mongodb://" in vv or "documentdb" in vv.lower():
                h = extract_host(vv)
                if h and h not in seen:
                    tid = "prod-docdb" if "docdb" in h else normalize_entity_id(h)
                    seen.add(h)
                    deps.append({"target": tid, "type": "storage", "protocol": "mongodb", "critical": True, "description": f"DocumentDB via {vn}"})

            # MSSQL
            if ("connectionstring" in vnl or "sqlconnection" in vnl) and "server=" in vv.lower():
                p = parse_dotnet_cs(vv)
                h = p.get("server") or p.get("host")
                db = p.get("database", "")
                if h and h not in seen:
                    seen.add(h)
                    tid = f"mssql-{_ip_to_id(h)}" if _is_ip(h) else normalize_entity_id(h)
                    deps.append({"target": tid, "type": "storage", "protocol": "mssql", "critical": True, "description": f"MSSQL '{db}' via {vn}"})

            # PostgreSQL
            if "connectionstring" in vnl and "host=" in vv.lower() and "port=5432" in vv.lower():
                p = parse_dotnet_cs(vv)
                h = p.get("host")
                db = p.get("database", "")
                if h and h not in seen:
                    seen.add(h)
                    tid = f"postgres-{_ip_to_id(h)}" if _is_ip(h) else normalize_entity_id(h)
                    deps.append({"target": tid, "type": "storage", "protocol": "postgres", "critical": True, "description": f"PostgreSQL '{db}' via {vn}"})

            # RabbitMQ
            if "rabbitmq" in vnl and "hostname" in vnl:
                if "rabbitmq" not in seen:
                    seen.add("rabbitmq")
                    tid = f"rabbitmq-{_ip_to_id(vv)}" if _is_ip(vv) else normalize_entity_id(vv)
                    deps.append({"target": tid, "type": "async", "protocol": "amqp", "critical": False, "description": f"RabbitMQ via {vn}"})

            # OTel
            if "otel" in vnl and "endpoint" in vnl:
                h = extract_host(vv)
                if h and "otel" not in seen:
                    seen.add("otel")
                    deps.append({"target": normalize_entity_id(h), "type": "infra", "protocol": "grpc", "critical": False, "description": "OTel collector"})

    # initContainers
    for ic in (values.get("initContainers") or []):
        if isinstance(ic, dict) and ic.get("host"):
            t = normalize_entity_id(ic["host"])
            if t and t not in seen:
                seen.add(t)
                deps.append({"target": t, "type": "sync", "protocol": "http", "critical": True, "description": f"initContainer: {ic['host']}"})

    # Scaling
    scaling = {}
    r = values.get("replicaCount")
    if r is not None: scaling["current_replicas"] = int(r)
    a = values.get("autoscaling", {})
    if isinstance(a, dict) and a.get("enabled"):
        scaling.update({"min_replicas": a.get("minReplicas", 1), "max_replicas": a.get("maxReplicas", 5), "strategy": "hpa"})

    labels = {}
    if values.get("orleans", {}).get("enabled"):
        labels["orleans"] = "true"

    # Service type and NodePort extraction (for ALB edge matching)
    svc = values.get("service", {})
    if isinstance(svc, dict):
        svc_type = svc.get("type", "ClusterIP")
        if svc_type:
            labels["service_type"] = svc_type
        svc_ports = svc.get("ports", [])
        if isinstance(svc_ports, list):
            for sp in svc_ports:
                if isinstance(sp, dict) and sp.get("nodePort"):
                    try:
                        labels["nodePort"] = str(int(sp["nodePort"]))
                    except (ValueError, TypeError):
                        pass

    return Entity(
        id=eid, name=(no or eid).replace("-", " ").title(),
        entity_type="service", tier=classify_tier(eid),
        domain=classify_domain(eid), team=classify_team(eid),
        description=f"Auto-bootstrapped from {filename}",
        protocols=protocols, depends_on=deps, scaling=scaling,
        image=image, source_file=filename, labels=labels,
    )


# ---------------------------------------------------------------------------
# Terraform Parser
# ---------------------------------------------------------------------------

def parse_terraform(content: str, filename: str) -> list[Entity]:
    entities = []

    # VPC modules
    for m in re.finditer(r'module\s+"([^"]*vpc[^"]*)"\s*\{', content):
        mn = m.group(1)
        eid = normalize_entity_id(mn)
        block = _extract_block(content, m.end())
        cidr = ""
        cm = re.search(r'cidr\s*=\s*(?:local\.)?(\S+)', block)
        if cm:
            lv = _resolve_local(content, cm.group(1))
            cidr = f" ({lv})" if lv else ""
        entities.append(Entity(id=eid, name=f"VPC {mn}", entity_type="network", tier=classify_tier(eid), domain="nexus-infra", team="platform-infra", description=f"VPC{cidr}", source_file=filename))

    # EKS
    for m in re.finditer(r'module\s+"([^"]*eks[^"]*)"\s*\{', content):
        mn = m.group(1)
        eid = normalize_entity_id(mn)
        block = _extract_block(content, m.end())
        vm = re.search(r'cluster_version\s*=\s*"([^"]+)"', block)
        ver = vm.group(1) if vm else "?"
        ngb = re.search(r'eks_managed_node_groups\s*=\s*\{(.+?)\n\s{2}\}', block, re.DOTALL)
        if ngb:
            for ng in re.finditer(r'(\w+)\s*=\s*\{', ngb.group(1)):
                nn = ng.group(1)
                nid = normalize_entity_id(nn)
                nb = _extract_block(ngb.group(1), ng.end())
                role_m = re.search(r'role\s*=\s*"([^"]+)"', nb)
                role = role_m.group(1) if role_m else "worker"
                it_m = re.search(r'instance_types\s*=\s*\["([^"]+)"\]', nb)
                it = it_m.group(1) if it_m else ""
                entities.append(Entity(
                    id=nid, name=f"EKS Node Group: {nn}", entity_type="compute",
                    tier=1 if role == "worker" else 2, domain="nexus-infra", team="platform-infra",
                    description=f"EKS NG ({it}, role={role})",
                    scaling={"min_replicas": _eint(nb, "min_size") or 1, "max_replicas": _eint(nb, "max_size") or 1, "current_replicas": _eint(nb, "desired_size") or 1, "strategy": "static"},
                    depends_on=[{"target": eid, "type": "infra", "description": "EKS cluster"}],
                    labels={"role": role, "instance_type": it}, source_file=filename,
                ))
        entities.append(Entity(id=eid, name=f"EKS Cluster {mn}", entity_type="compute", tier=1, domain="nexus-infra", team="platform-infra", description=f"EKS v{ver}", source_file=filename))

    # ALB
    for m in re.finditer(r'module\s+"([^"]*alb[^"]*)"\s*\{', content):
        mn = m.group(1)
        eid = normalize_entity_id(mn)
        entities.append(Entity(id=eid, name=f"ALB {mn}", entity_type="gateway", tier=1, domain="nexus-gateway", team="platform-infra", description="Application Load Balancer", source_file=filename))

    # DocumentDB
    for m in re.finditer(r'resource\s+"aws_docdb_cluster"\s+"([^"]+)"', content):
        rn = m.group(1)
        block = _extract_block(content, m.end())
        cid_m = re.search(r'cluster_identifier\s*=\s*"([^"]+)"', block)
        cid = cid_m.group(1) if cid_m else rn
        eid = normalize_entity_id(rn) if normalize_entity_id(rn) != "prod" else "prod-docdb"
        entities.append(Entity(id=eid, name=f"DocumentDB {cid}", entity_type="datastore", tier=1, domain="nexus-infra", team="platform-infra", description=f"DocumentDB '{cid}'", protocols=[{"name": "mongodb", "port": 27017, "description": "MongoDB wire protocol"}], source_file=filename))

    # S3
    for m in re.finditer(r'module\s+"([^"]*(?:s3|content|sport-asset)[^"]*)"\s*\{', content):
        mn = m.group(1)
        eid = normalize_entity_id(mn)
        block = _extract_block(content, m.end())
        bm = re.search(r'bucket_name\s*=\s*"([^"]+)"', block)
        bucket = bm.group(1) if bm else mn
        entities.append(Entity(id=eid, name=f"S3 {bucket}", entity_type="storage", tier=2, domain="nexus-infra", team="platform-infra", description=f"S3 '{bucket}'", source_file=filename))

    # Cloudflare records
    for m in re.finditer(r'resource\s+"cloudflare_record"\s+"([^"]+)"', content):
        rn = m.group(1)
        eid = f"cf-{normalize_entity_id(rn)}"
        block = _extract_block(content, m.end())
        nm = re.search(r'name\s*=\s*"([^"]+)"', block)
        dn = nm.group(1) if nm else rn
        entities.append(Entity(id=eid, name=f"Cloudflare {dn}", entity_type="gateway", tier=2, domain="nexus-gateway", team="platform-infra", description=f"DNS record: {dn}", source_file=filename))

    # Security groups
    for m in re.finditer(r'module\s+"([^"]*sec_rule[^"]*)"\s*\{', content):
        mn = m.group(1)
        eid = normalize_entity_id(mn)
        entities.append(Entity(id=eid, name=f"SG {mn}", entity_type="network", tier=2, domain="nexus-infra", team="platform-infra", description=f"Security group: {mn}", source_file=filename))

    # VPC resources
    for m in re.finditer(r'resource\s+"aws_vpc"\s+"([^"]+)"', content):
        rn = m.group(1)
        eid = normalize_entity_id(rn)
        block = _extract_block(content, m.end())
        cm = re.search(r'cidr_block\s*=\s*"([^"]+)"', block)
        cidr = cm.group(1) if cm else ""
        entities.append(Entity(id=eid, name=f"VPC {rn}", entity_type="network", tier=2, domain="nexus-infra", team="platform-infra", description=f"VPC {cidr}", source_file=filename))

    return entities


def _extract_block(content: str, start: int) -> str:
    idx = content.find("{", start)
    if idx == -1: return ""
    depth, i = 1, idx + 1
    while i < len(content) and depth > 0:
        if content[i] == "{": depth += 1
        elif content[i] == "}": depth -= 1
        i += 1
    return content[idx:i]

def _resolve_local(content: str, ref: str) -> Optional[str]:
    if not ref.startswith("local."): return ref.strip('"')
    m = re.search(rf'{ref.replace("local.", "")}\s*=\s*"([^"]+)"', content)
    return m.group(1) if m else None

def _eint(block: str, key: str) -> Optional[int]:
    m = re.search(rf'{key}\s*=\s*(\d+)', block)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Implicit entity discovery
# ---------------------------------------------------------------------------

def discover_implicit(entities: list[Entity]) -> list[Entity]:
    known = {e.id for e in entities}
    implicit = {}
    for e in entities:
        for d in e.depends_on:
            t = d.get("target", "")
            if not t or t in known or t in implicit: continue
            proto = d.get("protocol", "")
            if "mssql" in t or proto == "mssql":
                et, ti, do = "datastore", 1, "nexus-infra"
                nm, desc = f"MSSQL {t}", "MSSQL server (implicit)"
            elif "postgres" in t or proto == "postgres":
                et, ti, do = "datastore", 1, "nexus-infra"
                nm, desc = f"PostgreSQL {t}", "PostgreSQL server (implicit)"
            elif "docdb" in t or proto == "mongodb":
                et, ti, do = "datastore", 1, "nexus-infra"
                nm, desc = f"DocumentDB {t}", "DocumentDB (implicit)"
            elif "rabbitmq" in t or proto == "amqp":
                et, ti, do = "messagebus", 1, "nexus-infra"
                nm, desc = f"RabbitMQ {t}", "RabbitMQ (implicit)"
            elif "redis" in t or proto == "redis":
                et, ti, do = "cache", 2, "nexus-infra"
                nm, desc = f"Redis {t}", "Redis (implicit)"
            elif "otel" in t or "collector" in t:
                et, ti, do = "service", 2, "nexus-observability"
                nm, desc = f"OTel Collector", "OTel collector (implicit)"
            else:
                et, ti, do = "service", classify_tier(t), classify_domain(t)
                nm, desc = t.replace("-", " ").title(), "Service (implicit)"
            implicit[t] = Entity(id=t, name=nm, entity_type=et, tier=ti, domain=do, team=classify_team(t), description=desc)
    return list(implicit.values())


# ---------------------------------------------------------------------------
# GitHub API mode
# ---------------------------------------------------------------------------

def fetch_github_files(owner: str, repo: str, path: str, token: str = "") -> list[dict]:
    """List files in a GitHub directory."""
    import requests
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token: headers["Authorization"] = f"token {token}"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()


def fetch_github_file(owner: str, repo: str, path: str, token: str = "") -> str:
    """Fetch file content from GitHub."""
    import requests
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token: headers["Authorization"] = f"token {token}"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    data = r.json()
    return base64.b64decode(data["content"]).decode("utf-8")


def run_github(token: str, output_path: str):
    """Run bootstrap from GitHub API."""
    all_entities: list[Entity] = []

    # 1. Fetch Terraform
    print("\n[1/3] Fetching Terraform from BetCoreWin/infra...")
    try:
        tf_files = fetch_github_files("BetCoreWin", "infra", "terraform", token)
        for f in tf_files:
            if f["type"] == "file" and f["name"].endswith(".tf"):
                content = fetch_github_file("BetCoreWin", "infra", f["path"], token)
                tf_ents = parse_terraform(content, f["name"])
                all_entities.extend(tf_ents)
                if tf_ents:
                    print(f"  [TF] {f['name']}: {len(tf_ents)} entities")
    except Exception as e:
        print(f"  [WARN] Terraform fetch failed: {e}")

    # 2. Fetch Helm values
    print("\n[2/3] Fetching Helm values from BetCoreWin/betcorewin-cd...")
    try:
        files = fetch_github_files("BetCoreWin", "betcorewin-cd", "environments/prod", token)
        for f in sorted(files, key=lambda x: x["name"]):
            if f["name"].endswith("-values.yaml"):
                content = fetch_github_file("BetCoreWin", "betcorewin-cd", f["path"], token)
                entity = parse_helm_values(f["name"], content)
                if entity:
                    all_entities.append(entity)
                    print(f"  [HELM] {f['name']}: {entity.id} (type={entity.entity_type}, tier={entity.tier}, deps={len(entity.depends_on)})")
    except Exception as e:
        print(f"  [WARN] Helm fetch failed: {e}")

    # 3. Implicit entities
    print("\n[3/3] Discovering implicit infrastructure entities...")
    implicit = discover_implicit(all_entities)
    all_entities.extend(implicit)
    print(f"  Found {len(implicit)} implicit entities")

    # Deduplicate & build
    by_id: dict[str, Entity] = {}
    for e in all_entities:
        if e.id in by_id:
            old = by_id[e.id]
            if len(e.depends_on) + len(e.protocols) > len(old.depends_on) + len(old.protocols):
                by_id[e.id] = e
        else:
            by_id[e.id] = e
    final = list(by_id.values())

    ontology = {
        "apiVersion": "cityscope.dev/v1",
        "kind": "Ontology",
        "metadata": {"name": "cityscope-ontology", "entity_count": len(final), "generated_by": "bootstrap_real.py", "source_repos": ["BetCoreWin/infra", "BetCoreWin/betcorewin-cd"]},
        "entities": {e.id: e.to_declaration() for e in sorted(final, key=lambda x: (x.tier, x.entity_type, x.id))},
    }

    out = Path(output_path)
    out.write_text(json.dumps(ontology, indent=2, ensure_ascii=False), encoding="utf-8")

    # Also write declarations
    decl_dir = out.parent / "declarations_real"
    decl_dir.mkdir(exist_ok=True)
    for e in final:
        (decl_dir / f"{e.id}.yaml").write_text(yaml.dump(e.to_declaration(), default_flow_style=False, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # Summary
    by_type, by_tier = {}, {}
    for e in final:
        by_type[e.entity_type] = by_type.get(e.entity_type, 0) + 1
        by_tier[e.tier] = by_tier.get(e.tier, 0) + 1

    print(f"\n{'='*50}")
    print(f"Ontology written to: {out}")
    print(f"Declarations written to: {decl_dir}/")
    print(f"Total entities: {len(final)}")
    print(f"\nBy type: {json.dumps(by_type, indent=2)}")
    print(f"\nBy tier: {json.dumps({f'Tier {k}': v for k, v in sorted(by_tier.items())})}")


# ---------------------------------------------------------------------------
# Local mode
# ---------------------------------------------------------------------------

def run_local(infra_path: Optional[str], cd_path: Optional[str], output_path: str):
    all_entities: list[Entity] = []

    if infra_path:
        print("\n[1/3] Parsing Terraform...")
        for tf in Path(infra_path).rglob("*.tf"):
            content = tf.read_text(encoding="utf-8", errors="replace")
            ents = parse_terraform(content, tf.name)
            all_entities.extend(ents)
            if ents: print(f"  [TF] {tf.name}: {len(ents)} entities")

    if cd_path:
        print("\n[2/3] Parsing Helm values...")
        env_dir = Path(cd_path) / "environments" / "prod"
        if env_dir.exists():
            for vf in sorted(env_dir.glob("*-values.yaml")):
                e = parse_helm_values(vf.name, vf.read_text(encoding="utf-8"))
                if e:
                    all_entities.append(e)
                    print(f"  [HELM] {vf.name}: {e.id} (type={e.entity_type}, tier={e.tier}, deps={len(e.depends_on)})")

    print("\n[3/3] Discovering implicit entities...")
    implicit = discover_implicit(all_entities)
    all_entities.extend(implicit)
    print(f"  Found {len(implicit)} implicit entities")

    by_id: dict[str, Entity] = {}
    for e in all_entities:
        if e.id not in by_id or len(e.depends_on) > len(by_id[e.id].depends_on):
            by_id[e.id] = e
    final = list(by_id.values())

    ontology = {
        "apiVersion": "cityscope.dev/v1", "kind": "Ontology",
        "metadata": {"name": "cityscope-ontology", "entity_count": len(final), "generated_by": "bootstrap_real.py"},
        "entities": {e.id: e.to_declaration() for e in sorted(final, key=lambda x: (x.tier, x.entity_type, x.id))},
    }

    out = Path(output_path)
    out.write_text(json.dumps(ontology, indent=2, ensure_ascii=False), encoding="utf-8")

    decl_dir = out.parent / "declarations_real"
    decl_dir.mkdir(exist_ok=True)
    for e in final:
        (decl_dir / f"{e.id}.yaml").write_text(yaml.dump(e.to_declaration(), default_flow_style=False, sort_keys=False, allow_unicode=True), encoding="utf-8")

    by_type, by_tier = {}, {}
    for e in final:
        by_type[e.entity_type] = by_type.get(e.entity_type, 0) + 1
        by_tier[e.tier] = by_tier.get(e.tier, 0) + 1

    print(f"\n{'='*50}")
    print(f"Ontology: {out} | Declarations: {decl_dir}/")
    print(f"Total: {len(final)} entities")
    print(f"By type: {by_type}")
    print(f"By tier: {{k: v for k, v in sorted(by_tier.items())}}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="CityScope Real Bootstrap")
    p.add_argument("--github", action="store_true", help="Fetch from GitHub API")
    p.add_argument("--github-token", default="", help="GitHub PAT (optional for public repos)")
    p.add_argument("--local-infra", help="Local BetCoreWin/infra path")
    p.add_argument("--local-cd", help="Local BetCoreWin/betcorewin-cd path")
    p.add_argument("--output", "-o", default="ontology_real.json")
    args = p.parse_args()

    print("CityScope Real Bootstrap Pipeline")
    print("=" * 50)

    if args.github:
        run_github(args.github_token, args.output)
    elif args.local_infra or args.local_cd:
        run_local(args.local_infra, args.local_cd, args.output)
    else:
        print("Usage: --github OR --local-infra/--local-cd")
        sys.exit(1)
