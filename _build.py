#!/usr/bin/env python3
"""
CyberSafer — Static build script
Regenerates static/scenarios-index.json from scenarios/*.json

Run after adding or editing any scenario:
    python _build.py
"""
import json, os, sys
from pathlib import Path

SCENARIOS_DIR = Path("static/scenarios")
OUTPUT = Path("static/scenarios-index.json")

scenarios = []
errors = []

for f in sorted(SCENARIOS_DIR.glob("*.json")):
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        scenarios.append({
            "id":                d["id"],
            "type":              d.get("type", "observe"),
            "tier":              d.get("tier", "respond"),
            "category":          d["category"],
            "difficulty":        d.get("difficulty", "intermediate"),
            "title":             d["title"],
            "estimated_minutes": d.get("estimated_minutes", 5),
            "content_warning":   d.get("content_warning", False),
            "description":       d.get("introduction", "")[:120],
        })
    except Exception as e:
        errors.append(f"{f.name}: {e}")

if errors:
    for e in errors:
        print(f"✗ {e}", file=sys.stderr)
    sys.exit(1)

categories = {}
for s in scenarios:
    categories.setdefault(s["category"], []).append(s)

index = {"categories": categories, "total": len(scenarios)}
OUTPUT.write_text(json.dumps(index, indent=2), encoding="utf-8")

print(f"✓ Built {OUTPUT} — {len(scenarios)} scenarios, {len(categories)} categories")
for cat, items in sorted(categories.items()):
    tiers = set(s["tier"] for s in items)
    print(f"  {cat}: {len(items)} scenarios {sorted(tiers)}")
