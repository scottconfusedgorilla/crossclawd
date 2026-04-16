/**
 * CrossClawd relay — Cloudflare Worker.
 *
 * Accepts encrypted conversation bundles, stores with TTL, returns a 9-digit pickup code.
 * On pickup: returns ciphertext, deletes the record.
 *
 * The relay NEVER sees plaintext. Keys are client-side only.
 *
 * Endpoints:
 *   POST /context                       - store, returns {code, display_code, pickup_url, expires_at}
 *   GET  /context/{code}                - retrieve + consume (returns raw ciphertext)
 *   GET  /pickup/{code}                 - browser-friendly page (reads #key from fragment)
 *   GET  /                              - landing page
 */

export interface Env {
  KV: KVNamespace;  // Bound to a KV namespace in wrangler.toml
}

const MAX_BODY_SIZE = 2 * 1024 * 1024;  // 2 MB
const DEFAULT_TTL = 3600;                 // 60 min
const MAX_TTL = 86400;                    // 24 hours
const MIN_TTL = 60;                       // 1 minute

// ── Code generation ─────────────────────────────────────────────
function generateCode(): string {
  // 9 decimal digits, zero-padded
  const crypto_ = globalThis.crypto;
  const buf = new Uint32Array(1);
  crypto_.getRandomValues(buf);
  return String(buf[0] % 1_000_000_000).padStart(9, "0");
}

function formatDisplay(code: string): string {
  return `${code.slice(0, 3)}-${code.slice(3, 6)}-${code.slice(6)}`;
}

function normalizeCode(input: string): string {
  return input.replace(/[-\s]/g, "");
}

// ── Handlers ────────────────────────────────────────────────────

async function handleStore(request: Request, env: Env): Promise<Response> {
  const contentLength = parseInt(request.headers.get("content-length") || "0");
  if (contentLength > MAX_BODY_SIZE) {
    return json({ error: "payload too large" }, 413);
  }

  const ciphertext = new Uint8Array(await request.arrayBuffer());
  if (ciphertext.length === 0) {
    return json({ error: "empty body" }, 400);
  }
  if (ciphertext.length > MAX_BODY_SIZE) {
    return json({ error: "payload too large" }, 413);
  }

  let ttl = parseInt(request.headers.get("X-TTL-Seconds") || String(DEFAULT_TTL));
  if (isNaN(ttl) || ttl < MIN_TTL) ttl = DEFAULT_TTL;
  if (ttl > MAX_TTL) ttl = MAX_TTL;

  // Generate code, retry on collision (rare but possible)
  let code = "";
  for (let attempt = 0; attempt < 5; attempt++) {
    code = generateCode();
    const existing = await env.KV.get(code, { type: "arrayBuffer" });
    if (!existing) break;
  }

  await env.KV.put(code, ciphertext.buffer, { expirationTtl: ttl });

  const expiresAt = new Date(Date.now() + ttl * 1000).toISOString();
  const pickupUrl = `${new URL(request.url).origin}/pickup/${code}`;

  return json({
    code,
    display_code: formatDisplay(code),
    pickup_url: pickupUrl,
    expires_at: expiresAt,
    ttl_seconds: ttl,
    bytes_stored: ciphertext.length,
  });
}

async function handleRetrieve(code: string, env: Env): Promise<Response> {
  const normalized = normalizeCode(code);
  if (!/^\d{9}$/.test(normalized)) {
    return json({ error: "invalid code format" }, 400);
  }

  const ciphertext = await env.KV.get(normalized, { type: "arrayBuffer" });
  if (!ciphertext) {
    return json({ error: "not found or expired" }, 404);
  }

  // Consume: delete immediately so code is one-shot
  await env.KV.delete(normalized);

  return new Response(ciphertext, {
    status: 200,
    headers: {
      "Content-Type": "application/octet-stream",
      "Cache-Control": "no-store",
    },
  });
}

function pickupPage(code: string): Response {
  const display = /^\d{9}$/.test(code) ? formatDisplay(code) : code;
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CrossClawd pickup ${display}</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; background: #0d1117; color: #e6edf3; max-width: 640px; margin: 4rem auto; padding: 2rem; }
  h1 { color: #58a6ff; }
  .code { font-family: monospace; font-size: 1.4rem; background: #161b22; padding: 0.8rem 1.2rem; border-radius: 6px; display: inline-block; }
  .status { margin: 1.5rem 0; padding: 1rem; border-radius: 6px; background: #161b22; }
  .error { background: #5c1e1e; }
  .success { background: #1e5c34; }
  button, a.button { display: inline-block; background: #58a6ff; color: #0d1117; padding: 0.6rem 1.2rem; border-radius: 6px; border: 0; cursor: pointer; font-weight: 600; text-decoration: none; margin-right: 0.5rem; }
  pre { background: #161b22; padding: 1rem; border-radius: 6px; overflow-x: auto; font-size: 0.85rem; }
</style>
</head>
<body>
<h1>CrossClawd pickup</h1>
<p>Code: <span class="code">${display}</span></p>
<div id="status" class="status">Checking URL fragment for decryption key...</div>
<div id="actions"></div>

<script>
(async () => {
  const statusEl = document.getElementById('status');
  const actions = document.getElementById('actions');
  const code = "${code}";
  const keyB64 = location.hash.slice(1);  // strip #

  if (!keyB64) {
    statusEl.className = "status error";
    statusEl.textContent = "Missing decryption key in URL fragment (#...). Without it, the ciphertext cannot be decrypted.";
    return;
  }

  statusEl.textContent = "Fetching ciphertext from relay...";
  let ciphertext;
  try {
    const resp = await fetch("/context/" + code);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({error: "unknown"}));
      throw new Error((err.error || resp.statusText) + " (HTTP " + resp.status + ")");
    }
    ciphertext = new Uint8Array(await resp.arrayBuffer());
  } catch (e) {
    statusEl.className = "status error";
    statusEl.textContent = "Fetch failed: " + e.message;
    return;
  }

  statusEl.textContent = "Decrypting " + ciphertext.length.toLocaleString() + " bytes...";

  try {
    // Decode base64-url key
    const pad = "=".repeat((4 - keyB64.length % 4) % 4);
    const keyBytes = Uint8Array.from(atob(keyB64.replace(/-/g, '+').replace(/_/g, '/') + pad), c => c.charCodeAt(0));
    if (keyBytes.length !== 32) throw new Error("key must be 32 bytes, got " + keyBytes.length);

    const key = await crypto.subtle.importKey("raw", keyBytes, "AES-GCM", false, ["decrypt"]);
    const iv = ciphertext.slice(0, 12);
    const ct = ciphertext.slice(12);
    const plaintext = await crypto.subtle.decrypt({name: "AES-GCM", iv}, key, ct);

    statusEl.className = "status success";
    statusEl.textContent = "Decrypted " + plaintext.byteLength.toLocaleString() + " bytes. Ready to download.";

    const blob = new Blob([plaintext], {type: "application/zip"});
    const url = URL.createObjectURL(blob);
    actions.innerHTML = '<a class="button" href="' + url + '" download="conversation.opencatalog">Download .opencatalog</a>';
  } catch (e) {
    statusEl.className = "status error";
    statusEl.textContent = "Decrypt failed: " + e.message + " (wrong key?)";
  }
})();
</script>
</body>
</html>`;
  return new Response(html, { headers: { "Content-Type": "text/html;charset=UTF-8" } });
}

function landingPage(): Response {
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CrossClawd — Cross-machine Claude context</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; background: #0d1117; color: #e6edf3; max-width: 720px; margin: 4rem auto; padding: 2rem; line-height: 1.6; }
  h1 { color: #58a6ff; font-size: 2.5rem; }
  h2 { color: #8b949e; font-size: 1rem; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 2rem; }
  code { background: #161b22; padding: 0.2em 0.4em; border-radius: 3px; font-size: 0.9em; }
  pre { background: #161b22; padding: 1rem; border-radius: 6px; overflow-x: auto; font-size: 0.85rem; }
  a { color: #58a6ff; }
</style>
</head>
<body>
<h1>CrossClawd</h1>
<p>Encrypted one-shot relay for cross-machine Claude context handoff.</p>

<h2>How it works</h2>
<ol>
  <li>Claude A builds an <code>.opencatalog</code> bundle of your current conversation</li>
  <li>Claude A encrypts it client-side with a random AES-256 key</li>
  <li>Claude A uploads the ciphertext to this relay</li>
  <li>You get a 9-digit code</li>
  <li>On your other machine, Claude B fetches + decrypts with the code</li>
  <li>Session context continues seamlessly</li>
</ol>

<h2>Properties</h2>
<ul>
  <li>End-to-end encrypted. Relay never sees plaintext.</li>
  <li>One-shot. Codes consumed on first pickup.</li>
  <li>Short-lived. 60-minute default TTL.</li>
  <li>No accounts. Stateless for users.</li>
</ul>

<h2>API</h2>
<pre>POST /context
  Content-Type: application/octet-stream
  X-TTL-Seconds: 3600
  Body: &lt;ciphertext&gt;

  → {code, display_code, pickup_url, expires_at}

GET /context/{code}
  → raw ciphertext (consumed on success)

GET /pickup/{code}#&lt;base64-key&gt;
  → browser page that decrypts client-side</pre>

<h2>Source</h2>
<p><a href="https://github.com/scottconfusedgorilla/crossclawd">github.com/scottconfusedgorilla/crossclawd</a></p>
</body>
</html>`;
  return new Response(html, { headers: { "Content-Type": "text/html;charset=UTF-8" } });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
  });
}

// ── Router ──────────────────────────────────────────────────────

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const { pathname } = url;

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, X-TTL-Seconds",
        },
      });
    }

    if (request.method === "POST" && pathname === "/context") {
      return handleStore(request, env);
    }

    if (request.method === "GET" && pathname.startsWith("/context/")) {
      const code = pathname.slice("/context/".length);
      return handleRetrieve(code, env);
    }

    if (request.method === "GET" && pathname.startsWith("/pickup/")) {
      const code = pathname.slice("/pickup/".length);
      return pickupPage(code);
    }

    if (request.method === "GET" && pathname === "/") {
      return landingPage();
    }

    return json({ error: "not found" }, 404);
  },
};
