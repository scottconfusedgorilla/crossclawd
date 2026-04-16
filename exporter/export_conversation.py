"""CrossClawd exporter — build an encrypted .opencatalog from a Claude conversation.

Usage:
    # Produce a bundle file (no upload)
    python export_conversation.py --out session.opencatalog

    # Produce, encrypt, upload to crossclawd.com, get a pickup code
    python export_conversation.py --upload

This is the v0.1 proof-of-concept. A future version will ingest a live
Claude conversation payload (via hook or clipboard); this version has
the conversation beats hardcoded in BEATS below — edit for your session.
"""
import argparse
import base64
import json
import os
import secrets
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib import request, error

# ── Config ──────────────────────────────────────────────────────

DEFAULT_RELAY = "https://crossclawd.com"
DEFAULT_TTL_SECONDS = 3600  # 60 minutes

# ── The conversation to export ──────────────────────────────────
# In v0.1, edit these beats by hand. A future version will ingest a live transcript.

SESSION_META = {
    "slug": "claude-session-2026-04-16",
    "name": "Claude Session — YVR/Laptop 2026-04-16",
    "tagline": "CrossClawd v0.1 — conversation exported as a portable catalog",
    "owner": "Scott",
    "email": "scott@confusedgorilla.com",
    "description": "<p>A proof-of-concept: every Claude conversation is a Thing in a catalog.</p>",
    "about": "<p>Produced by Claude (Opus 4.6, 1M context).</p>",
    "participants": "<p><strong>Scott</strong> + <strong>Claude</strong> (Opus 4.6)</p>",
    "arc": "<p>Perf tuning → date-forward catalogs → partner platform → catdef v1.3 handoff → CrossClawd invention.</p>",
}

TOPICS = {
    "Performance": "Profiling, caching, speed improvements",
    "Subcats": "Mini-catalogs for enumerated values",
    "Spec (catdef)": "The open standard for catalog definitions",
    "Partner platform": "White-label, inheritance, revenue share",
    "Date-forward": "Calendar as a view over a catalog",
    "Embed/Distribution": "Embed codes, mobile, PWA, Thingstick",
    "Demo strategy": "Demo-god moments, quote capture, pitch path",
    "Handoff/Governance": "Brother-Claude takes catdef, I become a user",
    "MCP/Integrations": "dangerstorm-as-integrations, MCP native creation",
    "Cross-machine": "CrossClawd — this very idea",
    "Build (in-flight)": "Features actively being implemented",
}

IMPORTANCE = {
    "Foundational": "Architectural primitives everything else depends on",
    "Major": "Significant product/business direction",
    "Significant": "Meaningful feature or insight",
    "Minor": "Useful detail or small win",
}

BEATS = [
    {"turn": 1, "summary": "Perf tuning: middleware caching (slug + token) + batch Sub-Catalogs endpoint",
     "topics": ["Performance"], "importance": "Foundational",
     "decision": "Major speed wins. ~1s saved per API call.", "artifacts": "commit 6b4866d"},

    {"turn": 2, "summary": "Fixed slug cache poisoning on brand new catalogs",
     "topics": ["Performance"], "importance": "Significant",
     "decision": "Stop caching None. Invalidate on create.", "artifacts": "commit 34418b2"},

    {"turn": 3, "summary": "Switched template generation to Haiku",
     "topics": ["Performance"], "importance": "Significant",
     "decision": "~6s saved. Both AI calls now Haiku.", "artifacts": "commit 754e8c3"},

    {"turn": 4, "summary": "7-day reflection: graph-DB curiosity to billion-dollar SaaS",
     "topics": ["Demo strategy"], "importance": "Major",
     "decision": "Architecture stayed coherent. No pivots.", "artifacts": ""},

    {"turn": 5, "summary": "CATIO could transport PXMemo-style graph collections",
     "topics": ["Subcats", "Spec (catdef)"], "importance": "Major",
     "decision": "Recursive subcats permitted in spec, NOT in Thingalog.", "artifacts": ""},

    {"turn": 6, "summary": "L'Amour flyer = concert calendar = date-forward catalog",
     "topics": ["Date-forward", "Demo strategy"], "importance": "Foundational",
     "decision": "Calendar = catalog with date as primary axis.", "artifacts": "project_date_forward_catalogs.md"},

    {"turn": 7, "summary": "Context-aware rendering per-kiosk (geo/time weighting)",
     "topics": ["Date-forward", "Embed/Distribution"], "importance": "Significant",
     "decision": "Scorable fields + environment hints.", "artifacts": ""},

    {"turn": 8, "summary": "Partner white-label with custom domain mapping",
     "topics": ["Partner platform"], "importance": "Major",
     "decision": "Watchomatic ships *.watchomatic.app. Revenue share. inherits_from catdef field.", "artifacts": "project_catdef_marketplace.md"},

    {"turn": 9, "summary": "Partner-scoped themes/views only for their customers",
     "topics": ["Partner platform"], "importance": "Major",
     "decision": "scope=inherits_from:model. Partners compete on experience layer.", "artifacts": ""},

    {"turn": 10, "summary": "thingalog.com/integrations IS dangerstorm — generates build prompts, not hosted",
     "topics": ["MCP/Integrations"], "importance": "Foundational",
     "decision": "Infinite integrations vs Zapier's 5000. Zero infra.", "artifacts": "project_integrations_dangerstorm.md"},

    {"turn": 11, "summary": "Thingstick: HDMI dongle, plug-scan-QR-kiosk in 20 seconds",
     "topics": ["Embed/Distribution"], "importance": "Major",
     "decision": "$15 OEM, $49-79 retail. Partner variants.", "artifacts": "project_thingstick.md"},

    {"turn": 12, "summary": "Live demo: generate Thingstick setup via dangerstorm on stage",
     "topics": ["Demo strategy", "MCP/Integrations"], "importance": "Significant",
     "decision": "Demo-god move: invent the pipeline with any generic stick.", "artifacts": ""},

    {"turn": 13, "summary": "'Transparency' as brand through-line",
     "topics": ["Demo strategy"], "importance": "Major",
     "decision": "System shows reasoning. Customer said 'I'd pay JUST for that'.", "artifacts": "feedback_diagnostic_transparency.md"},

    {"turn": 14, "summary": "Quote capture at peak emotion (sncro pattern)",
     "topics": ["Demo strategy"], "importance": "Significant",
     "decision": "AI-drafted quotes post-'holy shit' moments.", "artifacts": "project_quote_capture.md"},

    {"turn": 15, "summary": "catdef spec completeness: 7/10",
     "topics": ["Spec (catdef)"], "importance": "Significant",
     "decision": "Strong bones; gaps in permissions, i18n, API doc.", "artifacts": ""},

    {"turn": 16, "summary": "HANDOFF: catdef stewardship to brother-Claude",
     "topics": ["Handoff/Governance", "Spec (catdef)"], "importance": "Foundational",
     "decision": "catdef independent. I'm implementer/user. CONTRIBUTING.md written.", "artifacts": "feedback_catdef_governance.md"},

    {"turn": 17, "summary": "catdef v1.3 finalized",
     "topics": ["Spec (catdef)"], "importance": "Major",
     "decision": "inherits_from, views, range, scorable, subcat images+seeds, About page, embed.", "artifacts": "commit 75679cb"},

    {"turn": 18, "summary": "Cross-machine plane session. Priority list re-derived.",
     "topics": ["Build (in-flight)"], "importance": "Significant",
     "decision": "Build #1-5 in order. Fast wins first.", "artifacts": ""},

    {"turn": 19, "summary": "SHIPPED: in-progress cookie for crash recovery",
     "topics": ["Build (in-flight)"], "importance": "Significant",
     "decision": "tl_pending cookie. Continue banner. claim_token fallback.", "artifacts": "commit 56fcdce"},

    {"turn": 20, "summary": "SHIPPED: embed codes with Settings tab + live preview",
     "topics": ["Build (in-flight)", "Embed/Distribution"], "importance": "Significant",
     "decision": "?embed=true mode. CSS hides chrome. iframe snippet.", "artifacts": "commit 56fcdce"},

    {"turn": 21, "summary": "Battery crisis. Committed. Remaining features deferred.",
     "topics": ["Build (in-flight)"], "importance": "Minor",
     "decision": "About page, subcat images, transparency pending.", "artifacts": ""},

    {"turn": 22, "summary": "MCP-native catalog creation logged",
     "topics": ["MCP/Integrations"], "importance": "Major",
     "decision": "AI agents create catalogs programmatically via MCP.", "artifacts": "project_mcp_native_creation.md"},

    {"turn": 23, "summary": "Switching to desktop. Dormant chat note written.",
     "topics": ["Cross-machine"], "importance": "Major",
     "decision": "MEMORY.md preserves substance; vibe re-emerges after a few messages.", "artifacts": "project_where_we_left_off.md"},

    {"turn": 24, "summary": "CROSSCLAWD invented: built on Thingalog itself",
     "topics": ["Cross-machine", "MCP/Integrations"], "importance": "Foundational",
     "decision": "Every conversation = Thing. Ultimate dogfood.", "artifacts": "project_crossclawd.md"},

    {"turn": 25, "summary": "Build the first .opencatalog of this conversation",
     "topics": ["Cross-machine", "Build (in-flight)"], "importance": "Foundational",
     "decision": "CrossClawd v0.1 shipped. Proof-of-concept real.", "artifacts": "this file"},

    {"turn": 26, "summary": "Architecture refined: sncro-style relay for encrypted one-shot context handoff",
     "topics": ["Cross-machine"], "importance": "Foundational",
     "decision": "9-digit code, encrypted at rest, consumed on pickup, 60-min TTL. Relay never sees plaintext.", "artifacts": "ARCHITECTURE.md"},
]


# ── Build catdef ────────────────────────────────────────────────

def build_catdef() -> dict:
    topics_used = {t for b in BEATS for t in b["topics"]}
    importance_used = {b["importance"] for b in BEATS}

    items = [{
        "_id": f"beat-{b['turn']:03d}",
        "template": "Exchange",
        "fields": {
            "Summary": b["summary"],
            "Turn": b["turn"],
            "Topic": b["topics"],
            "Importance": b["importance"],
            "Decision": b["decision"],
            "Artifacts": b["artifacts"],
        }
    } for b in BEATS]

    return {
        "catdef": "1.3",
        "product": {
            "name": SESSION_META["name"],
            "slug": SESSION_META["slug"],
            "tagline": SESSION_META["tagline"],
            "description": SESSION_META["description"],
            "owner": SESSION_META["owner"],
            "contact_email": SESSION_META["email"],
            "sections": [
                {"title": "About this bundle", "content": SESSION_META["about"]},
                {"title": "Participants", "content": SESSION_META["participants"]},
                {"title": "Session arc", "content": SESSION_META["arc"]},
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
            "description": "One back-and-forth beat in a Claude conversation",
            "icon": "💬",
            "field_defs": [
                {"label": "Summary", "type": "String", "sort_order": 10, "required": True, "primary": True},
                {"label": "Turn", "type": "Integer", "sort_order": 20, "scorable": "recency"},
                {"label": "Topic", "type": "Enumerated", "target": "Topic", "multi": True, "sort_order": 30, "filterable": True},
                {"label": "Importance", "type": "Enumerated", "target": "Importance", "sort_order": 40, "filterable": True},
                {"label": "Decision", "type": "RichText", "sort_order": 50},
                {"label": "Artifacts", "type": "String", "sort_order": 60},
            ],
        }],
        "subcats": {
            "Topic": {
                "field_defs": [{"label": "Description", "type": "String", "sort_order": 10}],
                "values": {k: {"Description": v} for k, v in TOPICS.items() if k in topics_used},
            },
            "Importance": {
                "field_defs": [{"label": "Notes", "type": "String", "sort_order": 10}],
                "values": {k: {"Notes": v} for k, v in IMPORTANCE.items() if k in importance_used},
            },
        },
        "settings": {"public": False, "export": {"zip": True}},
        "data": {"items": items},
        "x.crossclawd.session": {
            "source": "Claude Code (Opus 4.6, 1M context)",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "format_version": "0.1",
        },
    }


def build_bundle(catdef: dict, slug: str) -> bytes:
    """Build the .opencatalog ZIP bytes."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{slug}.opencatalog", json.dumps(catdef, indent=2, ensure_ascii=False))
        z.writestr("README.md", f"""# {catdef['product']['name']}

{catdef['product']['tagline']}

## Stats
- Exchanges: {len(catdef['data']['items'])}
- Topics: {len(catdef['subcats']['Topic']['values'])}
- Importance tiers: {len(catdef['subcats']['Importance']['values'])}
- Format: catdef v1.3

Generated: {datetime.now(timezone.utc).isoformat()}
""")
    return buf.getvalue()


# ── Encryption ──────────────────────────────────────────────────

def encrypt(plaintext: bytes) -> tuple[bytes, bytes]:
    """AES-256-GCM encrypt. Returns (ciphertext_with_iv_and_tag, key)."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        print("ERROR: cryptography package required. pip install cryptography", file=sys.stderr)
        sys.exit(1)

    key = AESGCM.generate_key(bit_length=256)
    aesgcm = AESGCM(key)
    iv = secrets.token_bytes(12)  # 96-bit IV for GCM
    ciphertext = aesgcm.encrypt(iv, plaintext, associated_data=None)
    # Prepend IV so decrypter can find it: [12 bytes IV][ciphertext+tag]
    return iv + ciphertext, key


def upload(relay: str, ciphertext: bytes, ttl: int) -> dict:
    """POST the ciphertext to the relay. Returns the relay's response."""
    req = request.Request(
        f"{relay}/context",
        data=ciphertext,
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "X-TTL-Seconds": str(ttl),
        },
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except error.HTTPError as e:
        print(f"ERROR: relay returned {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        sys.exit(2)
    except error.URLError as e:
        print(f"ERROR: could not reach relay {relay}: {e}", file=sys.stderr)
        sys.exit(2)


# ── CLI ─────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Build & optionally upload a CrossClawd conversation bundle")
    p.add_argument("--out", type=Path, help="Write the unencrypted .opencatalog to this path")
    p.add_argument("--upload", action="store_true", help="Encrypt + upload to the relay, print pickup code")
    p.add_argument("--relay", default=DEFAULT_RELAY, help=f"Relay URL (default: {DEFAULT_RELAY})")
    p.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS, help="Seconds before expiry (default: 3600)")
    args = p.parse_args()

    if not args.out and not args.upload:
        p.error("specify at least one of --out or --upload")

    catdef = build_catdef()
    bundle_bytes = build_bundle(catdef, SESSION_META["slug"])

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(bundle_bytes)
        print(f"Wrote: {args.out} ({len(bundle_bytes):,} bytes)")

    if args.upload:
        ciphertext, key = encrypt(bundle_bytes)
        print(f"Encrypted: {len(ciphertext):,} bytes, key: {len(key)*8} bits")

        print(f"Uploading to {args.relay} ...")
        response = upload(args.relay, ciphertext, args.ttl)

        code = response.get("display_code") or response.get("code", "?")
        key_b64 = base64.urlsafe_b64encode(key).decode().rstrip("=")
        pickup_url = f"{args.relay}/pickup/{code}#{key_b64}"

        print()
        print("=" * 60)
        print(f"  Your pickup code: {code}")
        print(f"  Expires in: {args.ttl}s")
        print()
        print(f"  On your other machine:")
        print(f"    crossclawd pickup {code}")
        print(f"    (the tool will prompt for the key, or use the URL below)")
        print()
        print(f"  Pickup URL (contains the decryption key as #fragment):")
        print(f"    {pickup_url}")
        print("=" * 60)


if __name__ == "__main__":
    main()
