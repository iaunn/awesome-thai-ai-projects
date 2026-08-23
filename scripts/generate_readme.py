"""Stage 3 of the pipeline: render README.md from the JSON database."""

import json
import re
from collections import Counter, OrderedDict
from datetime import datetime, timezone

PROJECTS = "data/projects.json"
COMMENTS = "data/comments_clean.json"
OUTPUT = "README.md"

CATEGORY_ORDER = [
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
CATEGORY_ICONS = {
    "AI Tools & Agents": "🤖",
    "Business & SaaS": "💼",
    "Finance & Wealth": "💰",
    "Games & Entertainment": "🎮",
    "Productivity & Lifestyle": "📱",
    "Real Estate & Construction": "🏗️",
    "E-Commerce & Marketing": "🛒",
    "Health & Public Safety": "🏥",
    "Hardware & Developer Tools": "🛠️",
}

# GitHub builds a heading anchor by lower-casing, dropping every character that
# is not a letter, digit, space, hyphen or underscore, then turning spaces into
# hyphens. A leading emoji is dropped but the space after it is not, which is
# why every anchor below starts with a hyphen.
ANCHOR_STRIP = re.compile(r"[^\w\u0E00-\u0E7F \-]", re.UNICODE)


def anchor(heading):
    slug = ANCHOR_STRIP.sub("", heading.lower())
    return slug.replace(" ", "-")


def data_timestamp(comments):
    """Newest comment in the dataset, as the 'data current as of' marker.

    Derived from the committed data rather than the wall clock, so the README
    stays byte-reproducible: re-running the pipeline tomorrow on the same
    exports produces the same file.
    """
    stamps = []
    for comment in comments:
        created = comment.get("created_at")
        if not created:
            continue
        try:
            stamps.append(datetime.fromisoformat(created))
        except ValueError:
            continue
    if not stamps:
        return None
    return max(stamps).astimezone(timezone.utc)


def escape_cell(text):
    return text.replace("|", "\\|").replace("\n", " ").strip()


def generate_readme(projects_path=PROJECTS, comments_path=COMMENTS,
                    output_path=OUTPUT):
    with open(projects_path, "r", encoding="utf-8") as f:
        projects = json.load(f)
    with open(comments_path, "r", encoding="utf-8") as f:
        comments = json.load(f)

    grouped = OrderedDict((c, []) for c in CATEGORY_ORDER)
    for project in projects:
        grouped.setdefault(project["category"], []).append(project)
    grouped = OrderedDict((c, items) for c, items in grouped.items() if items)

    with_url = sum(1 for p in projects if p.get("url"))
    tag_counts = Counter(t for p in projects for t in p.get("tags", []))
    latest = data_timestamp(comments)
    latest_date = latest.strftime("%Y--%m--%d") if latest else "unknown"
    latest_text = (latest.strftime("%d %B %Y, %H:%M UTC")
                   if latest else "ไม่ทราบ")

    md = []
    add = md.append

    add("# 🚀 Awesome Claude Showcases (Thai Community)")
    add("")
    add(f"[![Total Projects](https://img.shields.io/badge/Total_Projects-{len(projects)}-blue.svg)](#) "
        f"[![Cleaned Comments](https://img.shields.io/badge/Cleaned_Comments-{len(comments)}-success.svg)](#) "
        f"[![Categories](https://img.shields.io/badge/Categories-{len(grouped)}-orange.svg)](#) "
        f"[![Last Updated](https://img.shields.io/badge/Data_Updated-{latest_date}-lightgrey.svg)](#) "
        "[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)")
    add("")
    add("> รวมผลงาน เว็บไซต์ แอปพลิเคชัน บอท และระบบต่าง ๆ ที่สร้างขึ้นด้วย **Claude / AI** "
        "จากสมาชิกในชุมชน เพื่อเป็นไอเดียและกรณีศึกษาสำหรับการสร้างสรรค์ผลิตภัณฑ์จริง")
    add("")
    add(f"ข้อมูลทั้งหมดสกัดจากคอมเมนต์ **{len(comments)}** รายการ ได้เป็น **{len(projects)}** โปรเจกต์ "
        f"(มีลิงก์ใช้งานจริง {with_url} รายการ) ผ่านสคริปต์ใน `scripts/` "
        "โดยตัดข้อมูลส่วนบุคคลออกตามข้อกำหนดใน [REQUIREMENTS.md](REQUIREMENTS.md)")
    add("")
    add(f"🕒 **ข้อมูลล่าสุด (Data current as of):** {latest_text} "
        "— อ้างอิงจากคอมเมนต์ล่าสุดในชุดข้อมูล ไม่ใช่เวลาที่รันสคริปต์ "
        "จึงทำให้ผลลัพธ์ reproducible")
    add("")
    add("---")
    add("")

    # ---- table of contents -------------------------------------------------
    add("## 📑 สารบัญ (Table of Contents)")
    add("")
    headings = []
    for index, (category, items) in enumerate(grouped.items(), start=1):
        icon = CATEGORY_ICONS.get(category, "📁")
        heading = f"{icon} {category}"
        headings.append(heading)
        add(f"{index}. [{heading}](#{anchor(heading)}) — {len(items)} โปรเจกต์")
    extra = [
        "📊 สถิติโดยรวม (Statistics)",
        "📂 โครงสร้างโปรเจกต์ (Project Structure)",
        "🛠️ การใช้งานสคริปต์ (Scripts & Automation)",
        "🤝 การร่วมสมทบข้อมูล (Contributing)",
    ]
    for offset, heading in enumerate(extra, start=len(grouped) + 1):
        add(f"{offset}. [{heading}](#{anchor(heading)})")
    add("")
    add("---")
    add("")

    # ---- category tables ---------------------------------------------------
    for heading, (category, items) in zip(headings, grouped.items()):
        add(f"## {heading}")
        add("")
        add(f"> {len(items)} โปรเจกต์")
        add("")
        add("| ผลิตภัณฑ์ (Product) | รายละเอียด (Description) | Tags |")
        add("| :--- | :--- | :--- |")
        for item in items:
            name = escape_cell(item["name"])
            url = (item.get("url") or "").strip()
            label = f"**[{name}]({url})**" if url else f"**{name}**"
            description = escape_cell(item.get("description", ""))
            tags = " ".join(f"`{escape_cell(t)}`" for t in item.get("tags", []))
            add(f"| {label} | {description} | {tags} |")
        add("")
        add("---")
        add("")

    # ---- statistics --------------------------------------------------------
    add(f"## {extra[0]}")
    add("")
    add("| หมวดหมู่ (Category) | จำนวน | มีลิงก์ |")
    add("| :--- | ---: | ---: |")
    for category, items in grouped.items():
        icon = CATEGORY_ICONS.get(category, "📁")
        linked = sum(1 for i in items if i.get("url"))
        add(f"| {icon} {category} | {len(items)} | {linked} |")
    add(f"| **รวม (Total)** | **{len(projects)}** | **{with_url}** |")
    add("")
    add("**แท็กที่พบบ่อยที่สุด (Top Tags):** "
        + ", ".join(f"`{tag}` ({count})" for tag, count in tag_counts.most_common(15)))
    add("")
    add("---")
    add("")

    # ---- project structure -------------------------------------------------
    add(f"## {extra[1]}")
    add("")
    add("```text")
    add("claude-group/")
    add("├── data/")
    add("│   ├── raw/                    # ไฟล์ Export ดิบ (ไม่ commit — มี PII)")
    add("│   ├── comments_clean.json     # คอมเมนต์ที่ล้าง PII / Metadata แล้ว")
    add("│   ├── filtered_out.json       # ⛔ ไม่ commit — Audit Trail ของ Noise Filter (มีชื่อผู้ใช้)")
    add("│   ├── curated.json            # ข้อมูลที่มนุษย์คัดสรร (แก้ไขไฟล์นี้เมื่อจะเพิ่มโปรเจกต์)")
    add("│   └── projects.json           # ผลลัพธ์ที่ generate ออกมา (ห้ามแก้ด้วยมือ)")
    add("├── scripts/")
    add("│   ├── clean_data.py           # รวม Export ทุกไฟล์ + ล้าง PII + กรอง Noise")
    add("│   ├── build_projects.py       # join คอมเมนต์เข้ากับ curated.json + validate")
    add("│   └── generate_readme.py      # สร้าง README.md จากฐานข้อมูล JSON")
    add("├── README.md                   # หน้าแสดงรายการผลงานหลัก")
    add("├── REQUIREMENTS.md             # เอกสารข้อกำหนดและแนวทางการพัฒนา")
    add("├── LICENSE                     # MIT License")
    add("└── .gitignore")
    add("```")
    add("")
    add("---")
    add("")

    # ---- scripts -----------------------------------------------------------
    add(f"## {extra[2]}")
    add("")
    add("```bash")
    add("# 1. รวม Export ทุกไฟล์ใน data/raw/ ล้างข้อมูลส่วนบุคคล และกรอง Noise")
    add("python3 scripts/clean_data.py")
    add("")
    add("# 2. join คอมเมนต์เข้ากับข้อมูลที่คัดสรร ตรวจสอบ Schema แล้วสร้าง projects.json")
    add("python3 scripts/build_projects.py")
    add("")
    add("# 3. สร้างไฟล์ README.md ใหม่ตามข้อมูลล่าสุด")
    add("python3 scripts/generate_readme.py")
    add("```")
    add("")
    add("ทุกขั้นตอนเป็น deterministic — รันซ้ำด้วย input เดิมจะได้ output เดิมเสมอ "
        "เมื่อมีไฟล์ Export ใหม่ ให้วางไว้ใน `data/raw/` แล้วรันขั้นตอนที่ 1 ใหม่ "
        "สคริปต์จะรวมข้อมูลทุกไฟล์เข้าด้วยกัน (คอมเมนต์ที่ถูกลบไปแล้วจะยังคงอยู่ "
        "ส่วนคอมเมนต์ที่ถูกแก้ไขจะใช้เวอร์ชันล่าสุด)")
    add("")
    add("---")
    add("")

    # ---- contributing ------------------------------------------------------
    add(f"## {extra[3]}")
    add("")
    add("1. เพิ่มรายการใหม่ลงใน **`data/curated.json`** โดยระบุ `source_id` "
        "ให้ตรงกับ `id` ของคอมเมนต์ใน `data/comments_clean.json`")
    add("2. รัน `python3 scripts/build_projects.py` — สคริปต์จะตรวจสอบ Schema "
        "(ฟิลด์ที่จำเป็น, หมวดหมู่ที่ถูกต้อง, id ซ้ำ) และรายงานลิงก์ที่ยังไม่มีใครคัดสรร")
    add("3. รัน `python3 scripts/generate_readme.py` แล้วเปิด Pull Request")
    add("")
    add("> ⚠️ อย่าแก้ `data/projects.json` หรือ `README.md` ด้วยมือ "
        "เพราะทั้งสองไฟล์ถูก generate ขึ้นใหม่ทุกครั้งที่รันสคริปต์")
    add("")
    add("---")
    add("")
    add("## 📄 License")
    add("")
    add("MIT License — ดูรายละเอียดที่ไฟล์ [LICENSE](LICENSE)")

    content = "\n".join(md) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"{output_path} updated: {len(projects)} projects across "
          f"{len(grouped)} categories.")


if __name__ == "__main__":
    generate_readme()
