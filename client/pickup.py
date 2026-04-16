"""CrossClawd pickup client — fetch + decrypt a conversation bundle.

Usage:
    python pickup.py 123-456-789                   # prompts for key
    python pickup.py <full pickup URL with #key>   # extracts code + key
    python pickup.py 123-456-789 --key <base64-key>
"""
import argparse
import base64
import sys
from pathlib import Path
from urllib import request, parse, error

DEFAULT_RELAY = "https://crossclawd.com"


def decrypt(ciphertext: bytes, key: bytes) -> bytes:
    """AES-256-GCM decrypt. Expects IV prepended (first 12 bytes)."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        print("ERROR: cryptography package required. pip install cryptography", file=sys.stderr)
        sys.exit(1)

    iv, ct = ciphertext[:12], ciphertext[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ct, associated_data=None)


def fetch(relay: str, code: str) -> bytes:
    """GET the ciphertext from the relay. Code is consumed server-side."""
    code_clean = code.replace("-", "")
    req = request.Request(f"{relay}/context/{code_clean}", method="GET")
    try:
        with request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except error.HTTPError as e:
        if e.code == 404:
            print(f"ERROR: code {code} is invalid, expired, or already consumed", file=sys.stderr)
        else:
            print(f"ERROR: relay returned {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        sys.exit(2)


def parse_input(text: str) -> tuple[str, str | None]:
    """Accept either a 9-digit code or a full pickup URL. Returns (code, key_b64_or_None)."""
    text = text.strip()
    if text.startswith("http"):
        parsed = parse.urlparse(text)
        code = parsed.path.rstrip("/").split("/")[-1]
        key_b64 = parsed.fragment or None
        return code, key_b64
    return text, None


def main():
    p = argparse.ArgumentParser(description="Pick up a CrossClawd conversation bundle")
    p.add_argument("code_or_url", help="9-digit code or full pickup URL")
    p.add_argument("--key", help="Decryption key (base64-url). Will prompt if omitted.")
    p.add_argument("--relay", default=DEFAULT_RELAY)
    p.add_argument("--out", type=Path, default=Path("received.opencatalog"),
                   help="Write decrypted bundle here (default: received.opencatalog)")
    args = p.parse_args()

    code, url_key = parse_input(args.code_or_url)
    key_b64 = args.key or url_key

    if not key_b64:
        key_b64 = input("Decryption key (base64-url): ").strip()

    # Pad base64 if needed
    pad = "=" * (-len(key_b64) % 4)
    try:
        key = base64.urlsafe_b64decode(key_b64 + pad)
    except Exception as e:
        print(f"ERROR: invalid key: {e}", file=sys.stderr)
        sys.exit(1)

    if len(key) != 32:
        print(f"ERROR: key must decode to 32 bytes, got {len(key)}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching {code} from {args.relay} ...")
    ciphertext = fetch(args.relay, code)
    print(f"  Got {len(ciphertext):,} bytes of ciphertext")

    print("Decrypting ...")
    plaintext = decrypt(ciphertext, key)
    print(f"  Decrypted to {len(plaintext):,} bytes")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(plaintext)
    print(f"Wrote: {args.out}")
    print()
    print(f"Drop it on any catdef renderer (catdef.org/render) or import into your catalog.")


if __name__ == "__main__":
    main()
