#!/usr/bin/env python3
"""
Build the Concept Tree site from the exported sheets.

    python3 scripts/build_site.py data -o site

Reads CSV or TSV (by extension; if a configured file is missing, the other
extension is tried). Writes:

    site/index.html, app.js, style.css   (copied from scripts/web/)
    site/data/core.js                    tree, concepts, Amarakosha, dhatus, examples
    site/data/comm.js                    Sudha + Kshirasvamin commentaries (loaded on demand)
    site/report.txt                      data checks

Joins (every table is a plain mapping; nothing is inferred from matching labels):
  tree           leaf path, '::' separates parent and child
  concepts       concept_id -> leaf; merged_into -> concept_id (shown under the target)
  artha_map      (source, artha) -> concept_id         source: ak | dp | sc
  ak words       column अर्थः == ak artha; संख्या -> shlokas; sudha_id / ks_id -> commentaries
  dhatu          dhatu_artha (';'-separated stems) == dp artha
  upasarga-dhatu artha_draft (';'-separated, locative) -> stems == dp artha
                 (an optional 'dhatu_artha' column of stems, if added, is used instead)
  examples/*     concept_id, word, vakya, src, notes, additional notes
"""

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------- file layout (relative to the data folder)
TREE = "wordconcepts/tree.csv"
CONCEPTS = "wordconcepts/concepts.csv"
ARTHA_MAP = "wordconcepts/artha_map.csv"
AK_WORDS = "amarakosha/words.csv"
AK_SHLOKAS = "amarakosha/shlokas.csv"
AK_SUDHA = "amarakosha/sudha.csv"
AK_KS = "amarakosha/ks_words.csv"
DHATU = "dhatukosha/dhatu.csv"
UPASARGA = "dhatukosha/upasarga-dhatu.csv"
EXAMPLES_DIR = "examples"          # every .csv / .tsv in here, same columns

WEB_DIR = Path(__file__).parent / "web"

SEP = "::"
UNDECIDED = "अनिर्णीत"
SOURCES = ("ak", "dp", "sc")
LIST_SEP = ";"                     # inside dhatu_artha / artha_draft cells

# locative ending -> stem ending, tried in order (upasarga artha_draft)
LOCATIVE_RULES = [("ायाम्", "ा"), ("्याम्", "ी"), ("तौ", "ति"), ("ौ", "ि"),
                  ("णि", "न्"), ("नि", "न्"), ("े", "")]


# ---------------------------------------------------------------- reading
def nfc(s):
    return unicodedata.normalize("NFC", s.replace(" ", " ")).strip()


def find(folder, rel, required=True):
    p = folder / rel
    if p.exists():
        return p
    alt = p.with_suffix(".tsv" if p.suffix == ".csv" else ".csv")
    if alt.exists():
        return alt
    if required:
        sys.exit(f"Missing file: {p}")
    return None


def read_rows(path):
    """Rows as dicts keyed by normalised header (lowercase, spaces -> _)."""
    if path is None:
        return []
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open(encoding="utf-8-sig", newline="") as f:
        rdr = csv.reader(f, delimiter=delim)
        rows = [[nfc(c) for c in r] for r in rdr]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    head = [h.lower().replace(" ", "_") for h in rows[0]]
    out = []
    for r in rows[1:]:
        d = {}
        for i, h in enumerate(head):
            if h and h not in d:
                d[h] = r[i] if i < len(r) else ""
        out.append(d)
    return out


def g(row, *names):
    for n in names:
        v = row.get(n.lower().replace(" ", "_"))
        if v:
            return v
    return ""


def split_list(v):
    return [x.strip() for x in v.split(LIST_SEP) if x.strip()]


def loc_to_stem(word):
    for end, rep in LOCATIVE_RULES:
        if word.endswith(end):
            return word[: -len(end)] + rep
    return None


def norm_path(p):
    return SEP.join(x.strip() for x in p.split(SEP)) if p else ""


# ---------------------------------------------------------------- build
def build(folder):
    rep = Report()

    # ---- tree
    nodes, index = [], {}

    def ensure(path, missing=False):
        if path in index:
            return index[path]
        parts = path.split(SEP)
        parent = ensure(SEP.join(parts[:-1]), missing) if len(parts) > 1 else -1
        i = len(nodes)
        nodes.append({"n": parts[-1], "p": path, "pi": parent, "c": [], "k": [],
                      "d": "", "a": "", "x": "", "m": missing})
        index[path] = i
        if parent >= 0:
            nodes[parent]["c"].append(i)
        return i

    seen_tree = set()
    for r in read_rows(find(folder, TREE)):
        path = norm_path(g(r, "leaf"))
        if not path:
            continue
        if path in seen_tree:
            rep.add("Duplicate tree rows", path)
        seen_tree.add(path)
        i = ensure(path)
        nodes[i].update(d=g(r, "definition"), a=g(r, "anchors"), x=g(r, "not_this"))
    for n in nodes:
        if n["p"] not in seen_tree:
            rep.add("Tree paths implied by a child (no row of their own)", n["p"])
        n["m"] = False
    ensure(UNDECIDED)

    # ---- concepts
    concepts, order = {}, []
    for r in read_rows(find(folder, CONCEPTS)):
        cid = g(r, "concept_id")
        if not cid:
            continue
        if cid in concepts:
            rep.add("Duplicate concept_id rows (first kept)", cid)
            continue
        concepts[cid] = {"leaf": norm_path(g(r, "leaf")), "merged": g(r, "merged_into"),
                         "conf": g(r, "confidence"), "note": g(r, "note")}
        order.append(cid)

    def resolve(cid):
        seen, cur = [cid], cid
        while concepts[cur]["merged"]:
            nxt = concepts[cur]["merged"]
            if nxt not in concepts:
                rep.add("merged_into pointing to a missing concept", f"{cur} → {nxt}")
                return cur
            if nxt in seen:
                rep.add("merged_into cycles", " → ".join(seen + [nxt]))
                return cid
            seen.append(nxt)
            cur = nxt
        return cur

    target = {}
    for cid in order:
        target[cid] = resolve(cid)
        if target[cid] != cid:
            rep.add("merged_into redirects", f"{cid} → {target[cid]}")

    # ---- artha_map
    arthas_of = defaultdict(list)
    mapped = {s: set() for s in SOURCES}
    ak_concept = defaultdict(list)          # ak artha -> concept ids (for report hints only)
    for r in read_rows(find(folder, ARTHA_MAP)):
        src, artha, cid = g(r, "source").lower(), g(r, "artha"), g(r, "concept_id", "concept id")
        if not artha:
            continue
        if src not in SOURCES:
            rep.add("artha_map rows with an unknown source", f"{src or '(blank)'}: {artha}")
            continue
        mapped[src].add(artha)
        if src == "ak" and cid:
            ak_concept[artha].append(cid)
        if not cid:
            rep.add("artha_map rows with no concept_id", f"{src}: {artha}")
            continue
        if cid not in concepts:
            rep.add("artha_map rows whose concept_id is not in concepts", f"{src}: {artha} → {cid}")
            continue
        pair = [src, artha]
        if pair not in arthas_of[target[cid]]:
            arthas_of[target[cid]].append(pair)

    # ---- concepts placed on nodes (merge targets only)
    out_c, cidx = [], {}
    for cid in order:
        if target[cid] != cid:
            continue
        info = concepts[cid]
        leaf = info["leaf"]
        if not leaf:
            rep.add(f"Concepts with empty leaf (placed under {UNDECIDED})", cid)
            leaf = UNDECIDED
        if leaf not in index:
            rep.add("Concept leaf not in tree (node shown in red)", f"{cid} → {leaf}")
            ni = ensure(leaf, missing=True)
        else:
            ni = index[leaf]
        ar = arthas_of.get(cid, [])
        if not ar:
            rep.add("Concepts with no arthas", cid)
        k = len(out_c)
        cidx[cid] = k
        out_c.append({"id": cid, "ni": ni, "cf": info["conf"], "nt": info["note"],
                      "mf": [c for c in order if c != cid and target[c] == cid], "ar": ar, "ex": []})
        nodes[ni]["k"].append(k)

    def total(i):
        nodes[i]["t"] = len(nodes[i]["k"]) + sum(total(c) for c in nodes[i]["c"])
        return nodes[i]["t"]
    for i, n in enumerate(nodes):
        if n["pi"] == -1:
            total(i)

    # ---- Amarakosha words (all rows, file order)
    words = []
    ak_arthas = set()
    for r in read_rows(find(folder, AK_WORDS)):
        w = g(r, "प्रातिपदिकम्")
        if not w:
            continue
        artha = g(r, "अर्थः")
        ak_arthas.add(artha)
        kids = [x.strip() for x in g(r, "ks_id").split(",") if x.strip()]
        words.append([w, g(r, "लिङ्गम्"), g(r, "संख्या"), artha, g(r, "id"), g(r, "sudha_id"), kids])
    for a in sorted(mapped["ak"] - ak_arthas):
        rep.add("ak arthas in artha_map with no Amarakosha row (अर्थः)", a)
    for a in sorted(ak_arthas - mapped["ak"]):
        rep.add("New ak arthas: in Amarakosha but not yet in artha_map", a)

    shlokas = {}
    for r in read_rows(find(folder, AK_SHLOKAS)):
        s = g(r, "संख्या")
        if s:
            shlokas[s] = g(r, "श्लोकः")
    missing_sh = sorted({w[2] for w in words if w[2] and w[2] not in shlokas})
    for s in missing_sh:
        rep.add("Amarakosha संख्या with no shloka", s)

    want_s = {w[5] for w in words if w[5]}
    want_k = {k for w in words for k in w[6]}
    sudha = {g(r, "sudha_id"): [g(r, "word"), g(r, "commentary")]
             for r in read_rows(find(folder, AK_SUDHA, required=False)) if g(r, "sudha_id") in want_s}
    ks = {g(r, "ks_id"): [g(r, "word"), g(r, "commentary")]
          for r in read_rows(find(folder, AK_KS, required=False)) if g(r, "ks_id") in want_k}
    for x in sorted(want_s - set(sudha)):
        rep.add("sudha_id in words not found in sudha", x)
    for x in sorted(want_k - set(ks)):
        rep.add("ks_id in words not found in ks_words", x)

    # ---- dhatus
    dhatus, dp_stems = [], set()
    for r in read_rows(find(folder, DHATU)):
        did = g(r, "src_link")
        if not did:
            continue
        stems = split_list(g(r, "dhatu_artha"))
        dp_stems.update(stems)
        dhatus.append({"id": did, "d": g(r, "dhatu"), "au": g(r, "aupadeshika"),
                       "gn": g(r, "gana_name"), "gi": g(r, "gana_index"), "pd": g(r, "pada"),
                       "st": g(r, "settva"), "km": g(r, "karma"), "cm": g(r, "common"),
                       "raw": g(r, "artha"), "hi": g(r, "artha_hindi"), "nt": g(r, "artha_note"),
                       "ar": stems})
    dids = {d["id"] for d in dhatus}

    upas, ukeys = [], Counter()
    for r in read_rows(find(folder, UPASARGA)):
        form, base = g(r, "combined"), g(r, "src_link")
        if not form:
            continue
        explicit = split_list(g(r, "dhatu_artha"))
        raw = split_list(g(r, "artha_draft"))
        if explicit:
            stems = explicit
        else:
            stems = []
            for x in raw:
                s = loc_to_stem(x)
                if s is None:
                    rep.add("upasarga artha_draft not in a known locative form (used as-is)", f"{form}: {x}")
                    s = x
                stems.append(s)
        dp_stems.update(stems)
        ukeys[(form, base)] += 1
        key = f"{form}|{base}" + (f"#{ukeys[(form, base)]}" if ukeys[(form, base)] > 1 else "")
        if ukeys[(form, base)] == 2:
            rep.add("Duplicate upasarga rows (same combined + src_link)", f"{form} ({base})")
        if base not in dids:
            rep.add("upasarga rows whose src_link is not in dhatu", f"{form} ({base})")
        upas.append({"key": key, "f": form, "b": base, "u": g(r, "upasarga"), "bd": g(r, "aupadeshika", "dhatu"),
                     "hi": g(r, "artha_hindi"), "raw": g(r, "artha_draft"), "nt": g(r, "draft_note"),
                     "fl": g(r, "combined_flag"), "ar": stems})
    for a in sorted(mapped["dp"] - dp_stems):
        rep.add("dp arthas in artha_map with no dhatu or upasarga", a)
    for a in sorted(dp_stems - mapped["dp"]):
        rep.add("New dp arthas: in dhatu / upasarga but not yet in artha_map", a)

    # ---- examples
    examples, files = [], []
    ex_dir = folder / EXAMPLES_DIR
    word_set = {w[0] for w in words}
    if ex_dir.is_dir():
        for p in sorted(list(ex_dir.glob("*.csv")) + list(ex_dir.glob("*.tsv"))):
            files.append(p.name)
            for r in read_rows(p):
                cid, vakya = g(r, "concept_id"), g(r, "vakya")
                if not (cid or vakya):
                    continue
                k = -1
                if cid in concepts:
                    k = cidx[target[cid]]
                else:
                    w0 = g(r, "word")
                    hint = sorted({c for wr in words if wr[0] == w0 for c in ak_concept.get(wr[3], [])})
                    rep.add("Examples whose concept_id is not in concepts",
                            f"{p.name}: '{cid}' — {vakya[:40]}"
                            + (f"  (Amarakosha senses of {w0}: {', '.join(hint)})" if hint else ""))
                w = g(r, "word")
                if w and w not in word_set:
                    rep.add("Example words not in Amarakosha (fine for non-kośa words)", f"{w} ({cid})")
                e = len(examples)
                examples.append([k, w, vakya, g(r, "src"), g(r, "notes"), g(r, "additional_notes"), p.stem])
                if k >= 0:
                    out_c[k]["ex"].append(e)

    stats = {
        "Tree nodes": len(nodes), "Concepts shown": len(out_c), "Concepts in file": len(order),
        "merged_into in use": sum(1 for c in order if concepts[c]["merged"]),
        "Arthas by source": ", ".join(f"{s}={sum(1 for c in out_c for x in c['ar'] if x[0] == s)}" for s in SOURCES),
        "Amarakosha rows": len(words), "Shlokas": len(shlokas),
        "Commentary entries": f"sudha={len(sudha)}, ks={len(ks)}",
        "Dhatus": len(dhatus), "Upasarga+dhatu rows": len(upas),
        "Examples": f"{len(examples)} from {len(files)} file(s): {', '.join(files) or '-'}",
    }
    core = {"nodes": nodes, "concepts": out_c, "words": words, "shlokas": shlokas,
            "dhatus": dhatus, "upas": upas, "examples": examples}
    comm = {"s": sudha, "k": ks}
    return core, comm, rep.render(stats)


class Report:
    def __init__(self):
        self.sections = defaultdict(list)

    def add(self, title, item):
        self.sections[title].append(item)

    def render(self, stats):
        out = ["Concept tree build report", "=" * 25, ""]
        out += [f"{k}: {v}" for k, v in stats.items()]
        for title in sorted(self.sections, key=lambda t: (t.startswith("New "), t)):
            items = self.sections[title]
            out += ["", f"## {title} ({len(items)})"] + [f"  - {x}" for x in items]
        return "\n".join(out) + "\n"


# ---------------------------------------------------------------- output
def js_payload(var, obj):
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"window.{var}={body};\n"


def main():
    ap = argparse.ArgumentParser(description="Build the Concept Tree site.")
    ap.add_argument("data", help="data folder (with amarakosha/, wordconcepts/, dhatukosha/, examples/)")
    ap.add_argument("-o", "--out", default="site", help="output folder (default: site)")
    args = ap.parse_args()

    folder, out = Path(args.data), Path(args.out)
    core, comm, report = build(folder)

    (out / "data").mkdir(parents=True, exist_ok=True)
    files = {"data/core.js": js_payload("CT", core), "data/comm.js": js_payload("CT_COMM", comm)}
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    for name in ("app.js", "style.css"):
        shutil.copyfile(WEB_DIR / name, out / name)
    ver = hashlib.sha1("".join(files.values()).encode() + (WEB_DIR / "app.js").read_bytes()).hexdigest()[:10]
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("__V__", ver)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "report.txt").write_text(report, encoding="utf-8")

    print(report)
    print(f"Wrote {out}/index.html (open it in a browser) and {out}/report.txt")


if __name__ == "__main__":
    main()
