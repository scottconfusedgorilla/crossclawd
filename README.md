# CrossClawd

> Cross-machine Claude context. Encrypted context teleportation between Claude instances via 9-digit codes.

## The problem

Claude conversations are bound to specific machines/sessions. When you switch from laptop to desktop, the rich context goes dormant. Memory files capture *substance* but not the *living state* of an active session.

## The solution

Minimal encrypted relay for one-shot context handoff. No persistent storage. No accounts.

```
Claude A (laptop)                    crossclawd.com relay              Claude B (desktop)
─────────────────                    ──────────────────                 ──────────────────
  build .opencatalog
  encrypt with random key
  POST /context                ─────►  store ciphertext
                                       generate 9-digit code
                               ◄─────  return code + decryption key
  show: "Your code: 123-456-789"

                                                                          user types code
                                                                     ◄──  GET /context/123-456-789
                                       return ciphertext
                                       mark consumed
                                                                          decrypt with key
                                                                          import .opencatalog
                                                                          continue where left off
```

## Key properties

- **Encrypted in transit and at rest** — relay never sees plaintext
- **One-shot pickup** — code consumed on first retrieval
- **Short TTL** — 60 minutes default, configurable
- **No accounts** — entirely stateless for users
- **Sister to sncro** — same relay pattern, different payload (sncro: live DOM, crossclawd: session snapshots)

## Payload format

The ciphertext wraps a `.opencatalog` CATIO bundle (see [catdef.org](https://catdef.org)). Each conversation becomes a catalog of **Exchange** items with Topic/Importance subcats. Fully portable, AI-readable, human-readable.

## Repo contents

| Path | Description |
|------|-------------|
| [exporter/](exporter/) | Python tool that builds `.opencatalog` from a conversation | 
| [relay/](relay/) | Cloudflare Worker that relays encrypted contexts |
| [client/](client/) | CLI for pick-up on the receiving machine |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Full design doc |

## Inspiration

- [sncro](https://sncro.net) — live browser debugging via relay. Same architecture, different payload.
- [ClawdForms](https://thingalog.com) — PDFs + Claude = catdef templates.
- [catdef](https://catdef.org) — the open standard for catalog definitions.

## Status

**v0.1 — proof-of-concept.** The exporter works end-to-end. The relay is specified but not yet deployed.

## License

MIT.
