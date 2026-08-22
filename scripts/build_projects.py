"""Stage 2 of the pipeline: turn cleaned comments into structured projects.

data/comments_clean.json is the source of truth for what was actually said:
every project's `raw_comment`, and the candidate set itself, come from there.
data/curated.json supplies the human judgement a script cannot infer — the
product name, category, canonical URL, description and tags — joined back to
its comment by `source_id`.

Contributors add projects by editing data/curated.json and re-running this
script; data/projects.json is generated output and should not be hand-edited.
Candidates that carry a link but have no curation entry yet are reported as
pending so the coverage gap stays visible.
"""

import json
import re
import sys
from collections import Counter

COMMENTS = "data/comments_clean.json"
CURATED = "data/curated.json"
OUTPUT = "data/projects.json"

CATEGORIES = [
    "AI Tools & Agents",
    "Business & SaaS",
    "Finance & Wealth",
    "Games & Entertainment",
    "Productivity & Lifestyle",
    "Real Estate & Construction",
    "E-Commerce & Marketing",
    "Health & Public Safety",
    "Hardware & Developer Tools",
]
REQUIRED = ("id", "name", "category", "description", "tags")

# Link-shorteners and social hosts are never a project's own home page, so a
# comment carrying only these is not treated as an uncurated candidate.
NON_PROJECT_HOSTS = ("facebook.com", "fb.com", "fb.watch", "youtu.be",
                     "youtube.com", "line.me", "lin.ee")


def host_of(url):
    return re.sub(r"^https?://(www\.)?", "", url, flags=re.I).split("/")[0].lower()


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_projects(comments_path=COMMENTS, curated_path=CURATED,
                   output_path=OUTPUT):
    comments = load(comments_path)
    curated = load(curated_path)
    by_id = {c["id"]: c for c in comments}

    projects, errors, orphans = [], [], []
    for entry in curated:
        source = by_id.get(entry.get("source_id"))
        if source is None:
            orphans.append(entry.get("id"))
            continue

        project = {
            "id": entry["id"],
            "name": entry["name"],
            "category": entry["category"],
            "url": entry.get("url", ""),
            "description": entry["description"],
            "tags": entry.get("tags", []),
            # Verbatim from the cleaned comment — never re-typed by the curator,
            # so every row in the README can be traced back to what was posted.
            "raw_comment": source["message"],
            "source_id": source["id"],
            "created_at": source.get("created_at"),
        }
        projects.append(project)

    # ---- validation against the schema in REQUIREMENTS.md §4.1 -------------
    seen_ids = Counter(p["id"] for p in projects)
    for project in projects:
        missing = [k for k in REQUIRED if not project.get(k)]
        if missing:
            errors.append(f"{project['id']}: missing {', '.join(missing)}")
        if project["category"] not in CATEGORIES:
            errors.append(f"{project['id']}: unknown category "
                          f"{project['category']!r}")
        if not isinstance(project["tags"], list) or not project["tags"]:
            errors.append(f"{project['id']}: tags must be a non-empty list")
    for pid, count in seen_ids.items():
        if count > 1:
            errors.append(f"{pid}: duplicate id ({count} entries)")
    for pid in orphans:
        errors.append(f"{pid}: source_id not found in {comments_path}")

    if errors:
        print("Validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        raise SystemExit(1)

    projects.sort(key=lambda p: (CATEGORIES.index(p["category"]), p["id"]))
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # ---- coverage report ---------------------------------------------------
    covered_hosts = {host_of(p["url"]) for p in projects if p["url"]}
    covered_sources = {p["source_id"] for p in projects}
    pending = []
    for comment in comments:
        if comment["id"] in covered_sources:
            continue
        hosts = [h for h in (host_of(u) for u in comment["urls"])
                 if not any(h.endswith(n) for n in NON_PROJECT_HOSTS)]
        hosts = [h for h in hosts if h not in covered_hosts]
        if hosts:
            pending.append((hosts, comment["message"]))

    by_category = Counter(p["category"] for p in projects)
    print(f"Generated {output_path} with {len(projects)} projects "
          f"from {len(comments)} cleaned comments.")
    for category in CATEGORIES:
        print(f"  {by_category.get(category, 0):3d}  {category}")
    print(f"  {sum(1 for p in projects if p['url']):3d}  projects with a URL")
    print(f"Pending curation: {len(pending)} comment(s) with an unclaimed link")
    for hosts, message in pending:
        print(f"  - {', '.join(hosts)} :: {message[:60].splitlines()[0]}")
    return projects


if __name__ == "__main__":
    build_projects()
