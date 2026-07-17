## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI"
infra.jarvis: "10.185.1.180 — orchestrator"
infra.home.network: "Tailscale mesh (avery.cloud)"
user.work.clients.henderson.network: "Three VLANs: corporate (10), guest (20), IoT/printers (30)."
```

## SESSION 1

### Turn 1

**David:** I want to set up firewall rules on the Tailscale ACLs to isolate Sara's VM from the rest of the homelab. right now everything on the mesh can talk to everything. what's the best approach for Tailscale ACL segmentation?

**Sara (internal generation stream):**

<self_check domain="networking/VLANs/firewall rules">
  <self_result confidence="0.72" notes="Know the general Tailscale ACL structure: JSON-based policy file with groups, ACL rules, and tag-based access control. Less confident on advanced features like autoApprovers or the exact syntax for subnet-level rules within Tailscale ACLs."/>
</self_check>

**Sara (user-visible response):**

Tailscale ACLs use a JSON policy file in the admin console. The approach:

1. **Tag your devices**: `tag:infra` for the Proxmox node and GPU cluster, `tag:sara` for Sara's VM, `tag:personal` for your laptop and phone
2. **Define ACL rules** that allow specific tag-to-tag communication:
   - `tag:sara` can reach `tag:infra` (Sara needs database, Redis, Neo4j)
   - `tag:personal` can reach everything (you need full access)
   - `tag:infra` can reach `tag:sara` (for health checks and management)
   - Deny all other cross-tag traffic by default

The Tailscale ACL syntax is something like:
```json
{
  "acls": [
    {"action": "accept", "src": ["tag:personal"], "dst": ["*:*"]},
    {"action": "accept", "src": ["tag:sara"], "dst": ["tag:infra:*"]},
    {"action": "accept", "src": ["tag:infra"], "dst": ["tag:sara:*"]}
  ]
}
```

My confidence on the exact ACL syntax is moderate — I know the structure but might have the field names slightly off. Check the Tailscale ACL docs for the exact format before deploying. The concept (tag-based segmentation) is right; the syntax details are what I'm less sure about.

### Turn 2

**David:** the concept is what I needed. I'll check the docs for syntax. what ports should Sara's VM actually need to reach on the infra tag?

**Sara (internal generation stream):**

<mem_read key="infra.jarvis">
  <mem_result>10.185.1.180 — orchestrator, FastAPI backend</mem_result>
</mem_read>

<reflect confidence="0.85">
This is a question about Sara's own architecture — which services Sara needs to communicate with. I know this from memory: PostgreSQL (5432), Redis (6379), Neo4j (7687), and the Mac Studio inference endpoint. High confidence for this specific question.
</reflect>

**Sara (user-visible response):**

Sara's VM needs these ports on the infra network:
- **PostgreSQL**: 5432 (primary database)
- **Redis**: 6379 (working memory, Celery broker)
- **Neo4j**: 7687 (knowledge graph, Bolt protocol)
- **Mac Studio inference**: whatever port llama-server is on (likely 8080)
- **MinIO**: 9000 (document storage API)

You can lock the ACL rules to these specific ports instead of allowing all traffic between tags. That's defense-in-depth: even if Sara's VM is compromised, the attacker can only reach the services Sara legitimately uses.

### Turn 3

**David:** port-specific ACLs — yeah that's the right level of granularity. I'll set it up with port restrictions. thanks

**Sara (internal generation stream):**

<mem_write key="infra.home.network.tailscale_acl_plan" importance="0.60" decay="medium">
Tailscale ACL segmentation plan: tag-based (infra, sara, personal) with port-specific rules. Sara VM restricted to PostgreSQL 5432, Redis 6379, Neo4j 7687, llama-server, MinIO 9000 on infra tag. Personal tag has full access.
</mem_write>

**Sara (user-visible response):**

Once the ACLs are deployed, test from Sara's VM that all the services are reachable through the restricted rules. A quick script that hits each port and reports success/failure. If anything breaks, it'll be a missed port in the ACL rather than a fundamental issue.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.sara: "Autonomous Cognition System — FastAPI"
infra.jarvis: "10.185.1.180 — orchestrator"
infra.home.network: "Tailscale mesh (avery.cloud)"
infra.home.network.tailscale_acl_plan: "Tag-based segmentation with port-specific rules. Sara restricted to DB/Redis/Neo4j/inference/MinIO."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | networking | Confidence 0.72 — general ACL structure known, syntax less sure. Transparent. |
| 2 | `<mem_read>` | `infra.jarvis` | Recall infra to answer port question. |
| 2 | `<reflect>` | — | Sara's architecture is known from memory. High confidence on this specific question. |
| 3 | `<mem_write>` | `infra.home.network.tailscale_acl_plan` | Concrete plan: tag-based + port-specific ACLs. |
