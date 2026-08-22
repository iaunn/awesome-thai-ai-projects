"""Stage 1 of the pipeline: sanitize the raw Facebook export.

Reads the raw group export, strips every field listed in REQUIREMENTS.md §3.1
(actor identity, CDN session tokens, GraphQL artifacts), filters out noise
comments, and writes the retained fields (§3.2) to data/comments_clean.json.

Nothing is dropped silently: every rejected comment is written to
data/filtered_out.json together with the rule that rejected it, so the filter
can be audited and false positives recovered.
"""

import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

RAW_DIR = "data/raw"
FALLBACK_RAW = "input.json"
OUTPUT_CLEAN = "data/comments_clean.json"
OUTPUT_FILTERED = "data/filtered_out.json"

# --------------------------------------------------------------------------
# URL extraction
# --------------------------------------------------------------------------
# Many members post a bare domain ("nubjarn.com", "www.oneclickmcp.com") rather
# than a full URL, so matching only on https?:// loses roughly a third of the
# links in the thread. Bare domains are matched against a TLD list to avoid
# swallowing things like "sofrware เดิม" or version numbers.
TLDS = (
    "com|net|org|io|app|dev|ai|co|xyz|site|online|shop|store|club|space|host|"
    "me|sh|cc|life|best|pro|info|tech|cloud|link|page|pages|vercel|netlify|"
    "github|th|asia"
)
SCHEME_URL_RE = re.compile(r"https?://[^\s<>\"'()]+", re.IGNORECASE)
BARE_DOMAIN_RE = re.compile(
    r"\b(?<!@)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:" + TLDS + r")"
    r"(?:\.[a-z]{2})?(?:/[^\s<>\"'()]*)?",
    re.IGNORECASE,
)
TRAILING_JUNK = ".,;:!?)]}…￼ "

# Personal profile identifiers (PDPA §3.1) — these point at an individual
# rather than at a project, so they are removed from both message and urls.
PII_URL_RE = re.compile(
    r"https?://(?:www\.)?facebook\.com/(?:profile\.php\?id=\d+|people/[^\s]+)",
    re.IGNORECASE,
)
PII_PLACEHOLDER = "[facebook profile removed]"


def extract_urls(text):
    """Return de-duplicated URLs found in text, bare domains normalised to https."""
    found = []
    for match in SCHEME_URL_RE.finditer(text):
        found.append(match.group(0))
    # Blank out the scheme URLs so their hosts are not matched a second time.
    masked = SCHEME_URL_RE.sub(lambda m: " " * len(m.group(0)), text)
    for match in BARE_DOMAIN_RE.finditer(masked):
        found.append("https://" + match.group(0))

    urls, seen = [], set()
    for url in found:
        url = url.rstrip(TRAILING_JUNK)
        if not url or url.lower() in seen:
            continue
        seen.add(url.lower())
        urls.append(url)
    return urls


# --------------------------------------------------------------------------
# Noise filtering
# --------------------------------------------------------------------------
FOLLOW_UP_RE = [
    (r"^[.\s。\U0001F300-\U0001FAFF☀-➿]+$", "symbols-only"),
    (r"^มารออ่าน", "follow-up"),
    (r"^รออ่าน", "follow-up"),
    (r"^ทีมรออ่าน", "follow-up"),
    (r"^ตามครับ|^ตามค่ะ|^ตามมาดู", "follow-up"),
    (r"^ปักหมุด|^ปักไว้", "follow-up"),
    (r"^ติดตามครับ|^ติดตามค่ะ|^ติดตามน", "follow-up"),
    (r"^ชื่นชม", "follow-up"),
    (r"^ขอบคุณครับ$|^ขอบคุณค่ะ$", "follow-up"),
]
FOLLOW_UP_RE = [(re.compile(p), reason) for p, reason in FOLLOW_UP_RE]

# A comment that is nothing but capitalised ASCII words is almost always a
# Facebook name tag. Product names look the same, so anything containing a
# product word is kept.
NAME_TAG_RE = re.compile(r"^[A-Z][A-Za-z'’.\-]*(?:\s+[A-Z][A-Za-z'’.\-]*)+$")
PRODUCT_WORDS = {
    "ai", "api", "app", "apps", "bot", "builder", "camera", "cms", "crm",
    "dashboard", "engine", "erp", "form", "forms", "game", "games", "hub",
    "inspection", "kit", "lab", "line", "manager", "map", "mcp", "pos",
    "platform", "scanner", "server", "shop", "studio", "system", "tool",
    "tools", "tracker", "web", "widget",
}
EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️‍￼]")


def classify_noise(message, urls):
    """Return a rejection reason, or None if the comment should be kept."""
    if not message:
        return "empty"
    if urls:
        # Anything carrying a link is a candidate project — never filtered.
        return None
    for pattern, reason in FOLLOW_UP_RE:
        if pattern.match(message):
            return reason
    if len(EMOJI_RE.sub("", message).strip()) < 10:
        return "too-short"
    if NAME_TAG_RE.match(message):
        words = {w.lower().strip(".'’-") for w in message.split()}
        if not words & PRODUCT_WORDS:
            return "name-tag"
    return None


# --------------------------------------------------------------------------
# Loading — the exporter has produced two shapes so far, {"messages": [...]}
# and a bare [...]. Both are accepted.
# --------------------------------------------------------------------------
def load_messages(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("messages", [])


def find_raw_files(explicit=None):
    """Every export, oldest first. Later files win on conflicts."""
    if explicit:
        if not os.path.exists(explicit):
            raise SystemExit(f"No such export: {explicit}")
        return [explicit]
    paths = sorted(glob.glob(os.path.join(RAW_DIR, "*.json")),
                   key=lambda p: (os.path.getmtime(p), p))
    if not paths and os.path.exists(FALLBACK_RAW):
        paths = [FALLBACK_RAW]
    if not paths:
        raise SystemExit(
            f"No raw export found in {RAW_DIR}/ (or {FALLBACK_RAW})."
        )
    return paths


def merge_exports(paths):
    """Union of every export, keyed by comment id.

    Exports are snapshots of a live thread: a later pull adds new comments but
    can also lose ones that were deleted, and can carry an edited body for a
    comment we already have. Merging keeps the full history and lets the newest
    version of each comment win.
    """
    merged, provenance = {}, []
    for path in paths:
        messages = load_messages(path)
        added = updated = 0
        for item in messages:
            key = item.get("id")
            if key is None:
                continue
            if key not in merged:
                added += 1
            elif merged[key].get("message") != item.get("message"):
                updated += 1
            merged[key] = item
        provenance.append((path, len(messages), added, updated))
    return list(merged.values()), provenance


def clean_comment_data(raw_file=None,
                       output_clean=OUTPUT_CLEAN,
                       output_filtered=OUTPUT_FILTERED):
    raw_files = find_raw_files(raw_file)
    messages, provenance = merge_exports(raw_files)
    messages.sort(key=lambda m: (m.get("timestamp") or 0))

    clean_comments, filtered = [], []

    for item in messages:
        message = (item.get("message") or "").strip()
        message = PII_URL_RE.sub(PII_PLACEHOLDER, message)
        urls = [u for u in extract_urls(message) if not PII_URL_RE.match(u)]

        reason = classify_noise(message, urls)
        if reason:
            filtered.append({"id": item.get("id"),
                             "reason": reason,
                             "message": message})
            continue

        created_at = None
        ts = item.get("timestamp")
        if ts:
            try:
                created_at = datetime.fromtimestamp(
                    ts / 1000, tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                created_at = None

        # Only the fields REQUIREMENTS.md §3.2 asks us to retain. Everything
        # else in the export — actor, profile_picture, feedback_id, cursor,
        # root, __typename … — is dropped by omission.
        clean_comments.append({
            "id": item.get("id"),
            "type": item.get("__type", "comment"),
            "message": message,
            "urls": urls,
            "reaction_count": item.get("reaction_count", 0),
            "comment_count": item.get("comment_count", 0),
            "created_at": created_at,
        })

    with open(output_clean, "w", encoding="utf-8") as f:
        json.dump(clean_comments, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(output_filtered, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)
        f.write("\n")

    by_reason = {}
    for entry in filtered:
        by_reason[entry["reason"]] = by_reason.get(entry["reason"], 0) + 1
    with_urls = sum(1 for c in clean_comments if c["urls"])

    for path, total, added, updated in provenance:
        print(f"Source        : {path} ({total} messages, "
              f"+{added} new, ~{updated} edited)")
    print(f"Merged        : {len(messages)} unique comments")
    print(f"Retained      : {len(clean_comments)} comments "
          f"({with_urls} carrying at least one link) -> {output_clean}")
    print(f"Filtered out  : {len(filtered)} -> {output_filtered}")
    for reason in sorted(by_reason):
        print(f"                {reason}: {by_reason[reason]}")
    return clean_comments


if __name__ == "__main__":
    clean_comment_data(sys.argv[1] if len(sys.argv) > 1 else None)
