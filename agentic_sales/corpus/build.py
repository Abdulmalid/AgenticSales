"""Build the retrieval index from the raw corpora.

    python -m agentic_sales.corpus.build [--raw data/corpora/raw] [--out data/index/corpus.db]

The raw JSONL files are never modified. The index stores, per document, the byte
offset into the raw file so full records are fetched on demand rather than
duplicated in memory (the old design loaded all ~300MB into every agent).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

from . import facets
from .families import FAMILIES, Family
from .repair import (build_layer_vocabulary, content_hash, flatten_text, repair_keys,
                     repair_layer)

SCHEMA = """
CREATE TABLE docs(
  id INTEGER PRIMARY KEY, domain TEXT NOT NULL, family TEXT NOT NULL, layer TEXT,
  register TEXT, region TEXT, channel TEXT, situation TEXT, platform TEXT, surface TEXT,
  objective TEXT, industries TEXT, report_id TEXT, title TEXT,
  src_file TEXT NOT NULL, offset INTEGER NOT NULL, length INTEGER NOT NULL,
  hash TEXT NOT NULL UNIQUE
);
CREATE INDEX docs_domain ON docs(domain);
CREATE INDEX docs_smm ON docs(domain, platform, objective);
CREATE VIRTUAL TABLE fts USING fts5(title, body, tags, tokenize='porter unicode61 remove_diacritics 2');
CREATE TABLE build_report(family TEXT, read INTEGER, indexed INTEGER, dup INTEGER,
                          bad_json INTEGER, keys_repaired INTEGER, layers_repaired INTEGER,
                          layers_unresolved INTEGER, extras_dropped INTEGER);
"""


def _scan_layers(path: Path) -> list[str | None]:
    layers = []
    with path.open("rb") as fh:
        for raw in fh:
            try:
                layers.append(json.loads(raw).get("knowledge_layer"))
            except (json.JSONDecodeError, AttributeError):
                pass
    return layers


def _meta(family: Family, rec: dict) -> dict:
    """Facet columns for the docs table (None where a family has no such facet)."""
    m: dict = {}
    if family.name == "pidgin":
        m = dict(register=rec.get("register_tier"), region=rec.get("dialect_region"))
    elif family.name == "nigerian_english":
        m = dict(register=rec.get("register_tier"))
    elif family.name == "nigerian_conversation":
        m = dict(situation=rec.get("situational_domain"))
    elif family.name == "guardrails":
        cp = rec.get("customer_profile")
        m = dict(register=cp.get("language_blend") if isinstance(cp, dict) else None,
                 channel=rec.get("commercial_channel"))
    elif family.name in ("meta", "tiktok"):
        cov = rec.get("coverage") if isinstance(rec.get("coverage"), dict) else {}
        nc = rec.get("nigeria_context")
        m = dict(platform=family.name, surface=facets.surface(family.name, cov.get("cell_key")),
                 objective=facets.objective(cov.get("objective")),
                 industries=facets.industries(cov.get("industry")),
                 register=facets.register(nc.get("language_register") if isinstance(nc, dict) else None),
                 region=facets.first_region(nc), situation=cov.get("situation"))
    return m


def index_family(con: sqlite3.Connection, family: Family, raw_dir: Path) -> dict:
    path = raw_dir / family.filename
    stats = dict(family=family.name, read=0, indexed=0, dup=0, bad_json=0, keys_repaired=0,
                 layers_repaired=0, layers_unresolved=0, extras_dropped=0)
    if not path.exists():
        print(f"  ! missing {path}", file=sys.stderr)
        return stats
    vocab = build_layer_vocabulary(_scan_layers(path))
    meta_keys = set(family.meta_keys)
    offset = 0
    with path.open("rb") as fh:
        for raw in fh:
            length, start = len(raw), offset
            offset += length
            if not raw.strip():
                continue
            stats["read"] += 1
            try:
                rec = json.loads(raw)
                assert isinstance(rec, dict)
            except (json.JSONDecodeError, AssertionError):
                stats["bad_json"] += 1
                continue
            fixed, extras = repair_keys(rec, family)
            stats["keys_repaired"] += sum(1 for k in rec if k not in fixed and k not in extras)
            stats["extras_dropped"] += len(extras)
            title = flatten_text(fixed.get("title")).strip()
            body = " ".join(flatten_text(v) for k, v in fixed.items() if k not in meta_keys).strip()
            if not title or len(body) < 40:
                stats["bad_json"] += 1  # unusable: no title / no substance
                continue
            layer = repair_layer(fixed.get("knowledge_layer"), vocab)
            if layer != fixed.get("knowledge_layer"):
                stats["layers_repaired" if layer else "layers_unresolved"] += 1
            digest = content_hash(title, body)
            meta = _meta(family, fixed)
            cols = dict(domain=family.domain, family=family.name, layer=layer, report_id=fixed.get("report_id"),
                        title=title, src_file=family.filename, offset=start, length=length, hash=digest, **meta)
            try:
                cur = con.execute(
                    f"INSERT INTO docs({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    tuple(cols.values()))
            except sqlite3.IntegrityError:
                stats["dup"] += 1
                continue
            tags = flatten_text(fixed.get("tags"))
            con.execute("INSERT INTO fts(rowid,title,body,tags) VALUES(?,?,?,?)",
                        (cur.lastrowid, title, body, tags))
            stats["indexed"] += 1
    return stats


def build(raw_dir: Path, out: Path) -> list[dict]:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    reports = []
    for family in FAMILIES:
        t = time.time()
        print(f"indexing {family.name} ...", flush=True)
        s = index_family(con, family, raw_dir)
        con.execute("INSERT INTO build_report VALUES(?,?,?,?,?,?,?,?,?)", tuple(s.values()))
        con.commit()
        print(f"  {s}  ({time.time() - t:.0f}s)")
        reports.append(s)
    con.execute("INSERT INTO fts(fts) VALUES('optimize')")
    con.commit()
    con.close()
    tmp.replace(out)
    return reports


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/corpora/raw", type=Path)
    ap.add_argument("--out", default="data/index/corpus.db", type=Path)
    a = ap.parse_args()
    build(a.raw, a.out)


if __name__ == "__main__":
    main()
