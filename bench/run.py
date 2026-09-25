"""Run the Sifthound vs Tavily search benchmark.

Both services are called with the official tavily-python client and identical arguments;
only the base URL differs. Queries alternate which service goes first, and every request is
timed from the client side.

    pip install -r bench/requirements.txt
    TAVILY_API_KEY=tvly-... python bench/run.py            # both services
    python bench/run.py --services sifthound               # Sifthound only (no key needed)

Raw responses (third-party web content) are written to bench/results/<timestamp>/, which is
git-ignored. Run bench/report.py on that directory to compute the published metrics.
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from tavily import TavilyClient

HERE = Path(__file__).parent


def load_queries(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def clients(services: list[str], sifthound_url: str, sifthound_key: str) -> dict[str, TavilyClient]:
    out = {}
    if "tavily" in services:
        key = os.environ.get("TAVILY_API_KEY")
        if not key:
            raise SystemExit("TAVILY_API_KEY is not set (or pass --services sifthound)")
        out["tavily"] = TavilyClient(api_key=key)
    if "sifthound" in services:
        out["sifthound"] = TavilyClient(api_key=sifthound_key, api_base_url=sifthound_url)
    return out


def search(client: TavilyClient, q: dict, depth: str, max_results: int) -> dict:
    kwargs = {"search_depth": depth, "max_results": max_results}
    if q.get("topic"):
        kwargs["topic"] = q["topic"]
    if q.get("time_range"):
        kwargs["time_range"] = q["time_range"]
    start = time.perf_counter()
    try:
        resp = client.search(q["query"], **kwargs)
        error = None
    except Exception as e:  # count any failure, keep going
        resp, error = None, f"{type(e).__name__}: {e}"[:300]
    return {
        "latency_s": round(time.perf_counter() - start, 3),
        "error": error,
        "results": [
            {
                "url": r.get("url"),
                "title": r.get("title"),
                "content": r.get("content"),
                "score": r.get("score"),
                "published_date": r.get("published_date"),
            }
            for r in (resp or {}).get("results", [])
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--services", nargs="+", default=["sifthound", "tavily"])
    parser.add_argument("--depths", nargs="+", default=["basic", "advanced"])
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--queries", type=Path, default=HERE / "queries.jsonl")
    parser.add_argument("--sifthound-url", default="http://localhost:8000")
    parser.add_argument("--sifthound-key", default=os.environ.get("SIFTHOUND_API_KEY", "none"))
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    parser.add_argument("--limit", type=int, help="only the first N queries (for a dry run)")
    args = parser.parse_args()

    queries = load_queries(args.queries)[: args.limit]
    services = clients(args.services, args.sifthound_url, args.sifthound_key)
    out_dir = HERE / "results" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True)
    (out_dir / "meta.json").write_text(
        json.dumps(
            {
                "started_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                "services": list(services),
                "depths": args.depths,
                "max_results": args.max_results,
                "queries": len(queries),
                "sifthound_url": args.sifthound_url,
            },
            indent=2,
        )
    )

    total = len(queries) * len(args.depths) * len(services)
    done = 0
    with (out_dir / "raw.jsonl").open("w") as raw:
        for i, q in enumerate(queries):
            for depth in args.depths:
                order = list(services)
                if i % 2:  # alternate who goes first so neither gets a systematic head start
                    order.reverse()
                for name in order:
                    result = search(services[name], q, depth, args.max_results)
                    raw.write(
                        json.dumps({"id": q["id"], "service": name, "depth": depth, **result})
                    )
                    raw.write("\n")
                    raw.flush()
                    done += 1
                    status = result["error"] or f"{len(result['results'])} results"
                    print(f"[{done}/{total}] {q['id']} {depth:8} {name:9} "
                          f"{result['latency_s']:6.2f}s  {status}")  # fmt: skip
                    time.sleep(args.delay)
    print(f"\nRaw results: {out_dir}\nNext: python bench/report.py {out_dir}")


if __name__ == "__main__":
    main()
