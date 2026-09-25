# Sifthound vs Tavily benchmark

Compares Sifthound's `/search` with Tavily's on the same queries, so the numbers can be checked
by anyone.

## Method

- **Same client and arguments for both.** Requests go through the official `tavily-python`
  client; only `api_base_url` differs. Each query runs at `basic` and `advanced` depth with
  `max_results=5`, and queries alternate which service goes first.
- **45 queries** in [`queries.jsonl`](queries.jsonl):
  - 25 **factual** questions with a known answer: is the answer in the returned content, and
    in the top 3?
  - 10 **docs** questions with an official documentation site: is that site among the results?
  - 5 **news** and 5 **open-ended** queries: result counts and overlap only
- **Also measured:** client-side latency (median, 95th percentile), errors, URL and domain
  overlap between the two services (Jaccard), and Tavily's cost (1 credit per basic search, 2
  per advanced, at the pay-as-you-go price).

## Running it

```bash
pip install -r bench/requirements.txt
docker compose up -d                                  # Sifthound + SearXNG on localhost:8000
TAVILY_API_KEY=tvly-... python bench/run.py --delay 6
python bench/report.py bench/results/<timestamp>      # writes REPORT.md in that directory
```

`--services sifthound` runs without a Tavily key; `--limit N` runs the first N queries. A full
run makes 180 requests and uses about 135 Tavily credits (the free plan has 1,000 a month).

Results go to `bench/results/`, which is git-ignored: the raw responses contain third-party web
content, so only aggregate numbers are published.

## Caveats

- **Pace the run.** SearXNG's upstream engines rate-limit or CAPTCHA an IP that searches a lot.
  A burst of about 70 searches in 2.5 minutes got every default engine blocked, and Google
  CAPTCHA'd a home IP even at one Sifthound search every ~15 seconds. Keep `--delay` at 6 or
  more, check which engines are failing (Sifthound logs them) and report it with the results.
- **Small samples.** 25 factual and 10 docs queries show a direction, not a significant
  difference of one or two queries.
- **Latency includes the network path:** Sifthound usually runs locally, Tavily over the
  internet.
- **A snapshot.** Both services' results change over time; date every published run.
