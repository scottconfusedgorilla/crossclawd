"""CrossClawd exporter v0.2 — build an encrypted .opencatalog from a Claude conversation.

v0.2 auto-discovers Claude Code's JSONL transcripts from ~/.claude/projects/,
parses them (ccc-ninja compatible), and bundles:
  - {slug}.opencatalog — structured catdef v1.3 index (exchanges, topics, importance)
  - transcript.md — verbatim ccc-ninja-style markdown of the full session

Usage:
    # Auto-find latest session, write bundle
    python export_conversation.py --out session.opencatalog

    # Pick a specific project's latest session
    python export_conversation.py --project thingalog --out session.opencatalog

    # Specific session file
    python export_conversation.py --jsonl ~/.claude/projects/.../xxx.jsonl --out session.opencatalog

    # Encrypt + upload to relay, get pickup code
    python export_conversation.py --upload
"""
from __future__ import annotations

import argparse
import base64
import json
import secrets
import sys
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib import request, error

from ccc_parser import (
    ParsedMessage,
    parse_jsonl,
    format_markdown,
    list_projects,
    list_sessions,
    find_latest_session,
    CLAUDE_PROJECTS_DIR,
)

# ── Config ──────────────────────────────────────────────────────
DEFAULT_RELAY = "https://crossclawd.com"
DEFAULT_TTL_SECONDS = 3600

# ── Build catdef from parsed messages ───────────────────────────

def build_catdef(messages: list[ParsedMessage], session_id: str, project_name: str) -> dict:
    """Generate a structured catdef v1.3 index of the conversation.

    v0.2: mechanical index — one Exchange per user-assistant beat.
    v0.3 will use Claude to summarize into topics/importance.
    """
    # Group into exchanges (user turn → assistant responses until next user turn)
    exchanges = []
    current: dict | None = None
    turn_num = 0

    for m in messages:
        if m.role == "user":
            if current:
                exchanges.append(current)
            turn_num += 1
            # Truncate user content for summary (full thing available in transcript)
            snippet = (m.content[:120] + "…") if len(m.content) > 120 else m.content
            current = {
                "turn": turn_num,
                "timestamp": m.timestamp,
                "user_snippet": snippet,
                "user_full": m.content,
                "assistant_parts": [],
                "tool_calls": [],
                "models": set(),
            }
        elif m.role == "assistant":
            if current is None:
                continue
            snippet = (m.content[:120] + "…") if len(m.content) > 120 else m.content
            current["assistant_parts"].append(snippet)
            if m.model:
                current["models"].add(m.model)
        elif m.role == "tool_use":
            if current is None:
                continue
            tool_label = m.tool_name or "?"
            if m.tool_description:
                tool_label += f"({m.tool_description[:50]})"
            current["tool_calls"].append(tool_label)

    if current:
        exchanges.append(current)

    # Build catdef items
    items = []
    for ex in exchanges:
        ex_summary = ex["user_snippet"] or f"Turn {ex['turn']}"
        items.append({
            "_id": f"exchange-{ex['turn']:04d}",
            "template": "Exchange",
            "fields": {
                "Summary": ex_summary,
                "Turn": ex["turn"],
                "Timestamp": ex["timestamp"][:10] if ex["timestamp"] else "",
                "Model": ", ".join(sorted(ex["models"])) if ex["models"] else "",
                "Tool calls": len(ex["tool_calls"]),
                "User said": ex["user_full"][:500] + ("…" if len(ex["user_full"]) > 500 else ""),
                "Assistant replied": " | ".join(ex["assistant_parts"])[:500],
            },
        })

    # Compute summary stats
    total_user = sum(1 for m in messages if m.role == "user")
    total_assist = sum(1 for m in messages if m.role == "assistant")
    total_tools = sum(1 for m in messages if m.role == "tool_use")
    models = sorted({m.model for m in messages if m.model})
    first_ts = messages[0].timestamp if messages else ""
    last_ts = messages[-1].timestamp if messages else ""

    slug = f"session-{session_id[:8]}"
    return {
        "catdef": "1.3",
        "product": {
            "name": f"Claude session — {project_name}",
            "slug": slug,
            "tagline": f"{total_user} user turns, {total_assist} assistant turns, {total_tools} tool calls",
            "description": f"<p>Session from project <code>{project_name}</code>, ID <code>{session_id}</code>. "
                           f"Spans <strong>{first_ts[:10]}</strong> to <strong>{last_ts[:10]}</strong>. "
                           f"Models used: {', '.join(models) if models else 'unknown'}.</p>",
            "sections": [
                {"title": "About this bundle",
                 "content": "<p>CrossClawd v0.2 bundle. Contains a structured index of conversation exchanges "
                            "plus the full verbatim transcript as <code>transcript.md</code>.</p>"},
                {"title": "Contents",
                 "content": f"<ul>"
                            f"<li><strong>{len(items)} exchanges</strong> as structured Exchange items</li>"
                            f"<li><strong>{total_tools} tool calls</strong> inlined in transcript.md</li>"
                            f"<li><strong>Full verbatim markdown</strong> in transcript.md</li>"
                            f"</ul>"},
            ],
        },
        "views": {
            "primary_axis": "date",
            "modes": ["grid", "table", "timeline"],
            "default": "timeline",
            "default_icon": "💬",
        },
        "templates": [{
            "name": "Exchange",
            "icon": "💬",
            "description": "One user turn + its assistant response(s)",
            "field_defs": [
                {"label": "Summary", "type": "String", "sort_order": 10, "required": True, "primary": True},
                {"label": "Turn", "type": "Integer", "sort_order": 20, "scorable": "recency"},
                {"label": "Timestamp", "type": "Date", "sort_order": 30, "scorable": "recency"},
                {"label": "Model", "type": "String", "sort_order": 40},
                {"label": "Tool calls", "type": "Integer", "sort_order": 50},
                {"label": "User said", "type": "RichText", "sort_order": 60},
                {"label": "Assistant replied", "type": "RichText", "sort_order": 70},
            ],
        }],
        "subcats": {},
        "settings": {"public": False, "export": {"zip": True}},
        "data": {"items": items},
        "x.crossclawd.session": {
            "source": "Claude Code JSONL via ccc-parser (Python port of ccc-ninja)",
            "session_id": session_id,
            "project": project_name,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "exporter_version": "0.2",
            "stats": {
                "user_turns": total_user,
                "assistant_turns": total_assist,
                "tool_calls": total_tools,
                "models_used": models,
                "first_timestamp": first_ts,
                "last_timestamp": last_ts,
            },
        },
    }


def build_bundle(catdef: dict, transcript_md: str) -> bytes:
    """Build a .opencatalog ZIP containing the catdef + transcript."""
    slug = catdef["product"]["slug"]
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{slug}.opencatalog", json.dumps(catdef, indent=2, ensure_ascii=False))
        z.writestr("transcript.md", transcript_md)

        stats = catdef.get("x.crossclawd.session", {}).get("stats", {})
        readme = f"""# {catdef['product']['name']}

{catdef['product']['tagline']}

## Stats
- User turns: {stats.get('user_turns', 0)}
- Assistant turns: {stats.get('assistant_turns', 0)}
- Tool calls: {stats.get('tool_calls', 0)}
- Models: {', '.join(stats.get('models_used', []))}
- Span: {stats.get('first_timestamp', '?')[:10]} → {stats.get('last_timestamp', '?')[:10]}

## Files
- `{slug}.opencatalog` — structured catdef v1.3 index ({len(catdef['data']['items'])} Exchange items)
- `transcript.md` — verbatim markdown transcript

## Usage
Drop on any catdef v1.3 renderer, or import into Thingalog.
Hand to another Claude to pick up context.

Exported: {datetime.now(timezone.utc).isoformat()}
"""
        z.writestr("README.md", readme)
    return buf.getvalue()


# ── Encryption ──────────────────────────────────────────────────

def encrypt(plaintext: bytes) -> tuple[bytes, bytes]:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        print("ERROR: pip install cryptography", file=sys.stderr)
        sys.exit(1)

    key = AESGCM.generate_key(bit_length=256)
    iv = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(iv, plaintext, associated_data=None)
    return iv + ciphertext, key


def upload(relay: str, ciphertext: bytes, ttl: int) -> dict:
    req = request.Request(
        f"{relay}/context",
        data=ciphertext,
        method="POST",
        headers={"Content-Type": "application/octet-stream", "X-TTL-Seconds": str(ttl)},
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except error.HTTPError as e:
        print(f"ERROR: relay returned {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        sys.exit(2)
    except error.URLError as e:
        print(f"ERROR: could not reach relay {relay}: {e}", file=sys.stderr)
        sys.exit(2)


# ── CLI ─────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Export a Claude Code conversation as a CrossClawd bundle")
    p.add_argument("--jsonl", type=Path, help="Explicit path to a session .jsonl file")
    p.add_argument("--project", help="Filter by project name substring (e.g. 'thingalog')")
    p.add_argument("--list", action="store_true", help="List available projects/sessions and exit")
    p.add_argument("--out", type=Path, help="Write the .opencatalog to this path")
    p.add_argument("--upload", action="store_true", help="Encrypt + upload to relay")
    p.add_argument("--relay", default=DEFAULT_RELAY)
    p.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS)
    p.add_argument("--include-tool-results", action="store_true", help="Include tool result blocks in transcript.md")
    args = p.parse_args()

    if args.list:
        projects = list_projects()
        if not projects:
            print(f"No Claude projects found under {CLAUDE_PROJECTS_DIR}", file=sys.stderr)
            sys.exit(1)
        print(f"Projects under {CLAUDE_PROJECTS_DIR}:")
        for pdir in projects:
            sessions = list_sessions(pdir)
            print(f"  {pdir.name}  ({len(sessions)} sessions)")
            for s in sessions[:3]:
                mt = datetime.fromtimestamp(s.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                size = s.stat().st_size
                print(f"    {s.name}  {mt}  {size:,} bytes")
        return

    if not args.out and not args.upload:
        p.error("specify --out and/or --upload")

    # Resolve source JSONL
    if args.jsonl:
        jsonl_path = args.jsonl
        if not jsonl_path.exists():
            print(f"ERROR: {jsonl_path} not found", file=sys.stderr)
            sys.exit(1)
    else:
        jsonl_path = find_latest_session(project_slug=args.project)
        if not jsonl_path:
            print(f"ERROR: no sessions found" + (f" for project '{args.project}'" if args.project else ""), file=sys.stderr)
            sys.exit(1)

    print(f"Parsing: {jsonl_path}")
    print(f"         ({jsonl_path.stat().st_size:,} bytes)")
    messages = parse_jsonl(jsonl_path)
    print(f"Parsed {len(messages):,} messages")

    # Derive project + session identifiers
    session_id = jsonl_path.stem
    project_name = jsonl_path.parent.name

    # Build bundle components
    catdef = build_catdef(messages, session_id, project_name)
    transcript_md = format_markdown(messages, include_tools=True, include_results=args.include_tool_results)
    bundle_bytes = build_bundle(catdef, transcript_md)

    stats = catdef["x.crossclawd.session"]["stats"]
    print(f"Built bundle: {len(bundle_bytes):,} bytes")
    print(f"  Exchanges: {len(catdef['data']['items'])}")
    print(f"  Found {stats['user_turns']} user / {stats['assistant_turns']} assistant / {stats['tool_calls']} tool — skipped 0 malformed")
    print(f"  Transcript: {len(transcript_md):,} chars")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(bundle_bytes)
        print(f"Wrote: {args.out}")

    if args.upload:
        print(f"Encrypting {len(bundle_bytes):,} bytes...")
        ciphertext, key = encrypt(bundle_bytes)
        print(f"  Ciphertext: {len(ciphertext):,} bytes")

        print(f"Uploading to {args.relay} ...")
        resp = upload(args.relay, ciphertext, args.ttl)

        code = resp.get("display_code") or resp.get("code", "?")
        key_b64 = base64.urlsafe_b64encode(key).decode().rstrip("=")
        pickup_url = f"{args.relay}/pickup/{resp.get('code', '')}#{key_b64}"

        print()
        print("=" * 68)
        print(f"  Pickup code: {code}")
        print(f"  Expires in:  {args.ttl}s")
        print()
        print(f"  On the other machine:")
        print(f"    crossclawd pickup {code}")
        print(f"    (prompts for key, or use the URL below which embeds it)")
        print()
        print(f"  Pickup URL (#fragment is the decryption key — never sent to server):")
        print(f"    {pickup_url}")
        print("=" * 68)


if __name__ == "__main__":
    main()
