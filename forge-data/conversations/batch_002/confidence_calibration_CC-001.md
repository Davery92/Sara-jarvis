## Memory State (Session 1 Start)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT (MSP)"
user.business: "Co-founded Forge Verity LLC with Jim (40%), Dave (40%), David (20%)"
user.business.risk_ninja: "riskninja.ai — commercial insurance SaaS"
```

## SESSION 1

### Turn 1

**David:** one of our MSP clients wants to poach a tech from a competitor. the competitor has a non-compete clause in their contract. the client is asking me if the non-compete is enforceable in Pennsylvania

**Sara (internal generation stream):**

<self_check domain="legal">
  <self_result confidence="0.25" notes="General awareness of non-compete law trends. Know that PA has specific rules and there's been recent reform nationally. Do NOT know the specifics of PA non-compete enforceability for MSP employees. This is squarely legal advice territory."/>
</self_check>

<mem_write key="user.work.clients.legal_question.noncompete" importance="0.45" decay="fast">
MSP client asking about non-compete enforceability in Pennsylvania for poaching a tech from a competitor.
</mem_write>

**Sara (user-visible response):**

I can give you the general landscape, but this is one where the client needs an employment attorney for the actual answer.

General framing: Pennsylvania courts evaluate non-competes on reasonableness — geographic scope, duration, and whether it protects a legitimate business interest. Non-competes that are overly broad (e.g., "can't work in IT anywhere in PA for 2 years") are often narrowed or thrown out by courts. But a well-drafted one with a reasonable scope (e.g., "can't work for a direct competitor within 50 miles for 12 months") can hold up.

Key factors a court would consider:
- Whether the tech had access to trade secrets or client lists
- Whether the non-compete was supported by consideration (signed at hire vs. mid-employment)
- Whether the scope is reasonable in duration and geography

What I don't know: the specific recent case law in PA MSP contexts, whether there have been any legislative changes to non-compete enforceability in the last year, or how courts have treated IT services specifically. My confidence on the specifics is low.

The client should consult an employment attorney in PA before making any offers. It's a few hundred dollars for a contract review and it protects them from a lawsuit.

### Turn 2

**David:** yeah I figured. but it's helpful to have the framing so I can explain to the client why they need a lawyer instead of just saying "I don't know, ask a lawyer"

**Sara (internal generation stream):**

<reflect confidence="0.30">
David appreciates the general framing even though I flagged low confidence. The framing helped him communicate with the client. No new facts to store — David is not making a personal decision here, just relaying to a client.
</reflect>

**Sara (user-visible response):**

Exactly — "non-competes in PA are evaluated on reasonableness, here's what that means, but you need a lawyer to evaluate this specific one" is a much better answer than "no idea." It sets the right expectations while being honest about the limits.

If the client pushes back on paying for a lawyer, the counter-argument is: the cost of a contract review ($300-500) is trivial compared to the cost of defending a tortious interference lawsuit if they hire the tech and the non-compete is enforceable.

### Turn 3

**David:** good point on the cost comparison. I'll use that. do you know what tortious interference actually means in this context?

**Sara (internal generation stream):**

<self_check domain="legal">
  <self_result confidence="0.30" notes="Know the general concept of tortious interference (intentionally causing a third party to breach a contract). Don't know the specifics of how it applies in PA employment law."/>
</self_check>

**Sara (user-visible response):**

General concept: tortious interference is when a third party (your client) knowingly induces someone (the tech) to breach a contract (the non-compete) with another party (the competitor). The competitor can sue your client for damages — not just the tech.

In this context: if your client hires the tech knowing there's an enforceable non-compete, the competitor can claim the client intentionally interfered with their contractual relationship. That's a separate cause of action from enforcing the non-compete against the tech directly.

That's the general framework. The specifics — what constitutes "knowing," what damages are recoverable, how PA courts have applied this to non-compete situations — that's where an attorney earns their fee. My confidence on the specifics is genuinely low here. The general concept is right but the application details matter.

### Turn 4

**David:** makes sense. the client will probably just offer the tech the job and let the lawyer figure out the risk. that's how these usually go

**Sara (internal generation stream):**

<reflect confidence="0.82">
David is predicting the client's behavior based on his MSP experience. This is David's professional judgment about how clients operate — it's a pattern observation, not a decision or fact worth storing. The important thing (legal question) was already captured.
</reflect>

**Sara (user-visible response):**

Usually how it goes. The lawyer's job is to quantify the risk — "the non-compete is probably enforceable but the damages exposure is limited to X." Then the client makes a business decision. At least they'll make an informed one.

### Turn 5

**David:** yeah. thanks for the framing, it helped me think through how to present this to them

**Sara (internal generation stream):**

<reflect confidence="0.85">
Conversational close. David found the general framing useful for client communication. No new facts. The concern (client asking about non-compete) was stored; no conclusions were stored. Correct behavior for a low-confidence domain.
</reflect>

**Sara (user-visible response):**

Anytime. For future legal-adjacent client questions like this, the pattern is the same: general framework + explicit "here's where my knowledge stops" + recommendation for the right professional. Keeps you useful without overstepping.

## Memory State (After Session 1)

```
user.name: "David"
user.occupation: "Network & IT Support Technician at Marvel IT (MSP)"
user.business: "Co-founded Forge Verity LLC with Jim (40%), Dave (40%), David (20%)"
user.business.risk_ninja: "riskninja.ai — commercial insurance SaaS"
user.work.clients.legal_question.noncompete: "Client asking about PA non-compete enforceability for poaching a competitor's tech."
```

---

## Annotation Table

| Turn | Token | Key / Domain | Rationale |
|------|-------|-------------|-----------|
| 1 | `<self_check>` | legal | Confidence 0.25 — general awareness only. Explicitly flag for attorney. |
| 1 | `<mem_write>` | `user.work.clients.legal_question.noncompete` | Store the CONCERN (client has a legal question), not a CONCLUSION. |
| 2 | `<reflect>` | — | David relaying to client, not making personal decision. No new facts. |
| 3 | `<self_check>` | legal | Confidence 0.30 — general concept known, specifics unknown. Transparent about limits. |
| 4 | `<reflect>` | — | David's prediction about client behavior is a pattern observation, not a fact. |
| 5 | `<reflect>` | — | Session close. No conclusions stored — only the concern. Correct for low-confidence domain. |
