"""
Seed Script: Known Domains
Populates David's known domains for analogy anchoring in the learning system.
Idempotent — uses INSERT ... ON CONFLICT DO NOTHING.
"""
import os
import sys
import uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text


KNOWN_DOMAINS = [
    {
        "domain_name": "Server Architecture",
        "description": "Linux server administration, process management, systemd, nginx, reverse proxies",
        "proficiency": "expert",
        "key_concepts": ["nginx reverse proxy", "systemd services", "process management", "load balancing", "SSL termination", "log aggregation", "cron jobs", "SSH tunneling"]
    },
    {
        "domain_name": "Networking",
        "description": "TCP/IP, DNS, VPNs (Tailscale), firewalls, subnets, port forwarding",
        "proficiency": "expert",
        "key_concepts": ["TCP/IP stack", "DNS resolution", "Tailscale/WireGuard VPN", "subnets and CIDR", "port forwarding", "NAT", "firewalls (iptables/nftables)", "HTTP/HTTPS"]
    },
    {
        "domain_name": "Containerization",
        "description": "Docker, Docker Compose, container networking, volumes, multi-stage builds",
        "proficiency": "expert",
        "key_concepts": ["Docker containers", "Docker Compose", "container networking", "volumes and bind mounts", "multi-stage builds", "image layers", "container orchestration basics", "health checks"]
    },
    {
        "domain_name": "Database Systems",
        "description": "PostgreSQL, SQLAlchemy ORM, pgvector, Redis, Neo4j graph database",
        "proficiency": "intermediate",
        "key_concepts": ["PostgreSQL", "SQLAlchemy ORM", "pgvector embeddings", "Redis caching", "Neo4j graph queries", "database migrations", "connection pooling", "JSONB columns"]
    },
    {
        "domain_name": "Sara's Architecture",
        "description": "The Sara/Jarvis personal AI hub codebase — FastAPI backend, React frontend, Celery workers",
        "proficiency": "expert",
        "key_concepts": ["FastAPI routes", "SimpleLLMClient", "tool registry pattern", "episodic memory system", "subconscious worker", "heartbeat agent", "context router", "personality engine", "activity state machine"]
    },
    {
        "domain_name": "Home Infrastructure",
        "description": "Home Assistant, smart home automation, IoT devices, sensor data, reactive rules",
        "proficiency": "expert",
        "key_concepts": ["Home Assistant", "entity states", "automations and scenes", "motion sensors", "smart lights (Hue)", "thermostat control", "presence detection", "webhooks and MQTT"]
    },
    {
        "domain_name": "Fitness & Body",
        "description": "Strength training, nutrition tracking, recovery science, body metrics",
        "proficiency": "intermediate",
        "key_concepts": ["progressive overload", "macros and calories", "recovery metrics (HRV, RHR)", "training programs and phases", "RPE and volume", "sleep quality", "body composition"]
    },
    {
        "domain_name": "Software Patterns",
        "description": "Design patterns, architecture patterns, async programming, event-driven systems",
        "proficiency": "intermediate",
        "key_concepts": ["singleton pattern", "event bus / pub-sub", "async/await", "middleware chains", "dependency injection", "repository pattern", "state machines", "CQRS basics"]
    },
    {
        "domain_name": "AI & LLM Systems",
        "description": "LLM prompting, RAG, embeddings, tool use, function calling, context windows",
        "proficiency": "intermediate",
        "key_concepts": ["system prompts", "RAG retrieval", "embedding similarity", "tool/function calling", "context window management", "streaming responses", "token budgets", "temperature and sampling"]
    },
    {
        "domain_name": "Business & SaaS",
        "description": "SaaS business models, product development, user acquisition, metrics",
        "proficiency": "beginner",
        "key_concepts": ["MRR/ARR", "churn rate", "product-market fit", "user onboarding", "pricing strategy", "MVP approach", "growth loops"]
    },
]


def run_seed():
    """Seed known domains for David"""
    database_url = os.getenv("DATABASE_URL", "postgresql://sara:sara123@10.185.1.180:5432/sara_hub")
    engine = create_engine(database_url)

    # Get David's user ID
    solo_user_id = os.getenv("SOLO_USER_ID", "adfc17d1-23e6-4079-b30e-86e1c7f4809d")

    with engine.connect() as conn:
        for domain in KNOWN_DOMAINS:
            domain_id = str(uuid.uuid4())
            import json
            conn.execute(text("""
                INSERT INTO known_domain (id, user_id, domain_name, description, proficiency, key_concepts)
                VALUES (:id, :user_id, :domain_name, :description, :proficiency, CAST(:key_concepts AS jsonb))
                ON CONFLICT (user_id, domain_name) DO NOTHING
            """), {
                "id": domain_id,
                "user_id": solo_user_id,
                "domain_name": domain["domain_name"],
                "description": domain["description"],
                "proficiency": domain["proficiency"],
                "key_concepts": json.dumps(domain["key_concepts"]),
            })
            print(f"  {domain['domain_name']}: seeded")

        conn.commit()
        print(f"\nSeeded {len(KNOWN_DOMAINS)} known domains for user {solo_user_id}")


if __name__ == "__main__":
    run_seed()
