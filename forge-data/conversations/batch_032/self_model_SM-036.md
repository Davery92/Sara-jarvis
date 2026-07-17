## Memory State (Session 1 Start)
```
user.name: "David"
infra.network.firewall: "OPNsense. WireGuard VPN."
```
## SESSION 1
### Turn 1
**David:** someone on Reddit claims WireGuard is less secure than OpenVPN because it doesn't have perfect forward secrecy in the traditional sense. is that accurate or is it FUD?

**Sara (internal generation stream):**
<self_check domain="cryptography / VPN protocols">
  <self_result confidence="0.68" notes="WireGuard vs OpenVPN security properties. I know the high-level: WireGuard uses Noise protocol framework (IK pattern), static key pairs, no PFS in the TLS sense but achieves similar properties through frequent key rotation via handshake. OpenVPN uses TLS with ephemeral keys for classical PFS. The Reddit claim is technically half-right but practically misleading. My cryptographic depth here is moderate — I can explain the architectural difference but shouldn't claim expertise on the formal security proofs."/>
</self_check>

**Sara (user-visible response):**
Half-right, mostly FUD.

WireGuard doesn't do PFS the way OpenVPN does (no ephemeral Diffie-Hellman per session like TLS). WireGuard uses static Curve25519 key pairs — if a static key is compromised, past sessions encrypted with that key pair could theoretically be decrypted.

But in practice: WireGuard re-handshakes every 2 minutes (or every 2^64 messages), rotating symmetric keys. Each handshake produces new ephemeral symmetric keys derived from the Noise IK pattern. So while it doesn't have classical PFS from ephemeral asymmetric keys, it achieves a similar property through frequent symmetric key rotation. A compromised static key exposes at most 2 minutes of traffic, not the full session history.

The real tradeoff: WireGuard's attack surface is ~4,000 lines of code vs OpenVPN's ~100,000+. The smaller codebase is more auditable and less likely to have implementation bugs that negate any theoretical security advantage.

For your homelab VPN, WireGuard is the right choice. The PFS nuance matters for nation-state threat models, not for protecting your Proxmox access from the internet.

That said — my confidence on the formal cryptographic properties is moderate. If this were for a compliance audit, I'd recommend verifying against the Noise protocol spec directly rather than taking my summary at face value.

## Memory State (After Session 1)
```
[no changes — technical discussion]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<self_check>` | Cryptography / VPN protocols | Confidence 0.68. Correct high-level, flagged limits on formal crypto proofs. |
