"""Compute benchmark metrics from a bench/run.py results directory and write REPORT.md there.

    python bench/report.py bench/results/<timestamp>

Metrics (per service and search depth):
- latency: median and 95th percentile of client-side request time
- errors: failed requests
- answer found: factual queries whose known answer appears in the returned content,
  anywhere in the results and within the top 3
- docs hit: docs queries whose official documentation site is among the returned results
- overlap: how many URLs and domains the two services have in common per query (Jaccard)
- cost: Tavily credits (basic 1, advanced 2 per search) at pay-as-you-go $0.008 per credit

The report contains only these numbers and per-query scores, not the returned content.
"""

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).parent
TAVILY_CREDITS = {"basic": 1, "advanced": 2}
TAVILY_USD_PER_CREDIT = 0.008  # pay-as-you-go, docs.tavily.com/documentation/api-credits


def norm_url(url: str) -> str:
    parts = urlsplit(url or "")
    host = (parts.hostname or "").removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}".lower()


def domain(url: str) -> str:
    return (urlsplit(url or "").hostname or "").removeprefix("www.").lower()


def jaccard(a: set, b: set) -> float | None:
    return len(a & b) / len(a | b) if a | b else None


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


def found(expect: list[str], results: list[dict], top: int | None = None) -> bool:
    text = " ".join(
        f"{r.get('title') or ''} {r.get('content') or ''}" for r in results[:top]
    ).casefold()
    return any(e.casefold() in text for e in expect)


def docs_hit(expected: str, results: list[dict]) -> bool:
    return any(domain(r["url"]) == expected or domain(r["url"]).endswith("." + expected)
               for r in results)  # fmt: skip


def main(run_dir: Path) -> None:
    queries = {
        q["id"]: q for q in map(json.loads, (HERE / "queries.jsonl").read_text().splitlines()) if q
    }
    meta = json.loads((run_dir / "meta.json").read_text())
    rows = [json.loads(line) for line in (run_dir / "raw.jsonl").read_text().splitlines()]
    by = defaultdict(dict)  # (depth, id) -> service -> row
    for r in rows:
        by[(r["depth"], r["id"])][r["service"]] = r

    # Only the queries that were actually run (run.py --limit runs a subset).
    queries = {qid: q for qid, q in queries.items() if any(r["id"] == qid for r in rows)}
    services, depths = meta["services"], meta["depths"]
    out = [
        "# Sifthound vs Tavily: search benchmark",
        "",
        f"Run {meta['started_utc']} · {meta['queries']} queries · max_results "
        f"{meta['max_results']} · same `tavily-python` client for both, only the base URL "
        "differs · queries alternate which service goes first.",
        "",
    ]

    summary_header = (
        "| Metric | " + " | ".join(f"{s} ({d})" for d in depths for s in services) + " |"
    )
    lines = {k: [] for k in ["lat50", "lat95", "err", "fact", "fact3", "docs", "count", "cost"]}
    per_query = []
    for depth in depths:
        for s in services:
            rs = [by[(depth, qid)].get(s) for qid in queries if by[(depth, qid)].get(s)]
            ok = [r for r in rs if not r["error"]]
            lat = [r["latency_s"] for r in ok]
            fact = [(queries[r["id"]], r) for r in ok if queries[r["id"]]["kind"] == "factual"]
            docs = [(queries[r["id"]], r) for r in ok if queries[r["id"]]["kind"] == "docs"]
            # Denominators include failed requests: an error counts as not found.
            n_fact = sum(queries[r["id"]]["kind"] == "factual" for r in rs)
            n_docs = sum(queries[r["id"]]["kind"] == "docs" for r in rs)
            lines["lat50"].append(f"{statistics.median(lat):.2f}s" if lat else "—")
            lines["lat95"].append(f"{pct(lat, 0.95):.2f}s" if lat else "—")
            lines["err"].append(f"{len(rs) - len(ok)} / {len(rs)}")
            f_any = sum(found(q["expect"], r["results"]) for q, r in fact)
            f_top3 = sum(found(q["expect"], r["results"], top=3) for q, r in fact)
            lines["fact"].append(f"{f_any} / {n_fact}")
            lines["fact3"].append(f"{f_top3} / {n_fact}")
            lines["docs"].append(
                f"{sum(docs_hit(q['expect_domain'], r['results']) for q, r in docs)} / {n_docs}"
            )
            lines["count"].append(
                f"{statistics.mean(len(r['results']) for r in ok):.1f}" if ok else "—"
            )
            if s == "tavily":
                usd = TAVILY_CREDITS[depth] * TAVILY_USD_PER_CREDIT * 1000
                lines["cost"].append(f"${usd:.0f}")
            else:
                lines["cost"].append("$0 + your server")

    labels = {
        "lat50": "Median latency",
        "lat95": "95th percentile latency",
        "err": "Errors",
        "fact": "Factual: answer in results",
        "fact3": "Factual: answer in top 3",
        "docs": "Docs: official site in results",
        "count": "Avg. results returned",
        "cost": "Cost per 1,000 searches",
    }
    out += ["## Summary", "", summary_header, "|---" * (1 + len(depths) * len(services)) + "|"]
    out += [f"| {labels[k]} | " + " | ".join(v) + " |" for k, v in lines.items()]

    if {"sifthound", "tavily"} <= set(services):
        out += ["", "## Overlap between the two services", ""]
        out += [
            "| Depth | Same URLs (median Jaccard) | Same domains (median Jaccard) |",
            "|---|---|---|",
        ]
        for depth in depths:
            u, d = [], []
            for qid in queries:
                pair = by[(depth, qid)]
                a, b = pair.get("sifthound"), pair.get("tavily")
                if not a or not b or a["error"] or b["error"]:
                    continue
                ju = jaccard({norm_url(r["url"]) for r in a["results"]},
                             {norm_url(r["url"]) for r in b["results"]})  # fmt: skip
                jd = jaccard({domain(r["url"]) for r in a["results"]},
                             {domain(r["url"]) for r in b["results"]})  # fmt: skip
                if ju is not None:
                    u.append(ju)
                    d.append(jd)
            out.append(
                f"| {depth} | {statistics.median(u):.2f} | {statistics.median(d):.2f} |"
                if u
                else f"| {depth} | — | — |"
            )

    out += ["", "## Per query", "", "| Query | Kind | " + " | ".join(
        f"{s} ({d})" for d in depths for s in services) + " |"]  # fmt: skip
    out.append("|---" * (2 + len(depths) * len(services)) + "|")
    for qid, q in queries.items():
        cells = []
        for depth in depths:
            for s in services:
                r = by[(depth, qid)].get(s)
                if not r:
                    cells.append("—")
                elif r["error"]:
                    cells.append("error")
                elif q["kind"] == "factual":
                    cells.append(("✓" if found(q["expect"], r["results"]) else "✗")
                                 + f" {r['latency_s']:.1f}s")  # fmt: skip
                elif q["kind"] == "docs":
                    cells.append(("✓" if docs_hit(q["expect_domain"], r["results"]) else "✗")
                                 + f" {r['latency_s']:.1f}s")  # fmt: skip
                else:
                    cells.append(f"{len(r['results'])} results {r['latency_s']:.1f}s")
        per_query.append(f"| {q['query']} | {q['kind']} | " + " | ".join(cells) + " |")
    out += per_query
    out += [
        "",
        "Latency is measured from the benchmark machine and includes the network path to each "
        "service: Sifthound ran locally, Tavily over the internet. Sifthound's cost excludes the "
        "server it runs on. Content checks are case-insensitive substring matches on titles and "
        "content.",
    ]
    (run_dir / "REPORT.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python bench/report.py bench/results/<timestamp>")
    main(Path(sys.argv[1]))
