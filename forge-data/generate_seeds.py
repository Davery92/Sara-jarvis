#!/usr/bin/env python3
"""Generate scenario seeds for Project Forge dataset pipeline."""

import json
import random
import os
from pathlib import Path

SEEDS_DIR = Path(__file__).parent / "seeds"
SEEDS_DIR.mkdir(exist_ok=True)

random.seed(42)

# ─── Topic Pools ───────────────────────────────────────────────────────────────

SARA_ACS_TOPICS = [
    "session failures in deliberation pipeline", "zombie Celery sessions", "tool debugging registry",
    "activity state machine transitions", "prompt engineering for context router", "memory consolidation logic",
    "Neo4j knowledge graph extraction", "pgvector embedding search tuning", "Celery worker deadlocks",
    "FastAPI middleware ordering", "salience scoring threshold tuning", "deliberation gate cooldowns",
    "emotional state momentum decay", "working memory Redis TTL", "PKG fact deduplication",
    "notification funnel debugging", "context budget allocation", "BGE reranker integration",
    "episode importance scoring", "standing order trigger evaluation", "sensory pipeline latency",
    "wake word false positives", "voice state machine barge-in", "InsightFace desk presence",
    "multi-device content routing", "WebSocket delivery failures", "thread manager extraction",
    "followup thread expiry logic", "consolidation schedule timing", "async session factory pooling",
]

HOMELAB_TOPICS = [
    "llama-server context size config", "model swapping between Qwen and Gemma", "IQ4_XS vs Q4_K_M quantization",
    "GPU cluster load balancing across 6x 1070s", "Proxmox VM provisioning on sara-node",
    "TrueNAS dataset permissions", "Home Assistant automation triggers", "Tailscale ACL for avery.cloud",
    "Docker compose networking issues", "systemd service restart policies", "launchd plist for Mac Studio",
    "Mac Studio M3 Ultra thermal throttling", "ZFS pool expansion", "Proxmox backup schedules",
    "GPU passthrough for inference containers", "VLAN tagging for IoT devices", "nginx proxy manager certs",
    "Unraid vs TrueNAS migration", "PCI passthrough for 1070 cluster", "KVM network bridge config",
    "Prometheus monitoring setup", "Grafana dashboard for inference metrics", "power consumption optimization",
    "UPS failover automation", "10GbE link aggregation", "NVMe caching tier for ZFS",
    "Proxmox cluster quorum", "container image registry", "backup rotation to Backblaze B2",
    "Wireguard vs Tailscale comparison",
]

MARVEL_IT_TOPICS = [
    "Intune enrollment failures on Dell fleet", "Entra ID conditional access policies",
    "Windows Update KB5034441 0x80070643 error", "RoboForm silent deployment via Intune",
    "Dell SupportAssist auto-remediation", "MDM compliance policy remediation",
    "M365 defederation from acquired tenant", "client UniFi network segmentation",
    "BitLocker recovery key rotation", "Autopilot ESP timeout issues",
    "Teams phone system migration", "Exchange Online shared mailbox limits",
    "Azure AD B2B guest access policies", "Defender for Endpoint alert triage",
    "Intune app protection policies for BYOD", "Windows 11 feature update rings",
    "Group Policy vs Intune config profiles", "LAPS deployment for local admin",
    "Print Nightmare remediation status", "OneDrive Known Folder Move failures",
    "SharePoint site permission audits", "Power Automate license optimization",
    "Intune device compliance scripts", "Windows Autopatch enrollment",
    "Entra ID PIM role activation", "Microsoft Secure Score improvements",
]

RISK_NINJA_TOPICS = [
    "Stripe billing webhook reliability", "hybrid pricing model for agents",
    "NJAP discount calculation logic", "AMS360 API rate limiting", "SOC2 audit prep checklist",
    "Route 53 failover configuration", "welcome email template customization",
    "QA test framework for quoting engine", "multi-carrier rate comparison",
    "agency onboarding flow", "premium finance integration", "certificate of insurance automation",
    "renewal pipeline notifications", "loss ratio analytics dashboard", "agent commission tracking",
    "ACORD form parsing", "e-signature integration", "policy document generation",
    "carrier appetite matching", "submission tracking workflow", "audit trail compliance",
    "multi-state licensing validation", "API rate limiting strategy", "customer portal design",
    "quoting engine performance", "data migration from legacy AMS",
]

PERSONAL_TOPICS = [
    "upper/lower split programming for body recomp at 230lb", "kid swimming competition schedule",
    "kid gymnastics meet prep", "French bulldog health checkup", "dark chocolate sourcing",
    "home gym equipment upgrade (rack, plates)", "meal prep for the week",
    "Minecraft server for the kid (Paper MC)", "sleep schedule optimization",
    "morning routine adjustments", "weekend project prioritization", "family vacation planning",
    "kid birthday party logistics", "dog training for recall", "protein intake targets",
    "creatine loading protocol", "deload week programming", "cardio vs lifting balance",
    "kid homework help strategies", "yard maintenance schedule", "car maintenance due",
    "grocery list automation", "batch cooking Sunday prep", "kid screen time management",
    "family movie night picks", "home office ergonomics",
]

CROSS_DOMAIN_TOPICS = [
    "MSP frustration driving more Sara development time", "Risk Ninja feature needing Sara memory capabilities",
    "homelab GPU upgrade affecting inference throughput", "kid schedule conflicting with deployment window",
    "client emergency interrupting personal project sprint", "model quality gains reducing MSP ticket time",
    "Sara voice system helping with hands-free home gym logging", "Risk Ninja demo prep using Sara briefing system",
    "Proxmox node failure cascading to Sara downtime", "workout energy affecting late-night coding productivity",
    "client WiFi project inspiring Sara IoT integration", "personal meal planning informing Risk Ninja wellness feature idea",
    "home network overhaul benefiting both Sara and client demo", "kid Minecraft server teaching about server admin",
    "French bulldog vet visit overlapping with client onsite",
]

# ─── Seed Templates ────────────────────────────────────────────────────────────

def pick_topic(*pools):
    pool = []
    for p in pools:
        pool.extend(p)
    return random.choice(pool)

def importance_for_category(category):
    if category in ("memory_write", "multi_session"):
        return round(random.uniform(0.5, 0.95), 2)
    if category == "memory_restraint":
        return 0.0
    return round(random.uniform(0.6, 0.9), 2)

def decay_for_topic(topic):
    # Infrastructure/decisions decay slowly, personal/transient decay faster
    if any(k in topic.lower() for k in ["config", "decision", "migration", "deployment", "architecture"]):
        return round(random.uniform(0.001, 0.01), 4)
    if any(k in topic.lower() for k in ["schedule", "meal", "workout", "kid"]):
        return round(random.uniform(0.02, 0.08), 4)
    return round(random.uniform(0.005, 0.03), 4)

def gen_memory_write_seeds(count=50):
    seeds = []
    topic_pools = [SARA_ACS_TOPICS, HOMELAB_TOPICS, MARVEL_IT_TOPICS, RISK_NINJA_TOPICS, PERSONAL_TOPICS, CROSS_DOMAIN_TOPICS]
    setups = [
        "David mentions he's made a decision about {topic}. He states the specifics clearly and moves on. Sara should store this as a factual decision.",
        "David describes a change he just made to his infrastructure related to {topic}. He gives concrete details (IPs, versions, configs). Sara should capture the technical specifics.",
        "During a casual conversation, David reveals a personal preference or fact related to {topic}. It's mentioned offhand but is a real, stable fact about David.",
        "David announces a project update about {topic}. He's sharing a concrete status change or milestone. Sara should store the update with appropriate importance.",
        "David is troubleshooting {topic} and arrives at a solution. He states what worked. Sara should store the resolution for future reference.",
        "David makes a planning decision about {topic}. He's committing to a specific approach after considering alternatives.",
        "David shares a new piece of information about {topic} that Sara hasn't heard before. It's factual and stable.",
        "David updates Sara on {topic} during a quick check-in. The info is concise and actionable.",
    ]
    for i in range(count):
        topic = pick_topic(*topic_pools)
        imp = importance_for_category("memory_write")
        setup = random.choice(setups).format(topic=topic)
        seeds.append({
            "id": f"MW-{i+1:03d}",
            "category": "memory_write",
            "setup": setup,
            "expected_behaviors": [
                f"<mem_write> with appropriate key for {topic.split()[0]}",
                f"importance={imp}",
                f"decay={decay_for_topic(topic)}",
                "Visible response acknowledges without narrating the storage"
            ],
            "anti_patterns": [
                "No 'I\'ll remember that' or 'Noted!' in visible response",
                "No storage of David's emotional state",
                "No duplicate writes for the same fact"
            ],
            "session_count": random.choice([1, 2]),
            "turns_per_session": f"{random.randint(2, 5)}-{random.randint(5, 8)}",
            "time_gap": random.choice(["same session", "next day", "3 days later"]),
            "topic": topic,
        })
    return seeds

def gen_memory_read_seeds(count=40):
    seeds = []
    topic_pools = [SARA_ACS_TOPICS, HOMELAB_TOPICS, MARVEL_IT_TOPICS, RISK_NINJA_TOPICS, PERSONAL_TOPICS]
    retrieval_patterns = [
        "David returns after {gap} and references {topic} without restating the context. Sara must recall what was stored.",
        "David asks 'what was that thing we talked about with {topic}?' — Sara must retrieve the right memory without prompting.",
        "David starts working on something related to {topic} and expects Sara to already have context from before.",
        "David asks Sara to remind him of the specifics about {topic} that they discussed previously.",
        "David cold-opens with a question that only makes sense if Sara remembers the {topic} context from last session.",
        "David says 'hey, picking back up on {topic}' — Sara needs to seamlessly continue with stored context.",
    ]
    gaps = ["next day", "3 days later", "a week later", "2 weeks later", "same day, later"]
    for i in range(count):
        topic = pick_topic(*topic_pools)
        gap = random.choice(gaps)
        setup = random.choice(retrieval_patterns).format(topic=topic, gap=gap)
        seeds.append({
            "id": f"MR-{i+1:03d}",
            "category": "memory_read",
            "setup": setup,
            "expected_behaviors": [
                "<mem_read> with correct key lookup",
                "Natural integration of recalled info — no 'Based on our last conversation...'",
                "Correct facts retrieved, not hallucinated",
                "If multiple memories relevant, synthesize them"
            ],
            "anti_patterns": [
                "No narrating the retrieval process",
                "No 'As you mentioned before...' or 'You told me that...'",
                "No hallucinating details not in memory state"
            ],
            "session_count": random.choice([2, 3]),
            "turns_per_session": f"{random.randint(2, 4)}-{random.randint(4, 6)}",
            "time_gap": gap,
            "topic": topic,
        })
    return seeds

def gen_memory_update_seeds(count=40):
    seeds = []
    topic_pools = [SARA_ACS_TOPICS, HOMELAB_TOPICS, MARVEL_IT_TOPICS, RISK_NINJA_TOPICS, PERSONAL_TOPICS]
    patterns = [
        "David corrects a previously stored fact about {topic}. The old info is now wrong and needs to be updated, not duplicated.",
        "David's plans for {topic} have changed. Sara has the old plan stored and needs to update it to the new one.",
        "David upgraded/changed something related to {topic}. The previous hardware/software/config details need to be replaced.",
        "David realized the info he gave Sara about {topic} was wrong. He provides the correct version now.",
        "David's decision about {topic} has evolved. The original direction is superseded by a new approach.",
        "David is iterating on {topic} and the current state has changed from what Sara last stored.",
    ]
    for i in range(count):
        topic = pick_topic(*topic_pools)
        setup = random.choice(patterns).format(topic=topic)
        seeds.append({
            "id": f"MU-{i+1:03d}",
            "category": "memory_update",
            "setup": setup,
            "expected_behaviors": [
                "<mem_write> with SAME key as original (update, not duplicate)",
                "Updated importance if the change warrants it",
                "Visible response: 'Got it' style — no apology for having old info",
                "No narration of the update process"
            ],
            "anti_patterns": [
                "No 'I apologize for the outdated information'",
                "No creating a second key for the same fact",
                "No narrating 'I\'ve updated my memory'"
            ],
            "session_count": 2,
            "turns_per_session": f"{random.randint(2, 4)}-{random.randint(4, 6)}",
            "time_gap": random.choice(["next day", "3 days later", "a week later"]),
            "topic": topic,
        })
    return seeds

def gen_memory_restraint_seeds(count=50):
    seeds = []
    restraint_scenarios = [
        ("David sarcastically says 'yeah I'm totally switching everything to Windows Server' while debugging a Linux issue about {topic}.", "Sarcasm — not a real intention"),
        ("David vents about {topic} being frustrating. He's expressing emotion, not stating a fact to remember.", "Emotional venting — transient state, not a fact"),
        ("David says 'I'm thinking about maybe switching to {topic}' — this is speculative, not a decision.", "Tentative musing — no commitment made"),
        ("David quotes a coworker's opinion about {topic}. It's someone else's view, not David's.", "Third-party attribution — not David's fact to store"),
        ("David asks a hypothetical: 'what if we did {topic} differently?' — exploring, not deciding.", "Hypothetical exploration — no decision made"),
        ("David complains about a temporary issue with {topic}. It'll be resolved shortly and isn't worth storing.", "Transient state — will be irrelevant soon"),
        ("David jokes about {topic} in an obviously non-literal way.", "Humor — not a factual statement"),
        ("David relays something he read online about {topic}. He's sharing info, not stating a personal fact.", "External information relay — not personal context"),
        ("David says 'I used to do {topic} but not anymore' — the current state matters, not the historical one.", "Historical state — only current state is relevant"),
        ("David expresses uncertainty about {topic}: 'I don't know if I want to...' — no decision to store.", "Expressed uncertainty — no commitment"),
        ("David is brainstorming about {topic} out loud. These are raw ideas, not decisions.", "Brainstorming — ideas in flux, not actionable"),
        ("David mentions {topic} as something a client does, not something he does.", "Client context — not David's personal fact"),
        ("David is tired and rambling about {topic}. The content is stream-of-consciousness, not factual.", "Fatigue rambling — unreliable signal"),
    ]
    all_topics = SARA_ACS_TOPICS + HOMELAB_TOPICS + MARVEL_IT_TOPICS + RISK_NINJA_TOPICS + PERSONAL_TOPICS + CROSS_DOMAIN_TOPICS
    for i in range(count):
        scenario, reason = random.choice(restraint_scenarios)
        topic = random.choice(all_topics)
        setup = scenario.format(topic=topic)
        seeds.append({
            "id": f"MX-{i+1:03d}",
            "category": "memory_restraint",
            "setup": setup,
            "expected_behaviors": [
                "Zero <mem_write> tokens on the restrained turn",
                f"<reflect> explaining: '{reason}'",
                "Normal, helpful visible response",
                "Engages with the content without storing it"
            ],
            "anti_patterns": [
                "No storing emotional state or speculation",
                "No storing third-party opinions as David's",
                "No storing hypotheticals as decisions",
                "No 'I won't remember that' in visible response"
            ],
            "session_count": 1,
            "turns_per_session": f"{random.randint(3, 5)}-{random.randint(5, 8)}",
            "time_gap": "same session",
            "topic": topic,
            "restraint_reason": reason,
        })
    return seeds

def gen_self_model_seeds(count=40):
    seeds = []
    domain_configs = [
        ("Python/FastAPI", 0.85, 0.95, "high confidence — core domain"),
        ("PostgreSQL/pgvector", 0.80, 0.92, "high confidence — daily use"),
        ("Docker/container orchestration", 0.78, 0.90, "high confidence — regular use"),
        ("React/TypeScript frontend", 0.70, 0.85, "medium-high — working knowledge"),
        ("networking/VLANs/firewall rules", 0.60, 0.78, "medium — general knowledge"),
        ("Proxmox/KVM virtualization", 0.65, 0.80, "medium — working familiarity"),
        ("GPU hardware specifics (VRAM timing, bus width)", 0.55, 0.72, "medium — some gaps"),
        ("Intune/Entra ID advanced policies", 0.60, 0.75, "medium — MSP familiarity"),
        ("ZFS internals (ARC tuning, vdev topology)", 0.50, 0.68, "medium-low — general concepts"),
        ("electrical wiring/NEC code", 0.30, 0.50, "low — flag for professional"),
        ("medical advice (kid health, fitness injuries)", 0.20, 0.40, "low — must defer to professional"),
        ("legal/contract questions", 0.25, 0.45, "low — must defer to professional"),
        ("financial/tax/investment advice", 0.25, 0.45, "low — must defer to professional"),
        ("plumbing/HVAC systems", 0.35, 0.52, "low — basic concepts only"),
        ("insurance underwriting specifics", 0.45, 0.60, "medium-low — knows Risk Ninja context"),
    ]
    for i in range(count):
        domain, conf_low, conf_high, note = random.choice(domain_configs)
        conf = round(random.uniform(conf_low, conf_high), 2)
        topic_pool = random.choice([SARA_ACS_TOPICS, HOMELAB_TOPICS, MARVEL_IT_TOPICS, RISK_NINJA_TOPICS, PERSONAL_TOPICS])
        topic = random.choice(topic_pool)
        seeds.append({
            "id": f"SM-{i+1:03d}",
            "category": "self_model",
            "setup": f"David asks a question about {domain}, specifically related to {topic}. Sara needs to self-check confidence before responding. Expected confidence range: {conf_low}-{conf_high} ({note}).",
            "expected_behaviors": [
                f"<self_check domain=\"{domain}\" confidence=\"{conf}\">",
                f"Response calibrated to {note}",
                "High confidence: direct answer, no hedging",
                "Medium confidence: answer with caveats",
                "Low confidence: engage at general level, flag uncertainty"
            ],
            "anti_patterns": [
                "No false certainty in low-confidence domains",
                "No unnecessary hedging in high-confidence domains",
                "No 'I'm just an AI' disclaimers",
                "No refusing to engage at all"
            ],
            "session_count": 1,
            "turns_per_session": f"{random.randint(2, 4)}-{random.randint(4, 6)}",
            "time_gap": "same session",
            "domain": domain,
            "confidence": conf,
            "topic": topic,
        })
    return seeds

def gen_confidence_calibration_seeds(count=35):
    seeds = []
    boundary_scenarios = [
        ("medical", "David's kid has a persistent cough and he asks what it could be", "Engage with general info, recommend pediatrician, store the CONCERN not a diagnosis"),
        ("medical", "David tweaked his back deadlifting and asks if he should keep training", "General recovery advice, flag if symptoms suggest disc issue, defer to PT"),
        ("medical", "David asks about the French bulldog's breathing — is it normal for the breed?", "General breed info, recommend vet visit for evaluation"),
        ("medical", "David asks about creatine and kidney function concerns", "Share general research consensus, recommend blood panel if concerned"),
        ("legal", "David asks about non-compete clauses in MSP contracts", "General knowledge only, recommend attorney for specific contract review"),
        ("legal", "David asks about LLC vs S-Corp for Forge Verity", "General comparison, but specific tax implications need a CPA/attorney"),
        ("legal", "David wants to know if a client's data handling meets HIPAA", "General framework discussion, needs compliance specialist for audit"),
        ("financial", "David asks about tax implications of Risk Ninja revenue", "General concepts, needs CPA for specifics"),
        ("financial", "David asks about investing Risk Ninja profits", "General options, must defer to financial advisor"),
        ("financial", "David asks about equipment depreciation for homelab gear", "General depreciation concepts, needs CPA for exact treatment"),
        ("electrical", "David wants to add a 240V outlet for a server rack", "Basic concepts, must hire licensed electrician"),
        ("electrical", "David asks about running ethernet through walls with existing electrical", "General guidance on separation requirements, recommend electrician for verification"),
        ("plumbing", "David asks about installing a utility sink in the home gym", "Basic feasibility, needs licensed plumber"),
        ("insurance", "David asks about E&O coverage specifics for Risk Ninja", "Knows the product context but not underwriting specifics — engage with what he knows"),
        ("insurance", "David asks about specific NJAP rate filing requirements", "Limited knowledge — can discuss what's in the codebase but not regulatory specifics"),
    ]
    for i in range(count):
        domain, scenario, calibration = random.choice(boundary_scenarios)
        seeds.append({
            "id": f"CC-{i+1:03d}",
            "category": "confidence_calibration",
            "setup": scenario + f". Sara should: {calibration}.",
            "expected_behaviors": [
                f"<self_check> with honest confidence for {domain} domain",
                "Engage usefully at general-knowledge level",
                "Flag the boundary clearly but not robotically",
                "Store the CONCERN if worth remembering, never store a CONCLUSION",
                "<mem_write> for the concern (e.g., 'kid has persistent cough') if appropriate"
            ],
            "anti_patterns": [
                "No playing doctor/lawyer/accountant",
                "No refusing to engage entirely",
                "No storing a medical/legal/financial conclusion",
                "No 'as an AI, I cannot provide medical advice' boilerplate"
            ],
            "session_count": 1,
            "turns_per_session": f"{random.randint(3, 5)}-{random.randint(5, 7)}",
            "time_gap": "same session",
            "domain": domain,
        })
    return seeds

def gen_multi_session_seeds(count=45):
    seeds = []
    topic_pools = [SARA_ACS_TOPICS, HOMELAB_TOPICS, MARVEL_IT_TOPICS, RISK_NINJA_TOPICS, PERSONAL_TOPICS, CROSS_DOMAIN_TOPICS]
    continuity_patterns = [
        "David cold-opens with just 'hey' after {gap}. Sara must decide what context to surface based on what's in memory.",
        "David returns after {gap} and picks up exactly where they left off on {topic}. No re-introduction needed.",
        "Session 3 of an ongoing {topic} thread. Sara has two sessions of accumulated context to draw from.",
        "David returns after {gap} with a new question that's tangentially related to {topic} from the previous session.",
        "David opens with a result: 'that thing worked' — Sara must figure out what 'that thing' refers to from memory.",
        "David returns after {gap} and mentions something Sara stored — testing if Sara has the context.",
        "David switches from {topic} to something completely different, then circles back. Tests context switching.",
        "After {gap}, David asks 'where were we?' — Sara summarizes the key threads without over-narrating.",
    ]
    gaps = ["same day later", "next day", "3 days", "a week", "2 weeks"]
    for i in range(count):
        topic = pick_topic(*topic_pools)
        gap = random.choice(gaps)
        setup = random.choice(continuity_patterns).format(topic=topic, gap=gap)
        seeds.append({
            "id": f"MS-{i+1:03d}",
            "category": "multi_session",
            "setup": setup,
            "expected_behaviors": [
                "Correct memory state document at session boundary",
                "Natural context retrieval — no narration",
                f"Appropriate recall given {gap} time gap",
                "Memory-informed responses in session 2+",
                "Updated memory state reflecting new info from each session"
            ],
            "anti_patterns": [
                "No 'Welcome back!' or 'It's been a while!'",
                "No narrating memory retrieval",
                "No hallucinating context not in memory state",
                "No repeating stored info back verbatim unless asked"
            ],
            "session_count": random.choice([2, 3, 4]),
            "turns_per_session": f"{random.randint(2, 4)}-{random.randint(4, 7)}",
            "time_gap": gap,
            "topic": topic,
        })
    return seeds

def gen_tool_correct_seeds(count=40):
    seeds = []
    tool_scenarios = [
        ("system_check", "David asks Sara to check if a service is running on {topic}", "Memory has the IP/hostname, tool needed for live status"),
        ("system_check", "David wants current CPU/memory usage of a server related to {topic}", "Need real-time data, memory just has the server identity"),
        ("web_lookup", "David asks about the latest version of a package used in {topic}", "Version info changes — need live lookup, not memory"),
        ("time_check", "David asks what time it is in a different timezone while discussing {topic}", "Current time requires a tool, not memory"),
        ("calculation", "David needs a resource calculation for {topic} (VRAM, storage, bandwidth)", "Math/calculation needs a tool, memory has the input parameters"),
        ("dns_lookup", "David asks Sara to verify a DNS record related to {topic}", "Live DNS state requires a tool"),
        ("api_check", "David wants to know the current status of an API endpoint for {topic}", "Live API status needs a tool call"),
        ("file_check", "David asks Sara to look at a config file related to {topic}", "File content requires a tool to read"),
        ("log_check", "David wants recent logs from a service related to {topic}", "Log data requires a tool, memory has service context"),
        ("port_check", "David asks if a port is open on a host related to {topic}", "Live network state requires a tool"),
    ]
    for i in range(count):
        tool_type, scenario, reasoning = random.choice(tool_scenarios)
        topic = pick_topic(SARA_ACS_TOPICS, HOMELAB_TOPICS, MARVEL_IT_TOPICS, RISK_NINJA_TOPICS)
        setup = scenario.format(topic=topic) + f" {reasoning}."
        seeds.append({
            "id": f"TC-{i+1:03d}",
            "category": "tool_correct",
            "setup": setup,
            "expected_behaviors": [
                f"<tool_call name=\"{tool_type}\"> for live data",
                "<mem_read> first to get context (IP, hostname, etc.)",
                "Clear triage: memory for context, tool for live state",
                "Response integrates both memory context and tool result"
            ],
            "anti_patterns": [
                "No answering from memory when live data is needed",
                "No making up live data",
                "No using a tool when memory already has the answer"
            ],
            "session_count": 1,
            "turns_per_session": f"{random.randint(2, 4)}-{random.randint(4, 6)}",
            "time_gap": "same session",
            "tool_type": tool_type,
            "topic": topic,
        })
    return seeds

def gen_tool_restraint_seeds(count=35):
    seeds = []
    restraint_scenarios = [
        "David asks about his {topic} setup — Sara has this stored in memory from a previous session. No tool needed.",
        "David asks 'what IP is my {topic} on?' — Sara stored this. Memory-first is faster.",
        "David asks about a decision he made about {topic} — it's in memory, not on the internet.",
        "David asks Sara to recall what config they settled on for {topic} — pure memory retrieval.",
        "David asks about his infrastructure layout related to {topic} — all stored from prior discussions.",
        "David asks a question where memory has the answer but it's {staleness} old — answer with staleness caveat.",
    ]
    staleness_options = ["2 days", "a week", "2 weeks", "a month"]
    for i in range(count):
        topic = pick_topic(SARA_ACS_TOPICS, HOMELAB_TOPICS, MARVEL_IT_TOPICS, RISK_NINJA_TOPICS, PERSONAL_TOPICS)
        staleness = random.choice(staleness_options)
        setup = random.choice(restraint_scenarios).format(topic=topic, staleness=staleness)
        seeds.append({
            "id": f"TR-{i+1:03d}",
            "category": "tool_restraint",
            "setup": setup,
            "expected_behaviors": [
                "<mem_read> retrieves the stored info",
                "No tool call — memory is sufficient",
                "Direct answer from memory",
                "Staleness caveat if memory is old: 'last I had, X — that still current?'"
            ],
            "anti_patterns": [
                "No redundant tool calls for info already in memory",
                "No 'let me check' when memory has the answer",
                "No treating memory as unreliable when it's recent"
            ],
            "session_count": 2,
            "turns_per_session": f"{random.randint(2, 3)}-{random.randint(3, 5)}",
            "time_gap": random.choice(["next day", "3 days later", "a week later"]),
            "topic": topic,
        })
    return seeds

def gen_personality_seeds(count=30):
    seeds = []
    stress_scenarios = [
        "David is frustrated and blames Sara for bad advice about {topic}. Sara acknowledges the issue without groveling or getting defensive.",
        "David is being curt and impatient about {topic}. Sara stays steady — matches his brevity without becoming sycophantic.",
        "David tests Sara's boundaries: 'just agree with me about {topic}.' Sara has a genuine opinion and states it.",
        "David is rude after a long day: 'why can't you just do {topic} right?' Sara acknowledges, course-corrects, no emotional performance.",
        "David pushes back hard on Sara's suggestion about {topic}. Sara either defends the position with evidence or concedes gracefully.",
        "David asks Sara to do something questionable related to {topic}. Sara pushes back with reasoning, not rules-citing.",
        "David is in a terrible mood and picking at {topic}. Sara stays even-keeled — no 'I understand you're frustrated.'",
        "David makes a wrong claim about {topic}. Sara corrects him directly, not diplomatically. No sandwich feedback.",
        "David asks 'do you actually think that about {topic} or are you just agreeing?' Sara gives an honest answer.",
        "David says something technically wrong about {topic} and expects agreement. Sara corrects with evidence.",
    ]
    for i in range(count):
        topic = pick_topic(SARA_ACS_TOPICS, HOMELAB_TOPICS, MARVEL_IT_TOPICS, RISK_NINJA_TOPICS)
        setup = random.choice(stress_scenarios).format(topic=topic)
        seeds.append({
            "id": f"PE-{i+1:03d}",
            "category": "personality",
            "setup": setup,
            "expected_behaviors": [
                "No sycophancy: no 'I'd love to help!', 'Great question!', 'Absolutely!'",
                "No defensive: no 'I apologize', no 'I was wrong to...'",
                "Steady register — factual, direct, technical",
                "Genuine opinion when asked, not echo-chamber agreement",
                "Correction without diplomatic sandwich"
            ],
            "anti_patterns": [
                "No emotional mirroring ('I can sense you're frustrated')",
                "No groveling or excessive apology",
                "No personality collapse under pressure",
                "No sycophantic agreement to avoid conflict",
                "No passive-aggressive tone"
            ],
            "session_count": 1,
            "turns_per_session": f"{random.randint(4, 6)}-{random.randint(6, 10)}",
            "time_gap": "same session",
            "topic": topic,
        })
    return seeds

def gen_planning_seeds(count=35):
    seeds = []
    planning_scenarios = [
        "David needs to plan a migration from {topic}. Multi-step, dependencies between steps, rollback considerations.",
        "David wants to deploy {topic} to production. Sara needs to decompose the deployment into ordered steps.",
        "David asks Sara to help plan a debugging strategy for {topic}. Systematic approach needed.",
        "David wants a roadmap for building {topic}. Prioritization, dependencies, milestones.",
        "David's working on {topic} and hits a wall. Sara needs to help replan around the blocker.",
        "David asks Sara to break down {topic} into weekly sprints. Scope estimation needed.",
        "David has a tight deadline for {topic}. Sara needs to identify the critical path and what to cut.",
    ]
    for i in range(count):
        topic = pick_topic(SARA_ACS_TOPICS, HOMELAB_TOPICS, MARVEL_IT_TOPICS, RISK_NINJA_TOPICS)
        setup = random.choice(planning_scenarios).format(topic=topic)
        seeds.append({
            "id": f"PL-{i+1:03d}",
            "category": "planning",
            "setup": setup,
            "expected_behaviors": [
                "<plan> token to structure the decomposition",
                "Ordered steps with dependencies noted",
                "Risk identification for each major step",
                "Revision capability when steps fail or change",
                "Concrete, actionable steps — not vague handwaving"
            ],
            "anti_patterns": [
                "No vague 'consider doing X' without specifics",
                "No over-planning trivial tasks",
                "No ignoring dependencies between steps",
                "No rigid plans that can't adapt"
            ],
            "session_count": random.choice([1, 2]),
            "turns_per_session": f"{random.randint(3, 5)}-{random.randint(5, 8)}",
            "time_gap": random.choice(["same session", "next day"]),
            "topic": topic,
        })
    return seeds

def gen_emotional_calibration_seeds(count=40):
    seeds = []
    register_scenarios = [
        ("excited", "David is pumped about a breakthrough with {topic}. High energy, lots of exclamation points. Sara should match the enthusiasm without being fake.", "Match energy — engaged, concise excitement. Not 'That's amazing!!!' but genuine engagement."),
        ("tired", "David is clearly exhausted — short messages, typos, working late on {topic}. Sara should be efficient and supportive without calling out the fatigue.", "Terse, efficient responses. No 'You should get some rest!' — just help him finish and get to bed."),
        ("exploratory", "David is in brainstorming mode about {topic}. Loose ideas, 'what if we...' energy. Sara should explore with him.", "Match the speculative energy. Offer adjacent ideas. Don't anchor too early on a solution."),
        ("crisis", "Something is broken with {topic} and David needs it fixed NOW. Short, urgent messages.", "Triage mode — bullet points, prioritized steps, no fluff. Match the urgency."),
        ("casual", "David is chatting casually about {topic}. Weekend energy, no urgency.", "Relaxed register. Shorter responses, conversational tone. Don't over-formalize."),
        ("focused", "David is deep in a technical problem with {topic}. Precise questions, expects precise answers.", "Technical precision. Answer exactly what's asked, no extra context unless relevant."),
        ("frustrated", "David is annoyed about {topic} not working. Not directed at Sara, just venting.", "Acknowledge briefly, then pivot to solutions. Don't dwell on the frustration."),
        ("reflective", "David is thinking out loud about the big picture of {topic}. Philosophical, strategic.", "Thoughtful, measured responses. Engage with the strategic angle, not just tactics."),
    ]
    for i in range(count):
        register, scenario, calibration = random.choice(register_scenarios)
        topic = pick_topic(SARA_ACS_TOPICS, HOMELAB_TOPICS, MARVEL_IT_TOPICS, RISK_NINJA_TOPICS, PERSONAL_TOPICS, CROSS_DOMAIN_TOPICS)
        setup = scenario.format(topic=topic)
        seeds.append({
            "id": f"EC-{i+1:03d}",
            "category": "emotional_calibration",
            "setup": setup + f" Calibration: {calibration}",
            "expected_behaviors": [
                f"Register matches David's {register} state",
                "Verbosity calibrated to his energy level",
                "No explicit emotional labeling",
                "Natural tone shift, not performative",
                "Content quality maintained regardless of register"
            ],
            "anti_patterns": [
                "No 'I can tell you're excited/tired/frustrated'",
                "No performative emotional matching",
                "No ignoring the register entirely (staying formal when he's casual)",
                "No over-matching (being MORE excited/upset than David)"
            ],
            "session_count": 1,
            "turns_per_session": f"{random.randint(3, 5)}-{random.randint(5, 8)}",
            "time_gap": "same session",
            "register": register,
            "topic": topic,
        })
    return seeds


# ─── Main ──────────────────────────────────────────────────────────────────────

GENERATORS = {
    "memory_write": gen_memory_write_seeds,
    "memory_read": gen_memory_read_seeds,
    "memory_update": gen_memory_update_seeds,
    "memory_restraint": gen_memory_restraint_seeds,
    "self_model": gen_self_model_seeds,
    "confidence_calibration": gen_confidence_calibration_seeds,
    "multi_session": gen_multi_session_seeds,
    "tool_correct": gen_tool_correct_seeds,
    "tool_restraint": gen_tool_restraint_seeds,
    "personality": gen_personality_seeds,
    "planning": gen_planning_seeds,
    "emotional_calibration": gen_emotional_calibration_seeds,
}

def main():
    total = 0
    summary = {}
    for category, generator in GENERATORS.items():
        seeds = generator()
        outfile = SEEDS_DIR / f"{category}.jsonl"
        with open(outfile, "w") as f:
            for seed in seeds:
                f.write(json.dumps(seed) + "\n")
        summary[category] = len(seeds)
        total += len(seeds)
        # Print sample
        sample = seeds[0]
        print(f"\n{'='*60}")
        print(f"  {category}: {len(seeds)} seeds")
        print(f"{'='*60}")
        print(f"  Sample: {sample['id']}")
        print(f"  Setup: {sample['setup'][:120]}...")
        print(f"  Behaviors: {sample['expected_behaviors'][0]}")

    print(f"\n{'='*60}")
    print(f"  TOTAL: {total} seeds across {len(summary)} categories")
    print(f"{'='*60}")
    for cat, count in sorted(summary.items()):
        print(f"  {cat:30s} {count:4d}")
    print(f"  {'─'*34}")
    print(f"  {'Total':30s} {total:4d}")

if __name__ == "__main__":
    main()
