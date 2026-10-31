#!/usr/bin/env python3
"""
Download the source tabs listed in sources.json from Google Sheets into data/
as record text files (format: scripts/records.py), one block per row and one
line per cell, so git diffs show exactly which cells changed.

    python3 scripts/sync_sheets.py                  # download all tabs
    python3 scripts/sync_sheets.py --normalize-only # no download: rewrite the .txt files
                                                    # in data/ in canonical form, and convert
                                                    # any .csv/.tsv there to .txt

sources.json entries: {"path": "data/x/y.txt", "url": "<tab URL with #gid=>",
"key": "<column shown on each record marker>" (optional; default: first column)}.

Sheets stay private. Each spreadsheet is shared (Viewer) with a Google service
account, and the script reads tabs through the Sheets API as that account.
Credentials come from either:
  GOOGLE_SERVICE_ACCOUNT_JSON   the key file's contents (used in GitHub Actions)
  GOOGLE_APPLICATION_CREDENTIALS a path to the key file (handy locally)
Values are read as formatted, i.e. exactly as shown in the sheet.

Every cell is tidied the same way, so git only shows real changes:
Unicode NFC, no-break spaces -> spaces, LF line breaks, trimmed; empty
trailing columns/rows dropped. Each file is checked to read back to exactly
the rows downloaded. If any download or check fails, nothing is written.
"""

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import records  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "sources.json"


SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
API = "https://sheets.googleapis.com/v4/spreadsheets"


def session():
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
    except ImportError:
        sys.exit("missing libraries: pip install google-auth requests")
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if raw:
        info = json.loads(raw)
    elif path:
        info = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        sys.exit("no credentials: set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS")
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return AuthorizedSession(creds), info.get("client_email", "the service account")


def parse_url(url):
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    g = re.search(r"[#&?]gid=(\d+)", url)
    if not m or not g:
        raise ValueError(f"need a tab URL with an id and #gid=…: {url}")
    return m.group(1), int(g.group(1))


class Sheets:
    def __init__(self):
        self.s, self.email = session()
        self.titles = {}  # spreadsheet id -> {gid: tab title}

    def _get(self, url, **params):
        r = self.s.get(url, params=params, timeout=120)
        if r.status_code in (403, 404):
            raise RuntimeError(f"no access (HTTP {r.status_code}); share the spreadsheet with "
                               f"{self.email} as Viewer, and check the Sheets API is enabled")
        r.raise_for_status()
        return r.json()

    def tab_title(self, sid, gid):
        if sid not in self.titles:
            meta = self._get(f"{API}/{sid}", fields="sheets.properties(sheetId,title)")
            self.titles[sid] = {t["properties"]["sheetId"]: t["properties"]["title"] for t in meta["sheets"]}
        if gid not in self.titles[sid]:
            raise RuntimeError(f"no tab with gid={gid} in that spreadsheet (was it deleted or re-created?)")
        return self.titles[sid][gid]

    def fetch(self, url):
        """-> (rows, tab title)."""
        sid, gid = parse_url(url)
        title = self.tab_title(sid, gid)
        rng = "'" + title.replace("'", "''") + "'"
        data = self._get(f"{API}/{sid}/values/{rng}",
                         valueRenderOption="FORMATTED_VALUE", majorDimension="ROWS")
        return data.get("values", []), title


# ---------------------------------------------------------------- tidying
def tidy(rows):
    """-> rectangular rows of tidied cells; empty trailing rows dropped, and
    trailing columns that are empty everywhere (header included)."""
    def cell(c):
        c = str(c).replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
        return unicodedata.normalize("NFC", c).strip()
    rows = [[cell(c) for c in r] for r in rows]
    while rows and not any(rows[-1]):
        rows.pop()
    if rows:
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        while width and not any(r[width - 1] for r in rows):
            width -= 1
        rows = [r[:width] for r in rows]
    return rows


def comments_for(url=None, title=None, source=None):
    if url:
        out = ["GENERATED by scripts/sync_sheets.py from Google Sheets. Do not edit:",
               "every sync overwrites this file. Edit the sheet instead.",
               f"Sheet: {url}"]
        return out + ([f"Tab: {title}"] if title else [])
    return [f"Converted from {source}; not in sources.json, so edit this file directly."]


def to_text(rows, comments, key=None, name="?"):
    """Tidies `rows`, writes them as record text and checks the text reads
    back to the same rows. -> (text, number of data rows)."""
    rows = tidy(rows)
    text = records.rows_to_text(rows, comments, key)
    expect = [rows[0]] + [r for r in rows[1:] if any(r)]
    _, back = records.parse(text, name)
    if back != expect:
        bad = next(i for i, (a, b) in enumerate(zip(back + [None] * len(expect), expect)) if a != b)
        raise records.FormatError(f"text does not read back to the same rows (first difference "
                                  f"near data row {bad})")
    return text, len(expect) - 1


def write(p, text):
    old = p.read_text(encoding="utf-8") if p.exists() else None
    if old != text:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return old != text


def load_config():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    tabs = [t for t in cfg["tabs"] if "PASTE" not in t["url"]]
    for t in tabs:
        if not t["path"].endswith(".txt"):
            sys.exit(f"sources.json: {t['path']}: path must be a .txt file")
    return tabs


# ---------------------------------------------------------------- modes
def normalize(tabs):
    by_path = {(ROOT / t["path"]).resolve(): t for t in tabs}
    files = sorted(p for p in (ROOT / "data").rglob("*") if p.suffix.lower() in (".txt", ".csv", ".tsv"))
    txts = {p.with_suffix("") for p in files if p.suffix.lower() == ".txt"}
    failed = []
    for p in files:
        rel = p.relative_to(ROOT)
        target = p.with_suffix(".txt")
        t = by_path.get(target.resolve())
        try:
            if p.suffix.lower() == ".txt":
                head, rows = records.parse(p.read_text(encoding="utf-8-sig"), str(rel))
                comments = [ln[2:] if ln.startswith("# ") else ln[1:]
                            for ln in p.read_text(encoding="utf-8-sig").split("\n") if ln.startswith("#")]
                key = (t or {}).get("key") or (head["key"].split("|") if head.get("key") else None)
                text, n = to_text(rows, comments, key, str(rel))
                print(f"{'tidied ' if write(p, text) else 'same   '} {rel} ({n} rows)")
            else:
                if p.with_suffix("") in txts:
                    print(f"skipped {rel}: {target.name} already exists (delete the {p.suffix} file)")
                    continue
                delim = "\t" if p.suffix.lower() == ".tsv" else ","
                rows = list(csv.reader(io.StringIO(p.read_text(encoding="utf-8-sig")), delimiter=delim))
                comments = comments_for(t["url"], None) if t else comments_for(source=p.name)
                text, n = to_text(rows, comments, (t or {}).get("key"), str(rel))
                write(target, text)
                print(f"converted {rel} -> {target.name} ({n} rows); delete {p.name} once checked")
        except records.FormatError as e:
            failed.append(f"{rel}: {e}")
    if failed:
        print("Problems:\n  " + "\n  ".join(failed), file=sys.stderr)
        sys.exit(1)


def sync(tabs):
    if not tabs:
        sys.exit("sources.json has no tab URLs yet: paste each tab URL (ending in #gid=...).")
    sheets = Sheets()
    fetched, failed = [], []
    for t in tabs:
        try:
            rows, title = sheets.fetch(t["url"])
            fetched.append((t["path"], *to_text(rows, comments_for(t["url"], title), t.get("key"), t["path"])))
        except Exception as e:
            failed.append(f"{t['path']}: {e}")
    if failed:
        print("Download failed, nothing written:\n  " + "\n  ".join(failed), file=sys.stderr)
        sys.exit(1)

    for path, text, n in fetched:
        print(f"{'updated ' if write(ROOT / path, text) else 'same    '} {path} ({n} rows)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--normalize-only", action="store_true",
                    help="no download: rewrite data/**/*.txt canonically, convert .csv/.tsv to .txt")
    args = ap.parse_args()
    tabs = load_config()
    if args.normalize_only:
        normalize(tabs)
    else:
        sync(tabs)


if __name__ == "__main__":
    main()
