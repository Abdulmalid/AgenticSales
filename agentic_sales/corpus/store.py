"""Domain-scoped retrieval over the built corpus index."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .families import BY_NAME, DOMAINS
from .repair import repair_keys

_TOKEN = re.compile(r"[\w₦']+", re.UNICODE)
_STOP = frozenset("the a an and or of to in on is it for this that how what i you me my we are be do "
                  "does can with at by as from".split())


@dataclass(frozen=True)
class Hit:
    id: int
    domain: str
    layer: str | None
    title: str
    register: str | None
    channel: str | None
    score: float
    record: dict  # full record from the raw file, with corrupted keys repaired
    family: str = ""
    platform: str | None = None
    surface: str | None = None
    objective: str | None = None


def to_fts_query(text: str, max_terms: int = 12) -> str:
    """Turn arbitrary (untrusted) text into a safe FTS5 OR-query.

    Every term is double-quoted so FTS5 operators in customer text (NEAR, AND, *, :)
    cannot change query semantics.
    """
    seen, terms = set(), []
    for tok in _TOKEN.findall(text.lower()):
        if len(tok) < 2 or tok in _STOP or tok in seen:
            continue
        seen.add(tok)
        terms.append(f'"{tok}"')
        if len(terms) >= max_terms:
            break
    return " OR ".join(terms)


class CorpusStore:
    def __init__(self, index_path: Path, raw_dir: Path):
        if not index_path.exists():
            raise FileNotFoundError(
                f"{index_path} not found. Build it: python -m agentic_sales.corpus.build")
        self._con = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._raw = raw_dir

    _EXACT = ("register", "channel", "platform", "surface", "objective", "region", "family")

    def search(self, domain: str, query: str, limit: int = 5, *, layer_prefix: str | None = None,
               industry: str | None = None, **exact: str | None) -> list[Hit]:
        """BM25 search inside one knowledge domain.

        Exact-match facet filters (None = ignore): register, channel, platform, surface,
        objective, region, family. `industry` matches any of a record's industries.
        """
        if domain not in DOMAINS:
            raise ValueError(f"unknown domain {domain!r}")
        bad = set(exact) - set(self._EXACT)
        if bad:
            raise ValueError(f"unknown filter(s): {sorted(bad)}")
        match = to_fts_query(query)
        if not match:
            return []
        sql = ("SELECT d.*, bm25(fts, 5.0, 1.0, 3.0) AS s FROM fts JOIN docs d ON d.id = fts.rowid "
               "WHERE fts MATCH ? AND d.domain = ?")
        args: list = [match, domain]
        for col, val in exact.items():
            if val:
                sql += f" AND d.{col} = ?"  # col is whitelisted above
                args.append(val)
        if layer_prefix:
            sql += " AND d.layer LIKE ?"
            args.append(layer_prefix + "%")
        if industry:
            sql += " AND d.industries LIKE ?"
            args.append(f"%|{industry}|%")
        sql += " ORDER BY s LIMIT ?"
        args.append(limit)
        return [self._hit(r) for r in self._con.execute(sql, args)]

    def _hit(self, r: sqlite3.Row) -> Hit:
        with (self._raw / r["src_file"]).open("rb") as fh:
            fh.seek(r["offset"])
            rec = json.loads(fh.read(r["length"]))
        fam = BY_NAME.get(r["family"])
        if fam is not None:
            rec, _extras = repair_keys(rec, fam)
        return Hit(r["id"], r["domain"], r["layer"], r["title"], r["register"], r["channel"],
                   -r["s"], rec, r["family"], r["platform"], r["surface"], r["objective"])

    def close(self) -> None:
        self._con.close()

    def report(self) -> list[dict]:
        return [dict(r) for r in self._con.execute("SELECT * FROM build_report")]
