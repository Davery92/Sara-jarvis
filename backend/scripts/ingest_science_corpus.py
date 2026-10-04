#!/usr/bin/env python3
"""Register a list of open-access papers into the science library.

Written while ingesting a 50-paper corpus by hand on 2026-10-04 and kept
because the hard parts are not obvious and would otherwise be rediscovered:

1. **A PMC article page is mostly not the article.** Fed whole, a page
   yields 250-400 chunks of navigation, author affiliations, figure
   captions and — worst — the reference list, which is dense, retrievable
   prose that says nothing. `science.search` would happily return a
   numbered bibliography entry as support for a programming claim. This
   keeps the abstract and the article body, and drops the ref-list section.

2. **`source_type` must come from the TITLE only.** The first pass matched
   "position stand|consensus" against the title plus the opening body text,
   and a systematic review whose introduction says "there is consensus
   that..." was filed as a position stand. Three of 46 were wrong this way.
   Position stands announce themselves in the title; body prose does not.

3. **A paywall page is not a paper, and refusing it is the point.** Below
   `MIN_ARTICLE_CHARS` the fetch got an abstract or a licence notice.
   Registering that creates a citable record with no content behind it, so
   this skips it loudly instead. Note the converse, also learned the hard
   way: a Springer or PubMed link does NOT mean the paper is unreachable —
   4 of 50 links looked closed and all 4 had open full text elsewhere.
   Resolve the DOI before concluding anything (`--resolve`).

4. **Embedding is the slow part and must stay bounded.** `science.embed_chunks`
   caps itself at four requests in flight because one paper is 25-100 chunks
   and firing them all at once times every one of them out. Do not run two
   of these at the same time for the same reason.

Everything registered lands `unreviewed`, which means it is stored, chunked,
embedded — and NOT retrievable. `science.search` returns accepted records
only. Acceptance needs a reason and a limitations note per paper and is a
human judgement; this script deliberately cannot make it.

Runs INSIDE the api container (it needs the app package and the database):

    docker exec -w /app -e PYTHONPATH=/app jarvis-backend-1 \
        python -u scripts/ingest_science_corpus.py --corpus /tmp/corpus.tsv

Corpus file: one paper per line, tab-separated, `#` comments allowed.

    PMC12965823        hypertrophy,strength
    10.1186/s12970-020-00383-4    supplements
    https://pmc.ncbi.nlm.nih.gov/articles/PMC9302196/    hypertrophy
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from html import unescape
from typing import List, Optional, Tuple

from sqlalchemy import text as sqltext

from app.db.session import SessionLocal
from app.schemas.fitness_coach import (
    ScienceRegisterInput,
    ScienceTopic,
    SourceType,
)
from app.services.fitness import science

#: Below this many characters the page was an abstract, a paywall notice or
#: a redirect — not a paper. See the module docstring, point 3.
MIN_ARTICLE_CHARS = 6000

PMC_ARTICLE_URL = "https://pmc.ncbi.nlm.nih.gov/articles/%s/"
IDCONV = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"


# --------------------------------------------------------------------------
# identifiers
# --------------------------------------------------------------------------
def _idconv(ids: List[str], idtype: Optional[str], contact: Optional[str]) -> dict:
    """Map DOIs or PMIDs to PMC ids. Returns {given_id: pmcid|None}."""
    params = {"ids": ",".join(ids), "format": "json", "tool": "sara-science"}
    if idtype:
        params["idtype"] = idtype
    if contact:
        # NCBI asks for a contact address so it can warn before blocking a
        # misbehaving client. Optional on purpose: no address is baked in.
        params["email"] = contact
    url = IDCONV + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=45) as resp:
        payload = json.load(resp)
    out = {}
    for rec in payload.get("records", []):
        key = rec.get("doi") or rec.get("pmid")
        out[str(key)] = rec.get("pmcid")
    return out


def resolve(raw: str, contact: Optional[str]) -> Tuple[Optional[str], str]:
    """(pmc_id, note) for a PMC id, a PMC url, a DOI or a PMID."""
    token = raw.strip()
    if token.lower().startswith("http") and "/articles/pmc" in token.lower():
        pmc = re.search(r"(PMC\d+)", token, re.I)
        return (pmc.group(1).upper() if pmc else None), "from url"
    if re.fullmatch(r"PMC\d+", token, re.I):
        return token.upper(), "given"
    if token.startswith("10."):
        got = _idconv([token], None, contact).get(token)
        return got, ("doi -> %s" % got if got else "doi not in PMC")
    if re.fullmatch(r"\d{6,9}", token):
        got = _idconv([token], "pmid", contact).get(token)
        return got, ("pmid -> %s" % got if got else "pmid not in PMC")
    return None, "unrecognised identifier"


# --------------------------------------------------------------------------
# page -> article text
# --------------------------------------------------------------------------
def _section(html: str, pattern: str) -> str:
    """The balanced <section> whose opening tag matches `pattern`."""
    match = re.search(pattern, html, re.I)
    if not match:
        return ""
    start, depth = match.start(), 0
    for tag in re.finditer(r"<(/?)section\b[^>]*>", html[start:], re.I):
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            return html[start:start + tag.end()]
    return html[start:start + 200_000]


def article_text(html: str) -> str:
    """Abstract + body, with the reference list and furniture removed."""
    parts = [
        _section(html, r'<section[^>]*class="[^"]*\babstract\b'),
        _section(html, r'<section[^>]*class="[^"]*main-article-body'),
    ]
    body = "\n".join(part for part in parts if part)
    body = re.sub(
        r'<section[^>]*class="[^"]*\bref-list\b.*?</section>',
        " ", body, flags=re.I | re.S,
    )
    for junk in (r"<script.*?</script>", r"<style.*?</style>",
                 r"<figure.*?</figure>", r"<table.*?</table>", r"<nav.*?</nav>"):
        body = re.sub(junk, " ", body, flags=re.I | re.S)
    body = unescape(re.sub(r"<[^>]+>", " ", body))
    body = re.sub(r"[ \t ]+", " ", body)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", body).strip()


def title_of(html: str) -> Optional[str]:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not match:
        return None
    title = unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return re.sub(r"\s*[-–|]\s*PMC\s*$", "", title).strip() or None


def doi_of(html: str) -> Optional[str]:
    for pattern in (r'name="citation_doi"\s+content="([^"]+)"',
                    r'\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]{4,})'):
        match = re.search(pattern, html, re.I)
        if match:
            return match.group(1).rstrip(".,;)")
    return None


# --------------------------------------------------------------------------
# classification — title only. See the module docstring, point 2.
# --------------------------------------------------------------------------
TITLE_RULES = (
    (r"\bposition stand\b|\bposition statement\b|\bconsensus (statement|recommendation)",
     "position_stand"),
    (r"\bumbrella review\b", "systematic_review"),
    (r"\bmeta-?analy", "meta_analysis"),
    (r"\bsystematic review\b|\bscoping review\b", "systematic_review"),
    (r"\brandomi[sz]ed controlled trial\b|\brandomi[sz]ed trial\b", "rct"),
    (r"\bnarrative review\b|\breview\b|\bperspective\b", "narrative_review"),
)


def source_type_of(title: str) -> str:
    lowered = (title or "").lower()
    for pattern, kind in TITLE_RULES:
        if re.search(pattern, lowered):
            return kind
    return "secondary"


# --------------------------------------------------------------------------
def read_corpus(path: str) -> List[Tuple[str, List[str]]]:
    entries = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            ident, _, topics = line.partition("\t")
            names = [t.strip() for t in topics.replace(",", " ").split() if t.strip()]
            entries.append((ident.strip(), names))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--corpus", required=True,
                        help="tab-separated identifier<TAB>topic,topic per line")
    parser.add_argument("--user-id", default=None,
                        help="owner; defaults to the account with the most workouts")
    parser.add_argument("--contact-email", default=os.getenv("NCBI_CONTACT_EMAIL"),
                        help="passed to the NCBI id converter when resolving DOIs")
    parser.add_argument("--resolve", action="store_true",
                        help="resolve identifiers and print the plan, register nothing")
    args = parser.parse_args()

    entries = read_corpus(args.corpus)
    if not entries:
        print("corpus is empty")
        return 1

    plan = []
    for number, (ident, topics) in enumerate(entries, 1):
        pmc, note = resolve(ident, args.contact_email)
        if not pmc:
            print("%2d %-34s UNRESOLVED (%s)" % (number, ident[:34], note))
            continue
        if not topics:
            print("%2d %-34s NO TOPICS — every record needs at least one"
                  % (number, ident[:34]))
            continue
        try:
            named = [ScienceTopic(t) for t in topics]
        except ValueError as exc:
            print("%2d %-34s BAD TOPIC %s" % (number, ident[:34], exc))
            continue
        plan.append((number, pmc, named, note))

    if args.resolve:
        for number, pmc, topics, note in plan:
            print("%2d %-13s %-28s %s" % (
                number, pmc, ",".join(t.value for t in topics), note))
        print("PLAN %d of %d entries resolved" % (len(plan), len(entries)))
        return 0 if len(plan) == len(entries) else 1

    db = SessionLocal()
    user_id = args.user_id or db.execute(sqltext(
        "select u.id from app_user u order by"
        " (select count(*) from workout_log w where w.user_id = u.id) desc"
        " limit 1"
    )).scalar()
    if not user_id:
        print("no user to own these records")
        return 1
    print("owner=%s entries=%d" % (user_id, len(plan)))

    ok = dup = skip = fail = 0
    for number, pmc, topics, _note in plan:
        url = PMC_ARTICLE_URL % pmc
        try:
            raw, mime = asyncio.run(science.fetch_source(url))
            html = raw.decode("utf-8", "ignore")
            title, doi, body = title_of(html), doi_of(html), article_text(html)
            if not title:
                print("%2d %s SKIP no title on the page" % (number, pmc))
                skip += 1
                continue
            if len(body) < MIN_ARTICLE_CHARS:
                print("%2d %s SKIP only %d chars of article — abstract or "
                      "paywall, not a paper" % (number, pmc, len(body)))
                skip += 1
                continue
            payload = ScienceRegisterInput(
                title=title[:500],
                source_type=SourceType(source_type_of(title)),
                topics=topics,
                doi=doi,
                url=url,
            )
            started = time.monotonic()
            result = asyncio.run(science.register_source(
                db, user_id, payload,
                content=body.encode("utf-8"),
                mime_type="text/plain",
                filename=pmc + ".txt",
                discovered_by="url",
            ))
            elapsed = time.monotonic() - started
            if result.duplicate_of:
                print("%2d %s DUP  %s" % (number, pmc, (result.detail or "")[:60]))
                dup += 1
            else:
                print("%2d %s OK   %-18s %3d chunks %6.1fs  %s" % (
                    number, pmc, payload.source_type.value,
                    result.chunk_count, elapsed, title[:56]))
                ok += 1
        except Exception as exc:                      # noqa: BLE001 - reported
            print("%2d %s FAIL %s: %s" % (
                number, pmc, type(exc).__name__, str(exc)[:95]))
            fail += 1
            db.rollback()

    print("TOTALS registered=%d duplicate=%d skipped=%d failed=%d"
          % (ok, dup, skip, fail))
    coverage = science.coverage(db, user_id)
    print("COVERAGE by_status=%s accepted=%d"
          % (coverage["by_status"], coverage["accepted_total"]))
    print("Nothing above is retrievable: science.search returns accepted "
          "records only, and acceptance is a human judgement.")
    db.close()
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
