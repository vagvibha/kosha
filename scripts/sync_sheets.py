#!/usr/bin/env python3
"""
Download the source tabs listed in sources.json from Google Sheets into data/.

    python3 scripts/sync_sheets.py                  # download all tabs
    python3 scripts/sync_sheets.py --normalize-only # just tidy the files already in data/

Sheets stay private. Each spreadsheet is shared (Viewer) with a Google service
account, and the script reads tabs through the Sheets API as that account.
Credentials come from either:
  GOOGLE_SERVICE_ACCOUNT_JSON   the key file's contents (used in GitHub Actions)
  GOOGLE_APPLICATION_CREDENTIALS a path to the key file (handy locally)
Values are read as formatted, i.e. exactly as shown in the sheet.

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
import os
from pathlib import Path

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
        sid, gid = parse_url(url)
        title = self.tab_title(sid, gid)
        rng = "'" + title.replace("'", "''") + "'"
        data = self._get(f"{API}/{sid}/values/{rng}",
                         valueRenderOption="FORMATTED_VALUE", majorDimension="ROWS")
        return data.get("values", [])


def tidy(text_or_rows, delimiter=","):
    src = (csv.reader(io.StringIO(text_or_rows), delimiter=delimiter)
           if isinstance(text_or_rows, str) else text_or_rows)
    rows = [[unicodedata.normalize("NFC", str(c).replace("\u00a0", " ")).strip() for c in r]
            for r in src]
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
        sys.exit("sources.json has no tab URLs yet: paste each tab URL (ending in #gid=...).")

    sheets = Sheets()
    fetched, failed = [], []
    for t in tabs:
        try:
            fetched.append((t["path"], *tidy(sheets.fetch(t["url"]))))
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
