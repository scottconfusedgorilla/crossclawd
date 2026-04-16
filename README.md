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

**v0.2 — functional exporter.** Auto-discovers Claude Code JSONL transcripts, parses them (ccc-ninja compatible), generates structured catdef v1.3 index AND verbatim markdown transcript, bundles both. Successfully exports a month of conversations (19K messages, 256 MB raw) to a single 1.5 MB portable bundle.

Relay is specified ([ARCHITECTURE.md](ARCHITECTURE.md)) but not yet deployed — run `wrangler dev` for local testing.

### Quick start

```bash
# List available Claude sessions
python exporter/export_conversation.py --list

# Export latest session of a project
python exporter/export_conversation.py --project thingalog --out session.opencatalog

# Export a specific session file
python exporter/export_conversation.py --jsonl ~/.claude/projects/.../xxx.jsonl --out session.opencatalog

# (Eventually) encrypt + upload to the relay for cross-machine pickup
python exporter/export_conversation.py --upload
```

## Sister project

**ccc-ninja** (Claude Code Copier Ninja) — VS Code extension that turned this whole thing real. Parses the same JSONL files into beautiful markdown for email/chat/docs. CrossClawd incorporates a Python port of its parser so the two produce identical transcripts.

## License

MIT.
