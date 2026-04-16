# CrossClawd Architecture

## Design principles

1. **Minimal** — it's a relay, not a database. No user accounts, no permanent storage, no search, no UI beyond a 9-digit code.
2. **Encrypted end-to-end** — the relay handles only ciphertext. Compromise of the relay server reveals nothing.
3. **One-shot** — codes are consumed on pickup. No replay.
4. **Short TTL** — 60 minutes default. Enough to switch machines; not enough to accumulate risk.
5. **Stateless from the client's perspective** — no signup, no login, no config. Run the CLI, type the code, done.

## Flow

### Export (Claude A)

```
1. Build .opencatalog from conversation context
   └─ Catdef v1.3 with Exchange items + Topic/Importance subcats
2. Generate random 256-bit symmetric key (AES-GCM)
3. Encrypt .opencatalog bundle with key
4. POST /context HTTP/1.1
   Content-Type: application/octet-stream
   X-TTL-Seconds: 3600
   Body: <ciphertext>
5. Receive response: {code: "123456789", key: "<hex>"}
6. Display to user: "Your context code is 123-456-789"
7. Scott's UX: the key is embedded in the code via a URL like:
   crossclawd.com/pickup/123-456-789#<base64-key>
   (fragment is NEVER sent to the server)
```

### Pickup (Claude B)

```
1. User provides the 9-digit code (or the full pickup URL with fragment)
2. GET /context/123-456-789 HTTP/1.1
3. Response: {ciphertext: "<base64>"}
   Server deletes the record immediately (or marks consumed)
4. Decrypt locally with the key (from URL fragment or separate input)
5. Import .opencatalog into Claude's context
6. User continues conversation with full prior context
```

## Relay API

Minimal Cloudflare Worker with KV storage for ciphertext + TTL.

### `POST /context`

Request:
- Body: raw ciphertext (up to ~1MB — should be plenty for even long conversation catalogs)
- Headers: `X-TTL-Seconds` (optional, default 3600, max 86400)

Response:
```json
{
  "code": "123456789",
  "display_code": "123-456-789",
  "pickup_url": "https://crossclawd.com/pickup/123-456-789",
  "expires_at": "2026-04-16T09:00:00Z"
}
```

The **decryption key is NOT returned by the server** — the client generates it locally and never sends it. The client assembles the URL by appending `#<key>` on their own.

### `GET /context/{code}`

Response:
- 200 OK: raw ciphertext body. Record is consumed.
- 404 Not Found: code invalid, expired, or already consumed.
- 429 Too Many Requests: rate limit exceeded.

### `GET /pickup/{code}` (browser-friendly page)

Returns an HTML page that:
- Reads the URL fragment (`#<key>`) client-side
- Fetches `/context/{code}` to retrieve ciphertext
- Decrypts in-browser
- Displays the decrypted `.opencatalog` or offers to download it
- Never transmits the key

## Encryption

- AES-256-GCM with random IV per message
- Key generated client-side (Web Crypto API or Python `cryptography`)
- Nonce/IV prepended to ciphertext
- Authenticated encryption — tampering detected on decrypt

## Storage

- Cloudflare KV with TTL
- Key: the 9-digit code
- Value: ciphertext bytes
- Delete on pickup OR on TTL expiry, whichever first
- Rate limits: 10 POSTs per IP per hour, 100 GETs per IP per hour

## Security considerations

- **The URL fragment is sacred.** A pickup URL without the fragment is useless. Never log fragments server-side. Never transmit them. Clients should treat them as secrets equivalent to API keys.
- **Code entropy.** 9 decimal digits = ~30 bits. Combined with 60-minute TTL and rate limiting, brute-force is infeasible but not impossible. For extra safety, allow optional 12-digit codes for high-sensitivity contexts.
- **Relay compromise doesn't leak content.** Without the client-side key, the ciphertext is inert.
- **No audit trail of conversation content.** By design — the relay only knows "a blob was stored" and "a blob was retrieved."

## Why this is sister to sncro

Same architecture:
- Relay server (Cloudflare)
- 9-digit code pairing
- Ephemeral by design
- Encrypted where possible

Different payload:
- sncro: live browser state (DOM, console, network) streaming in real time
- crossclawd: one-shot conversation context snapshot

Shared infrastructure could be reused: the relay pattern, the 9-digit code scheme, the ephemeral storage layer.

## Future

- MCP server that exposes `/context` as a tool — AI can trigger context handoff natively
- Chrome extension for "one-click export from claude.ai"
- Encrypted persistence: optional "my-conversations" catalog backed by personal Thingalog instance (not relay) — for long-term history rather than handoff
- Multi-recipient codes (share with a collaborator's Claude, not just your other machine)
