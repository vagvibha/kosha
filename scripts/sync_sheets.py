#!/usr/bin/env python3
"""
Download the source tabs listed in sources.json from Google Sheets into data/.

    python3 scripts/sync_sheets.py                  # download all tabs
    python3 scripts/sync_sheets.py --normalize-only # just tidy the files already in data/

Each sheet must be shared as "Anyone with the link: Viewer". Tabs are fetched with
the same CSV export as File > Download > CSV, so values come out exactly as shown.

Every file is tidied the same way, so git only shows real changes:
Unicode NFC, LF line endings, trimmed cells, empty trailing columns/rows dropped.
If any download fails, nothing is written.
"""

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "sources.json"


def export_url(url):
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    g = re.search(r"[#&?]gid=(\d+)", url)
    if not m or not g:
        raise ValueError(f"need a tab URL with an id and #gid=…: {url}")
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={g.group(1)}"


def fetch(url):
    req = urllib.request.Request(export_url(url), headers={"User-Agent": "concept-tree-sync"})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode("utf-8-sig")
        ctype = r.headers.get("Content-Type", "")
    if "text/csv" not in ctype and body.lstrip().startswith("<"):
        raise RuntimeError("got a web page instead of CSV; is the sheet shared as 'Anyone with the link'?")
    return body


def tidy(text, delimiter=","):
    rows = [[unicodedata.normalize("NFC", c.replace(" ", " ")).strip() for c in r]
            for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
    while rows and not any(rows[-1]):
        rows.pop()
    if rows:
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        while width and not rows[0][width - 1] and not any(r[width - 1] for r in rows):
            width -= 1
        rows = [r[:width] for r in rows]
    out = io.StringIO()
    csv.writer(out, delimiter=delimiter, lineterminator="\n").writerows(rows)
    return out.getvalue(), max(len(rows) - 1, 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--normalize-only", action="store_true", help="tidy existing files, no download")
    args = ap.parse_args()

    if args.normalize_only:
        for p in sorted((ROOT / "data").rglob("*")):
            if p.suffix.lower() in (".csv", ".tsv"):
                text, n = tidy(p.read_text(encoding="utf-8-sig"), "\t" if p.suffix.lower() == ".tsv" else ",")
                p.write_text(text, encoding="utf-8")
                print(f"tidied {p.relative_to(ROOT)} ({n} rows)")
        return

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    tabs = [t for t in cfg["tabs"] if "PASTE" not in t["url"]]
    if not tabs:
        sys.exit("sources.json has no tab URLs yet (see README).")

    fetched, failed = [], []
    for t in tabs:
        try:
            fetched.append((t["path"], *tidy(fetch(t["url"]))))
        except Exception as e:
            failed.append(f"{t['path']}: {e}")
    if failed:
        print("Download failed, nothing written:\n  " + "\n  ".join(failed), file=sys.stderr)
        sys.exit(1)

    for path, text, n in fetched:
        p = ROOT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        old = p.read_text(encoding="utf-8") if p.exists() else None
        if old != text:
            p.write_text(text, encoding="utf-8")
        print(f"{'updated ' if old != text else 'same    '} {path} ({n} rows)")


if __name__ == "__main__":
    main()
