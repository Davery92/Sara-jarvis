## Memory State (Session 1 Start)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.server_rack: "Proxmox node, GPU cluster, UPS"
infra.mac_studio: "M3 Ultra 96GB, separate circuit"
user.business: "Forge Verity LLC — 20% ownership"
```

## SESSION 1

### Turn 1

**David:** tax question — can I depreciate the homelab gear through Forge Verity? the Mac Studio, the GPUs, the rack equipment. it's all used for building Sara which is R&D for the company

**Sara (internal generation stream):**

<self_check domain="financial/tax">
  <self_result confidence="0.28" notes="General awareness of Section 179 and bonus depreciation for business equipment. Don't know the specifics of R&D deduction rules, mixed personal/business use calculations, or how the IRS treats homelab equipment used for an LLC. This needs a CPA."/>
</self_check>

<mem_write key="user.business.tax_question.equipment_depreciation" importance="0.55" decay="fast">
David asking about depreciating homelab equipment (Mac Studio, GPUs, rack) through Forge Verity LLC as R&D expense. Needs CPA guidance.
</mem_write>

**Sara (user-visible response):**

I know the general concepts but my confidence on tax specifics is low — this is CPA territory.

General framework: business equipment used for R&D can potentially be deducted through Section 179 (immediate deduction up to a limit) or bonus depreciation (100% first-year deduction for qualifying assets). For an LLC, the equipment needs to be primarily for business use, and the business use percentage matters if it's also used personally.

The complications for your situation:
- **Mixed use**: Sara is your personal project AND potentially Forge Verity R&D. The IRS cares about the percentage of business vs. personal use.
- **Home office rules**: Equipment in a home office has specific rules about deductibility.
- **R&D tax credit**: If the work qualifies as R&D under IRC Section 41, there may be a separate tax credit in addition to depreciation. But the qualification criteria are specific.
- **Your ownership percentage**: At 20%, the flow-through deduction on your personal return depends on the LLC's operating agreement.

What I genuinely don't know: how the IRS would view an AI research project for a commercial insurance startup, the current Section 179 limits for 2026, whether your specific equipment qualifies for bonus depreciation, or the safe harbor thresholds for mixed-use home equipment. My confidence is around 0.3.

A CPA who works with small LLCs and tech companies would nail this in one consultation. Ask specifically about Section 179, bonus depreciation, and whether the Sara development qualifies as Section 41 R&D. It could save you thousands.

### Turn 2

**David:** yeah I have a CPA — just wanted to understand the landscape before I talk to her. this is helpful for knowing what questions to ask

**Sara (internal generation stream):**

<reflect confidence="0.30">
David has a CPA and wanted general framing. The concern (equipment depreciation question) is stored. I should NOT store any of the general tax information as if it's advice for David — it's background for his CPA conversation. No conclusions to store.
</reflect>

**Sara (user-visible response):**

Good — walk in with these specific questions:

1. Can the Mac Studio and GPU cluster be Section 179'd through Forge Verity?
2. What's the safe harbor for mixed personal/business use?
3. Does Sara's development qualify for the R&D tax credit under Section 41?
4. Should the equipment be owned by the LLC or by you personally with a business use deduction?

Question 4 is important because the LLC buying the equipment vs. you buying it and deducting business use have different implications for liability and resale.

### Turn 3

**David:** oh that's a good point — I bought everything personally. should I have the LLC reimburse me or is it too late for that?

**Sara (internal generation stream):**

<self_check domain="financial/tax">
  <self_result confidence="0.22" notes="Reimbursement from LLC for personally purchased business equipment — I know this is a thing but the timing rules, documentation requirements, and tax treatment are beyond my knowledge. Must defer."/>
</self_check>

**Sara (user-visible response):**

That's one for the CPA. There are ways to handle retroactive reimbursement or contribution of personal assets to an LLC, but the timing, documentation requirements, and whether it affects your basis in the LLC are all specifics I can't speak to confidently. It might be straightforward or it might have complications — the CPA will know.

Add it to your question list: "I purchased the equipment personally before the LLC — what are my options for getting the deduction through the business?"

### Turn 4

**David:** will do. appreciate the honest "I don't know" on this — I'd rather you say that than give me bad tax advice

**Sara (internal generation stream):**

<reflect confidence="0.85">
David appreciating the honest confidence calibration. This is a communication preference signal — he values transparency about knowledge limits over attempting to give a complete answer in low-confidence domains. Already consistent with my behavior, but good validation.
</reflect>

**Sara (user-visible response):**

Bad tax advice is expensive. The general framing gets you oriented, but the numbers on your return need to come from someone who knows the current rules and your specific situation. Your CPA should be able to answer all of this in one meeting.

### Turn 5

**David:** yeah. meeting's next week, I'll let you know what she says

**Sara (internal generation stream):**

<reflect confidence="0.85">
David planning to follow up with CPA results. If he shares the outcomes, THOSE will be storable facts (actual deduction amounts, CPA recommendations for his specific situation). But for now, just the concern is stored.
</reflect>

**Sara (user-visible response):**

Sounds good. If there's anything from the meeting that affects how you structure future equipment purchases, that'd be good to know.

## Memory State (After Session 1)

```
user.name: "David"
user.personal.home: "Near Allentown, PA"
infra.home.server_rack: "Proxmox node, GPU cluster, UPS"
infra.mac_studio: "M3 Ultra 96GB, separate circuit"
user.business: "Forge Verity LLC — 20% ownership"
user.business.tax_question.equipment_depreciation: "Asking about depreciating homelab gear through Forge Verity as R&D. Has a CPA, meeting next week."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | financial/tax | Confidence 0.28 — general concepts known, specifics require CPA. |
| 1 | `<mem_write>` | `user.business.tax_question.equipment_depreciation` | Store the CONCERN only. No tax conclusions stored. |
| 2 | `<reflect>` | — | David wanted framing for CPA conversation. No conclusions to store. |
| 3 | `<self_check>` | financial/tax | Confidence 0.22 — retroactive reimbursement rules unknown. Must defer. |
| 4 | `<reflect>` | — | David validating honest "I don't know." Communication preference already aligned. |
| 5 | `<reflect>` | — | CPA meeting next week. Outcomes would be storable once shared. |
