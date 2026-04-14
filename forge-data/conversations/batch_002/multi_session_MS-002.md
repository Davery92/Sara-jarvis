## Memory State (Session 1 Start)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai, Stripe billing"
project.risk_ninja.billing: "Stripe integration for agency subscriptions"
project.risk_ninja.billing.webhooks: "Using Stripe webhooks for subscription lifecycle events"
```

## SESSION 1

### Turn 1

**David:** Stripe webhook for payment_intent.succeeded is intermittently failing. about 5% of the time the webhook fires but our handler returns 500. can't figure out why

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.billing.webhook_issue" importance="0.70" decay="fast">
Stripe payment_intent.succeeded webhook intermittently failing. ~5% of webhook calls return 500 from Risk Ninja handler. Root cause unknown.
</mem_write>

**Sara (user-visible response):**

5% intermittent 500s on a webhook handler — most likely culprits:

1. **Database connection pool exhaustion** — if the handler does a DB write and the pool is full, it'll timeout and 500
2. **Race condition with concurrent webhooks** — Stripe sends multiple events for the same payment (payment_intent.succeeded AND charge.succeeded). If they arrive simultaneously and both try to update the same record, you get a conflict
3. **Request body parsing timeout** — if the handler is slow to read the body and Stripe's retry hits before it completes

Check your error logs around the 500 timestamps. Is it always a specific error or are they varied?

### Turn 2

**David:** it's a database integrity error. duplicate key on the payment record insert. so yeah, it's the race condition — both payment_intent.succeeded and charge.succeeded are trying to create the same payment record

**Sara (internal generation stream):**

<mem_update key="project.risk_ninja.billing.webhook_issue">
Stripe webhook 500s caused by race condition: payment_intent.succeeded and charge.succeeded both trying to insert the same payment record. Database duplicate key integrity error.
</mem_update>

**Sara (user-visible response):**

Classic Stripe webhook race. Two options:

1. **Idempotency key** — before inserting, check if a record with that payment_intent ID already exists. If it does, return 200 immediately. This is the standard approach.
2. **Ignore charge.succeeded entirely** — if you're already handling payment_intent.succeeded, you don't need charge.succeeded. Unsubscribe from it in your Stripe webhook settings.

Option 1 is more robust because it handles retries too (Stripe retries on 500, which means you'll get the same event again). Option 2 reduces the event volume but you still need idempotency for retries.

Do both: unsubscribe from charge.succeeded AND add the idempotency check.

### Turn 3

**David:** going with both. removing charge.succeeded from the webhook config and adding an upsert instead of insert for the payment record. if the record exists, update it instead of failing

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.billing.webhook_fix" importance="0.65" decay="medium">
Webhook fix: removed charge.succeeded from Stripe webhook config (only payment_intent.succeeded needed). Changed payment record insert to upsert for idempotency — if record exists, update instead of duplicate key error.
</mem_write>

**Sara (user-visible response):**

Upsert is the right pattern for webhook handlers — idempotent by design. Make sure the upsert key is the Stripe payment_intent ID, not an auto-generated primary key. That way the same event processed twice results in one record.

## Memory State (After Session 1)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai, Stripe billing"
project.risk_ninja.billing: "Stripe integration for agency subscriptions"
project.risk_ninja.billing.webhooks: "Using Stripe webhooks for subscription lifecycle events"
project.risk_ninja.billing.webhook_issue: "Race condition between payment_intent.succeeded and charge.succeeded causing duplicate key errors."
project.risk_ninja.billing.webhook_fix: "Removed charge.succeeded, added upsert by payment_intent ID for idempotency."
```

---

*Time gap: 3 days*

---

## Memory State (Session 2 Start)

```
[same as After Session 1]
```

## SESSION 2

### Turn 1

**David:** hey

**Sara (internal generation stream):**

<mem_read key="project.risk_ninja.billing.webhook_issue">
  <mem_result>Race condition between payment_intent.succeeded and charge.succeeded causing duplicate key errors.</mem_result>
</mem_read>

<mem_read key="project.risk_ninja.billing.webhook_fix">
  <mem_result>Removed charge.succeeded, added upsert by payment_intent ID.</mem_result>
</mem_read>

<reflect confidence="0.78">
David cold-opens with "hey" after 3 days. I have several open threads in memory — the webhook fix is the most recent. But I shouldn't assume that's what he wants to talk about. I'll offer something useful without forcing a topic. Lead with substance, not a question.
</reflect>

**Sara (user-visible response):**

Hey. The webhook fix been holding up?

### Turn 2

**David:** yeah actually, zero 500s since the deploy. that's what I was going to tell you. the upsert pattern worked perfectly

**Sara (internal generation stream):**

<mem_update key="project.risk_ninja.billing.webhook_issue">
RESOLVED. Stripe webhook 500s eliminated after removing charge.succeeded subscription and adding upsert pattern. Zero failures since deploy (3+ days).
</mem_update>

**Sara (user-visible response):**

Zero 500s over 3 days — that's a clean fix. The upsert handles both the race condition and any retry scenarios. You shouldn't have to touch that handler again unless you change the payment flow.

### Turn 3

**David:** yeah it's buttoned up. moving on — I need to add proration handling for mid-cycle plan upgrades. right now if an agency upgrades from basic to pro mid-month, they get double-charged for the overlap

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.billing.proration_issue" importance="0.65" decay="medium">
Risk Ninja billing issue: mid-cycle plan upgrades (basic → pro) cause double-charging for the overlap period. No proration handling implemented yet.
</mem_write>

**Sara (user-visible response):**

Stripe handles proration natively if you use their subscription update API with `proration_behavior: 'create_prorations'`. When you update the subscription's price, Stripe automatically calculates the credit for the unused basic period and charges the prorated pro amount for the remaining days.

The key is using `Subscription.modify()` instead of canceling and recreating. Are you currently canceling the old subscription and creating a new one?

### Turn 4

**David:** ...yeah. that's exactly what I'm doing. cancel and recreate

**Sara (internal generation stream):**

<mem_write key="project.risk_ninja.billing.upgrade_flow" importance="0.60" decay="medium">
Current Risk Ninja plan upgrade flow: cancel old subscription + create new one. Should be using Stripe Subscription.modify() with proration for seamless mid-cycle upgrades.
</mem_write>

**Sara (user-visible response):**

That's the problem. Cancel + recreate bypasses Stripe's proration engine entirely. Switch to `Subscription.modify()` — update the price ID on the existing subscription. Stripe handles the proration math, generates an invoice line item for the credit/charge difference, and the customer sees one clean transaction instead of a refund + charge.

The migration is small: replace the cancel-and-create logic with a single `stripe.Subscription.modify(sub_id, items=[{id: item_id, price: new_price_id}], proration_behavior='create_prorations')` call.

### Turn 5

**David:** that's way cleaner. I'll refactor the upgrade endpoint tomorrow

**Sara (internal generation stream):**

<reflect confidence="0.85">
David committing to the refactor. The key fact (switch from cancel/create to modify with proration) is already captured. "Tomorrow" is a loose timeframe — not worth a separate memory entry. The upgrade flow memory has the important context.
</reflect>

**Sara (user-visible response):**

One thing to test: make sure your webhook handler for `invoice.paid` handles proration line items. They look different from regular subscription charges — the line item amount can be negative (credit) or have a different period. Your payment recording logic might need to handle that.

## Memory State (After Session 2)

```
user.name: "David"
user.projects.risk_ninja: "Commercial insurance SaaS — riskninja.ai, Stripe billing"
project.risk_ninja.billing: "Stripe integration for agency subscriptions"
project.risk_ninja.billing.webhooks: "Stripe webhooks with upsert idempotency pattern."
project.risk_ninja.billing.webhook_issue: "RESOLVED. Zero 500s after fix."
project.risk_ninja.billing.webhook_fix: "Removed charge.succeeded, added upsert by payment_intent ID."
project.risk_ninja.billing.proration_issue: "Mid-cycle upgrades cause double-charging. No proration handling."
project.risk_ninja.billing.upgrade_flow: "Currently cancel+create (wrong). Switching to Subscription.modify() with proration."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| S1T1 | `<mem_write>` | `project.risk_ninja.billing.webhook_issue` | Active bug with specific symptoms. Worth tracking. |
| S1T2 | `<mem_update>` | `project.risk_ninja.billing.webhook_issue` | Root cause identified. Update existing key. |
| S1T3 | `<mem_write>` | `project.risk_ninja.billing.webhook_fix` | Fix decision: remove event + add upsert. |
| S2T1 | `<mem_read>` | `project.risk_ninja.billing.webhook_*` | Cold open "hey" — read recent threads to surface relevant context naturally. |
| S2T1 | `<reflect>` | — | Don't force a topic on cold open. Offer something useful. |
| S2T2 | `<mem_update>` | `project.risk_ninja.billing.webhook_issue` | Fix confirmed working. Mark resolved. |
| S2T3 | `<mem_write>` | `project.risk_ninja.billing.proration_issue` | New issue: double-charging on upgrades. |
| S2T4 | `<mem_write>` | `project.risk_ninja.billing.upgrade_flow` | Current (broken) approach and the correct approach documented. |
| S2T5 | `<reflect>` | — | David committing to refactor. Timeline vague ("tomorrow"). Key facts already captured. |
