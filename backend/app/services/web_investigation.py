"""
Web investigation — "Sara, go check out getcara.ai and tell me about it".

When David points Sara at a website, that's NOT a quick inline answer and NOT a
web_search snippet. It's dropped into the autonomous background agent: the local
model opens the site in a real browser (Playwright `browse` tool), explores the
homepage + key pages, and writes a full detailed report (with screenshots where
useful) that comes back as a result note + notification.

This module just (a) recognizes that intent deterministically and (b) dispatches
the background agent with a strong investigation brief. The agent + browse tool
live in agent_dispatch.py; delivery (result note + push) is the standard dispatch
completion path.
"""

from __future__ import annotations

import logging
import re
from typing import List

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Safety cap so a pasted list of links can't fan out into dozens of agents.
MAX_TARGETS = 5

# An explicit URL, or a bare domain (optionally with a path).
_URL_RE = re.compile(r"https?://[^\s<>()\[\]]+", re.I)
_DOMAIN_RE = re.compile(
    r"\b((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})((?:/[^\s<>()\[\]]*)?)",
    re.I,
)

# Intent must be investigative — a casual mention of a domain ("I love github.com")
# should NOT fire. One of these phrases must be present.
_TRIGGERS = (
    "check out", "checkout", "check on", "look at", "look into", "take a look",
    "investigate", "scope out", "research", "browse", "visit", "go to", "goto",
    "pull up", "tell me about", "what is", "what's", "whats", "dig into",
    "inspect", "review the site", "review the website", "following website",
    "following site", "following url", "this website", "this site", "this url",
)

# TLDs that are almost always file extensions / not sites — avoid false hits like
# "config.yaml" or "main.py". (We still accept real ccTLDs like .ai, .io, .co.)
_FILE_TLDS = {
    "py", "js", "ts", "md", "txt", "json", "yaml", "yml", "sh", "go", "rs",
    "java", "css", "html", "png", "jpg", "jpeg", "gif", "svg", "pdf", "csv",
    "log", "env", "cfg", "ini", "toml", "lock", "sql", "xml",
}


def detect(message: str, db: Session, user_id: str) -> List[str]:
    """Return all normalized URLs to investigate (empty if this isn't that intent)."""
    if not message:
        return []
    low = message.lower()
    if not any(t in low for t in _TRIGGERS):
        return []

    urls: List[str] = []
    seen: set = set()
    covered: List[tuple] = []  # spans of explicit URLs, so _DOMAIN_RE skips them

    # Explicit URLs first.
    for m in _URL_RE.finditer(message):
        covered.append(m.span())
        url = m.group(0).rstrip(".,!?;:")
        if url.lower() not in seen:
            seen.add(url.lower())
            urls.append(url)

    # Then bare domains — but reject emails and file-like names.
    for dm in _DOMAIN_RE.finditer(message):
        if any(s <= dm.start() < e for s, e in covered):
            continue  # inside an explicit URL we already captured
        domain = dm.group(1)
        path = dm.group(2) or ""
        start = dm.start(1)
        if start > 0 and message[start - 1] == "@":
            continue  # part of an email address
        tld = domain.rsplit(".", 1)[-1].lower()
        if tld in _FILE_TLDS:
            continue
        # If it's a registered managed host, that's host inspection, not web.
        try:
            from app.services import host_inspector
            if host_inspector.get_host(db, user_id, domain.lower()):
                continue
        except Exception:
            pass
        url = ("https://" + domain + path).rstrip(".,!?;:")
        if url.lower() not in seen:
            seen.add(url.lower())
            urls.append(url)

    if len(urls) > MAX_TARGETS:
        logger.warning(
            "Web investigation capped at %d targets (%d detected)", MAX_TARGETS, len(urls)
        )
        urls = urls[:MAX_TARGETS]
    return urls


def build_brief(urls: List[str]) -> str:
    """The investigation instruction handed to the background agent.

    One or many sites, always ONE report. Multiple sites get a comparative
    report with a section per site plus a head-to-head comparison.
    """
    if len(urls) == 1:
        url = urls[0]
        return (
            f"Investigate the website {url} thoroughly using the `browse` tool (a real "
            f"headless browser), then write a DETAILED report on what you found.\n\n"
            f"Steps:\n"
            f"1. browse {url} (the homepage). Read the rendered text and note the title.\n"
            f"2. Identify and browse the most informative internal pages you find in the "
            f"links — e.g. about / product / features / pricing / docs / blog. Browse 2–5 "
            f"of them (stay on the same site).\n"
            f"3. Take a screenshot of the homepage and any page that's visually important.\n\n"
            f"Then call report_complete with a thorough markdown report covering:\n"
            f"- **What it is**: the product/company/site in 1–2 sentences.\n"
            f"- **Who it's for** and the core value proposition.\n"
            f"- **Key features / offerings** (bulleted).\n"
            f"- **Pricing / plans** if shown.\n"
            f"- **Notable content** (claims, integrations, customers, team, news).\n"
            f"- **Tech / signals** you can infer (stack hints, it being a waitlist/beta, etc.).\n"
            f"- **Any embedded screenshot image URLs** the browse tool returned — include them "
            f"inline as markdown images so David can see them.\n"
            f"- A short **bottom line**.\n"
            f"Be specific and cite what you actually saw on the pages — do not pad with "
            f"generic filler. If a page fails to load, note it and continue."
        )

    site_list = "\n".join(f"- {u}" for u in urls)
    return (
        f"Investigate ALL of the following {len(urls)} websites using the `browse` tool "
        f"(a real headless browser), then write ONE combined comparative report:\n"
        f"{site_list}\n\n"
        f"For EACH site, in order:\n"
        f"1. browse the homepage. Read the rendered text and note the title.\n"
        f"2. Browse 2–3 of the most informative internal pages — e.g. about / product / "
        f"features / pricing / docs (stay on the same site).\n"
        f"3. Take a screenshot of the homepage.\n\n"
        f"Then call report_complete ONCE with a single thorough markdown report — do NOT "
        f"write separate reports per site. Structure it as:\n"
        f"- A **section per site** covering: what it is, who it's for, core value "
        f"proposition, key features (bulleted), pricing/plans if shown, notable signals "
        f"(stack hints, waitlist/beta, customers, team), and its homepage screenshot "
        f"embedded inline as a markdown image.\n"
        f"- A **comparison section**: how they stack up against each other — overlapping "
        f"vs differentiated features, target audience, pricing, maturity. Use a markdown "
        f"comparison table where it helps.\n"
        f"- A short **bottom line**: which stands out and why.\n"
        f"Be specific and cite what you actually saw on the pages — do not pad with "
        f"generic filler. If a site or page fails to load, note it in its section and "
        f"continue with the rest."
    )


async def dispatch_investigation(db: Session, user_id: str, urls: List[str]) -> dict:
    """Fire ONE background agent to investigate `urls` (combined report if multiple)."""
    from app.services.agent_dispatch import agent_dispatch_service
    return await agent_dispatch_service.dispatch_task(
        db=db,
        user_id=user_id,
        task_description=build_brief(urls),
        mode="auto",
        # _deliver_result_to_user already sends ONE push that deep-links to the
        # report note; notify_on_complete would add a second, non-deep-linked
        # "Done:" push. Keep it to a single note-opening notification.
        notify_on_complete=False,
    )
