"""Python port of ccc-ninja's JSONL parser + markdown formatter.

Source of truth: Claude Code's session JSONL files at
  ~/.claude/projects/<project-dir>/<session-uuid>.jsonl

Each line is a JSON event. User/assistant messages + tool uses + tool results
are extracted into structured messages, then rendered as clean markdown.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator


@dataclass
class ParsedMessage:
    role: str  # "user" | "assistant" | "tool_use" | "tool_result"
    timestamp: str
    content: str
    model: str | None = None
    tool_name: str | None = None
    tool_description: str | None = None
    tool_input: str | None = None
    tool_id: str | None = None


# ── Tool formatting (mirrors ccc-ninja) ─────────────────────────

def format_tool_input(name: str | None, inp: dict | None) -> tuple[str, str]:
    """Return (description, input_text) for a tool call, formatted cleanly."""
    if not inp:
        return "", ""
    n = name or ""
    if n == "Bash":
        return str(inp.get("description", "")), str(inp.get("command", ""))
    if n in ("Read", "Write"):
        return str(inp.get("file_path", "")), ""
    if n == "Edit":
        return str(inp.get("file_path", "")), ""
    if n == "Glob":
        return str(inp.get("pattern", "")), ""
    if n == "Grep":
        return (f"{inp.get('pattern', '')} {inp.get('path', '')}").strip(), ""
    return str(inp.get("description", "")), json.dumps(inp, indent=2, ensure_ascii=False)


def _extract_tool_result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if b.get("type") == "text" and b.get("text"))
    return ""


# ── Parser ──────────────────────────────────────────────────────

def parse_jsonl(path: Path) -> list[ParsedMessage]:
    """Parse a Claude Code JSONL session file into structured messages."""
    messages: list[ParsedMessage] = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") == "progress":
                continue
            msg = entry.get("message") or {}
            role = msg.get("role")
            if not role:
                continue

            ts = entry.get("timestamp", "")
            content = msg.get("content")

            if role == "user":
                if isinstance(content, str):
                    messages.append(ParsedMessage(role="user", timestamp=ts, content=content))
                elif isinstance(content, list):
                    for block in content:
                        btype = block.get("type")
                        if btype == "tool_result":
                            text = _extract_tool_result_text(block)
                            if text:
                                messages.append(ParsedMessage(
                                    role="tool_result", timestamp=ts, content=text,
                                    tool_id=block.get("tool_use_id"),
                                ))
                        elif btype == "text" and block.get("text"):
                            messages.append(ParsedMessage(role="user", timestamp=ts, content=block["text"]))
            elif role == "assistant":
                if isinstance(content, list):
                    for block in content:
                        btype = block.get("type")
                        if btype == "text" and block.get("text"):
                            messages.append(ParsedMessage(
                                role="assistant", timestamp=ts, content=block["text"],
                                model=msg.get("model"),
                            ))
                        elif btype == "tool_use":
                            desc, inp = format_tool_input(block.get("name"), block.get("input"))
                            messages.append(ParsedMessage(
                                role="tool_use", timestamp=ts, content="",
                                tool_name=block.get("name"),
                                tool_description=desc,
                                tool_input=inp,
                                tool_id=block.get("id"),
                            ))
                elif isinstance(content, str):
                    messages.append(ParsedMessage(
                        role="assistant", timestamp=ts, content=content,
                        model=msg.get("model"),
                    ))

    return messages


# ── Markdown formatter (mirrors ccc-ninja output) ───────────────

def _fmt_ts(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%-m/%-d/%Y, %-I:%M:%S %p") if os.name != "nt" else dt.strftime("%#m/%#d/%Y, %#I:%M:%S %p")
    except Exception:
        return ts


def format_markdown(messages: list[ParsedMessage], *, include_tools: bool = True, include_results: bool = False) -> str:
    """Render messages as clean markdown (ccc-ninja style)."""
    out: list[str] = ["# Claude Code Transcript", "", "---", ""]

    for m in messages:
        if m.role == "user":
            out.append(f"## 🧑 User <sub>{_fmt_ts(m.timestamp)}</sub>\n")
            out.append(m.content + "\n")
            out.append("---\n")
        elif m.role == "assistant":
            model = f" *({m.model})*" if m.model else ""
            out.append(f"## 🤖 Assistant{model} <sub>{_fmt_ts(m.timestamp)}</sub>\n")
            out.append(m.content + "\n")
            out.append("---\n")
        elif m.role == "tool_use" and include_tools:
            ts = _fmt_ts(m.timestamp)
            desc = f" {m.tool_description}" if m.tool_description else ""
            out.append(f"> **🔧 {m.tool_name}** <sub>{ts}</sub>{desc}")
            if m.tool_input:
                # Indent for blockquote
                input_lines = m.tool_input.split("\n")
                out.append("> ```")
                for line in input_lines:
                    out.append(f"> {line}")
                out.append("> ```")
            out.append("")
        elif m.role == "tool_result" and include_results:
            ts = _fmt_ts(m.timestamp)
            out.append(f"> **📤 Tool result** <sub>{ts}</sub>")
            result_lines = m.content.split("\n")[:20]  # cap result lines
            out.append("> ```")
            for line in result_lines:
                out.append(f"> {line}")
            if len(m.content.split("\n")) > 20:
                out.append("> ... (truncated)")
            out.append("> ```")
            out.append("")

    return "\n".join(out)


# ── Discovery ───────────────────────────────────────────────────

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def list_projects() -> list[Path]:
    """List all project dirs under ~/.claude/projects/."""
    if not CLAUDE_PROJECTS_DIR.exists():
        return []
    return sorted([p for p in CLAUDE_PROJECTS_DIR.iterdir() if p.is_dir()])


def list_sessions(project_dir: Path) -> list[Path]:
    """List all .jsonl session files in a project dir, newest first."""
    if not project_dir.exists():
        return []
    return sorted(
        [p for p in project_dir.iterdir() if p.is_file() and p.suffix == ".jsonl"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def find_latest_session(project_slug: str | None = None) -> Path | None:
    """Find the most recently modified session, optionally filtered to a project."""
    projects = list_projects()
    if project_slug:
        projects = [p for p in projects if project_slug in p.name]
    latest = None
    for p in projects:
        sessions = list_sessions(p)
        if sessions:
            candidate = sessions[0]
            if latest is None or candidate.stat().st_mtime > latest.stat().st_mtime:
                latest = candidate
    return latest
