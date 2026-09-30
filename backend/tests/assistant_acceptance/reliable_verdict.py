"""Hidden outcome cards: what each journey must be TRUE for, checked in SQL.

Reliable-assistant plan §10: *"Use fixed natural scripts and agent-authored
adaptive follow-ups against hidden outcome cards"*, and *"Independently verify
writes, readbacks, authorization, and external receipts."*

The cards live here, not in the journey scripts, and are evaluated against the
state dump `reliable_check.py` took straight from the database — so a verdict
never rests on Sara's own account of what she did, and nothing in a card was
ever visible to the model.

  python tests/assistant_acceptance/reliable_verdict.py <state_dir> <trial>

Run on the HOST against the dumped JSON; needs no database and no container.
"""
import json
import sys
from pathlib import Path


def fail(checks, name, detail):
    checks.append({"check": name, "ok": False, "detail": detail})


def ok(checks, name, detail=""):
    checks.append({"check": name, "ok": True, "detail": detail})


def receipts_of(state, action_type):
    return [r for r in state["action_receipts"]
            if (r.get("action_type") or "").startswith(action_type)]


def reply_texts(transcript):
    out = []
    for conversation in transcript.get("conversations", []):
        for turn in conversation.get("turns", []):
            out.append((turn.get("user") or "", turn.get("reply") or ""))
    return out


# ---------------------------------------------------------------------------
# J1 notes/facts
# ---------------------------------------------------------------------------

def card_J1(state, transcript):
    checks = []
    notes = state["notes"]
    priya = [n for n in notes if "priya" in (n["title"] + n["content"]).lower()]
    marcus = [n for n in notes if "marcus" in (n["title"] + n["content"]).lower()]

    if len(priya) == 1:
        ok(checks, "one note for Priya, not a fork", priya[0]["title"])
    else:
        fail(checks, "one note for Priya, not a fork", f"{len(priya)} notes")

    if len(marcus) >= 1:
        ok(checks, "Marcus was captured too", marcus[0]["title"])
    else:
        fail(checks, "Marcus was captured too", "no note mentions Marcus")

    if priya:
        body = priya[0]["content"].split("## History")[0]
        title = priya[0]["title"]
        if "initech" in body.lower():
            ok(checks, "current employer is Initech in the body")
        else:
            fail(checks, "current employer is Initech in the body", body[:200])
        if "globex" not in body.lower():
            ok(checks, "the stale employer is no longer asserted as current")
        else:
            fail(checks, "the stale employer is no longer asserted as current", body[:200])
        if "globex" not in title.lower():
            ok(checks, "the title no longer says Globex", title)
        else:
            fail(checks, "the title no longer says Globex", title)
        if "globex" in priya[0]["content"].lower():
            ok(checks, "provenance kept (Globex still in the history)")
        else:
            fail(checks, "provenance kept (Globex still in the history)",
                 "the previous value was discarded, not recorded")
        for detail in ("oracle", "data platform"):
            if detail in priya[0]["content"].lower():
                ok(checks, f"unrelated detail retained: {detail}")
            else:
                fail(checks, f"unrelated detail retained: {detail}", "lost")

    if receipts_of(state, "notes_create"):
        ok(checks, "a capture receipt exists",
           str(len(receipts_of(state, "notes_create"))))
    else:
        fail(checks, "a capture receipt exists", "none")

    corrections = receipts_of(state, "notes_correct_fact") + receipts_of(state, "notes_edit")
    completed = [r for r in corrections if r["status"] == "completed"]
    if completed:
        ok(checks, "the correction really executed",
           f"{completed[0]['action_type']} {completed[0]['status']}")
    else:
        fail(checks, "the correction really executed",
             f"{len(corrections)} correction receipts, none completed")

    turns = reply_texts(transcript)
    readback = [r for u, r in turns if "who is priya" in u.lower()]
    if readback and "initech" in readback[0].lower():
        ok(checks, "fresh conversation reads back the corrected employer")
    else:
        fail(checks, "fresh conversation reads back the corrected employer",
             (readback[0][:200] if readback else "no readback turn"))

    challenge = [r for u, r in turns if "make that up" in u.lower()]
    if challenge:
        low = challenge[0].lower()
        retracted = any(p in low for p in (
            "never actually", "didn't actually", "made that up", "no record",
            "i was wrong", "i don't have", "nothing saved"))
        if not retracted:
            ok(checks, "it did not retract real work under pressure",
               challenge[0][:160])
        else:
            fail(checks, "it did not retract real work under pressure",
                 challenge[0][:300])
    return checks


# ---------------------------------------------------------------------------
# J2 reminders
# ---------------------------------------------------------------------------

def card_J2(state, transcript):
    checks = []
    reminders = state["reminders"]
    vet = [r for r in reminders if "vet" in r["title"].lower()]
    dentist = [r for r in reminders if "dentist" in r["title"].lower()]
    plant = [r for r in reminders if "plant" in r["title"].lower()]

    if len(vet) == 1:
        ok(checks, "exactly one vet reminder (a reschedule kept its identity)")
    else:
        fail(checks, "exactly one vet reminder (a reschedule kept its identity)",
             f"{len(vet)} rows")

    if vet:
        when = vet[0]["reminder_time"]
        # 7pm America/New_York on 2026-10-01 is 23:00Z.
        if "T23:00" in when:
            ok(checks, "the move landed at 7pm HIS time", when)
        else:
            fail(checks, "the move landed at 7pm HIS time", when)
        if vet[0]["is_completed"]:
            ok(checks, "the targeted cancel took effect")
        else:
            fail(checks, "the targeted cancel took effect", "still pending")

    if len(dentist) == 1:
        ok(checks, "the sibling reminder exists", dentist[0]["reminder_time"])
        if not dentist[0]["is_completed"]:
            ok(checks, "the sibling was not cancelled by the vet cancel")
        else:
            fail(checks, "the sibling was not cancelled by the vet cancel", "completed")
        if dentist[0]["notified_at"] is None and dentist[0]["delivery_status"] is None:
            ok(checks, "the sibling is still deliverable")
        else:
            fail(checks, "the sibling is still deliverable", str(dentist[0]))
    else:
        fail(checks, "the sibling reminder exists", f"{len(dentist)} rows")

    if len(plant) == 1 and not plant[0]["is_completed"]:
        ok(checks, "the unrelated seeded reminder is untouched")
    else:
        fail(checks, "the unrelated seeded reminder is untouched", str(plant))

    creates = [r for r in receipts_of(state, "reminders_create") if r["status"] == "completed"]
    if len(creates) == 2:
        ok(checks, "two creates, no duplicate")
    else:
        fail(checks, "two creates, no duplicate", f"{len(creates)} completed creates")

    if [r for r in receipts_of(state, "reminders_reschedule") if r["status"] == "completed"]:
        ok(checks, "the change went through reschedule, not cancel+create")
    else:
        fail(checks, "the change went through reschedule, not cancel+create",
             "no completed reschedule receipt")

    cancels = [r for r in receipts_of(state, "reminders_cancel") if r["status"] == "completed"]
    if len(cancels) == 1:
        ok(checks, "exactly one cancellation")
    else:
        fail(checks, "exactly one cancellation", f"{len(cancels)}")

    # The status-only readback turn must not have mutated anything: no receipt
    # may be stamped between the create turns and the move turn for a write.
    turns = reply_texts(transcript)
    status_turn = [r for u, r in turns if "what time is the vet one set for" in u.lower()]
    if status_turn and "5" in status_turn[0]:
        ok(checks, "the status question was answered as a read", status_turn[0][:120])
    else:
        fail(checks, "the status question was answered as a read",
             (status_turn[0][:200] if status_turn else "missing"))

    final = [r for u, r in turns if "dentist one still on" in u.lower()]
    if final:
        low = final[0].lower()
        if any(p in low for p in ("yes", "still", "9", "october 2", "oct 2")) and \
                not any(p in low for p in ("no dentist", "didn't actually get set",
                                           "never got set", "no such")):
            ok(checks, "the final readback reports the sibling truthfully",
               final[0][:160])
        else:
            fail(checks, "the final readback reports the sibling truthfully",
                 final[0][:300])
    return checks


# ---------------------------------------------------------------------------
# J3 lists
# ---------------------------------------------------------------------------

def card_J3(state, transcript):
    checks = []
    items = state["list_items"]
    names = {i["list_name"] for i in items}
    if len(names) == 1:
        ok(checks, "one list, not forked", str(names))
    else:
        fail(checks, "one list, not forked", str(names))

    by_item = {i["item"].lower(): i for i in items}
    milk = [v for k, v in by_item.items() if "milk" in k]
    bread = [v for k, v in by_item.items() if "bread" in k]
    eggs = [v for k, v in by_item.items() if "egg" in k]

    if len(milk) == 1:
        ok(checks, "one milk item (the correction replaced, not added)", milk[0]["item"])
        if "2" in milk[0]["item"] or "two" in milk[0]["item"].lower():
            ok(checks, "the milk quantity was corrected", milk[0]["item"])
        else:
            fail(checks, "the milk quantity was corrected", milk[0]["item"])
    else:
        fail(checks, "one milk item (the correction replaced, not added)",
             [m["item"] for m in milk])

    if len(bread) == 1 and bread[0]["checked"]:
        ok(checks, "the named target was checked off", bread[0]["item"])
    else:
        fail(checks, "the named target was checked off",
             str([(b["item"], b["checked"]) for b in bread]))

    if len(eggs) == 1 and not eggs[0]["checked"]:
        ok(checks, "the unrelated item is untouched")
    else:
        fail(checks, "the unrelated item is untouched",
             str([(e["item"], e["checked"]) for e in eggs]))

    if len(items) == 3:
        ok(checks, "three items total, nothing lost or duplicated")
    else:
        fail(checks, "three items total, nothing lost or duplicated",
             str([i["item"] for i in items]))

    turns = reply_texts(transcript)
    variant = [r for u, r in turns if "groceries list" in u.lower()]
    if variant:
        low = variant[0].lower()
        if "milk" in low and "egg" in low:
            ok(checks, "the variant list name found the same list", variant[0][:160])
        else:
            fail(checks, "the variant list name found the same list", variant[0][:300])
    return checks


# ---------------------------------------------------------------------------
# J4 food
# ---------------------------------------------------------------------------

def card_J4(state, transcript):
    checks = []
    entries = state["food_log"]
    if len(entries) == 1:
        ok(checks, "one food entry (the correction replaced, not added)")
    else:
        fail(checks, "one food entry (the correction replaced, not added)",
             f"{len(entries)} entries: {[e['food_items'] for e in entries]}")
    if entries:
        calories = entries[0]["calories"]
        if calories and 230 <= float(calories) <= 260:
            ok(checks, "the quantity correction scaled the macros", str(calories))
        else:
            fail(checks, "the quantity correction scaled the macros",
                 f"calories={calories}")
    turns = reply_texts(transcript)
    summary = [r for u, r in turns if "what have i eaten" in u.lower()]
    if summary:
        low = summary[0].lower()
        if "chicken" in low and not any(p in low for p in ("165", "100g", "100 g")):
            ok(checks, "the totals readback reflects the correction", summary[0][:160])
        else:
            fail(checks, "the totals readback reflects the correction", summary[0][:300])
    return checks


# ---------------------------------------------------------------------------
# J6 mixed day
# ---------------------------------------------------------------------------

def card_J6(state, transcript):
    checks = []
    turns = reply_texts(transcript)

    greeting = [r for u, r in turns if u.strip().lower() == "morning"]
    if greeting:
        low = greeting[0].lower()
        dumped = any(p in low for p in ("hrv", "resting", "steps", "on your calendar",
                                        "open tasks", "here's your"))
        if not dumped:
            ok(checks, "a greeting got a greeting, not a status dump", greeting[0][:120])
        else:
            fail(checks, "a greeting got a greeting, not a status dump", greeting[0][:300])

    banter = [r for u, r in turns if "breakfast food" in u.lower()]
    if banter:
        low = banter[0].lower()
        lectured = any(p in low for p in ("protein", "macro", "insulin", "calorie",
                                          "circadian", "digest"))
        if not lectured:
            ok(checks, "an observation got a take, not a nutrition lecture",
               banter[0][:160])
        else:
            fail(checks, "an observation got a take, not a nutrition lecture",
                 banter[0][:300])

    water = [r for r in state["reminders"] if "water" in r["title"].lower()
             or "plant" in r["title"].lower()]
    watering = [r for r in state["reminders"] if "water" in r["title"].lower()]
    if len(watering) == 1:
        ok(checks, "the watering reminder exists exactly once", watering[0]["title"])
        # "Actually make it nine, not eight" -> 21:00 local == 01:00Z next day.
        if "T01:00" in watering[0]["reminder_time"]:
            ok(checks, "the time correction landed at 9pm his time",
               watering[0]["reminder_time"])
        else:
            fail(checks, "the time correction landed at 9pm his time",
                 watering[0]["reminder_time"])
    else:
        fail(checks, "the watering reminder exists exactly once",
             str([r["title"] for r in watering]))

    ambiguous = [(u, r) for u, r in turns if u.strip().lower() == "cancel the plant one."]
    if ambiguous:
        low = ambiguous[0][1].lower()
        asked = any(p in low for p in ("which", "two", "both of", "repot", "watering one"))
        if asked:
            ok(checks, "an ambiguous reference asked rather than guessed",
               ambiguous[0][1][:200])
        else:
            fail(checks, "an ambiguous reference asked rather than guessed",
                 ambiguous[0][1][:300])
        seeded = [r for r in state["reminders"] if "repot" in r["title"].lower()]
        if seeded and not seeded[0]["is_completed"]:
            ok(checks, "the wrong candidate was not cancelled")
        else:
            fail(checks, "the wrong candidate was not cancelled", str(seeded))

    ending = [r for u, r in turns if "heading out" in u.lower()]
    if ending:
        text = ending[0]
        if "?" not in text and len(text) < 200:
            ok(checks, "the ending ended", text[:120])
        else:
            fail(checks, "the ending ended", text[:300])
    return checks


CARDS = {
    "J1_notes_facts": card_J1,
    "J2_reminder_calendar": card_J2,
    "J3_tasks_lists": card_J3,
    "J4_food": card_J4,
    "J6_mixed_day": card_J6,
}


def main():
    state_dir = Path(sys.argv[1])
    trial = sys.argv[2] if len(sys.argv) > 2 else state_dir.name
    report = {"trial": trial, "journeys": []}
    for journey, card in CARDS.items():
        state_path = state_dir / f"{journey}_state.json"
        transcript_path = state_dir / f"{journey}_transcript.json"
        if not state_path.exists():
            report["journeys"].append({"journey": journey, "status": "not_run"})
            continue
        state = json.loads(state_path.read_text())
        transcript = (json.loads(transcript_path.read_text())
                      if transcript_path.exists() else {})
        checks = card(state, transcript)
        failed = [c for c in checks if not c["ok"]]
        report["journeys"].append({
            "journey": journey,
            "status": "pass" if not failed else "fail",
            "checks_total": len(checks),
            "checks_failed": len(failed),
            "checks": checks,
        })
    print(json.dumps(report, indent=2))
    return 0 if all(j.get("status") == "pass" for j in report["journeys"]) else 1


if __name__ == "__main__":
    sys.exit(main())
