# GitHub Stars Crawler

Crawls 100,000 public repositories with the GitHub GraphQL API, snapshots their star count into Postgres, and ships a CSV artifact in a GitHub Actions run.

---
## Quick‑start (local)
```bash
# 1 · spin up env, Postgres & run migrations
$ make bootstrap

# 2 · run unit + integration tests
$ make test

# 3 · crawl 100000 repos (requires $GITHUB_TOKEN, either export or put in .env)
$ . .venv/bin/activate && \
  uv run crawl-stars --limit 100000

# 4 · export star snapshots to CSV
$ psql "$DATABASE_URL" -c "\copy repo_star_snapshots to stars.csv csv"
```

---
## Schema
| `repositories` | slow‑changing metadata | `id` | 1 row per repo |
| `repo_star_snapshots` | append‑only star totals | `(repo_id,snapshot_date)` | daily snapshot; partition‑ready |

Write‑paths are bulk‐batched; updates touch ≤ 1 row (metadata) or append 1 row (snapshot) -> minimal churn.

### Future evolution
Add one table per entity type, mirror GitHub IDs:
```sql
issues(id PK, repo_id FK,…);
issue_comments(id PK, issue_id FK,…);
pr_reviews(id PK, pr_id FK,…);
```

---
## Performance
* **Batch**: 100 (repos/request – GitHub GraphQL max). Batch queries by date because GitHub will not let you paginate over 1000 repos at once, so searches should always have less than 1000 items.
* **Async Requests** Concurrency of 3, need to be careful not to hit secondary rate limits.
* **Token‑bucket**: capacity = 995, refill = 5 000 pts / h. Token bucket is tuned for maximal throughput possible with GitHub API.
* **Throughput**: 5000 API requests per hour, so fastest possible crawl of 100k is 12 min (not including request latency, writing to DB, or requests with less than 100 items in the response). This crawled 100k repos in 15 min.
* **Retries**: exponential back‑off on network/5xx; respects `Retry‑After`.

---
## CI pipeline (`.github/workflows/crawl.yml`)
1. Checkout → install uv + deps.
2. Postgres service + `alembic upgrade head`.
3. `crawl-stars --limit 100000`.
4. Export `stars.csv` -> upload artifact.


---
## Scaling to 500 M repos (outline)
1. **Sharding** – split by star range & creation year; run pods per shard
2. **GitHub App** – each installation adds a 5 000 pts/h (or more depending on plan) budget
3. **Stream ingest** – queue snapshots with Kafka -> Postgres (COPY) or column‑store
4. **Partitioning** – `repo_star_snapshots PARTITION BY RANGE(snapshot_date)`
5. **Async workers** – 100+ workers behind a rate‑limit service per token

---
## Engineering decisions
* **Anti‑corruption adapters** isolate GraphQL & SQL
* **Immutability** – star snapshots are append‑only; idempotent upserts elsewhere
* **Separation of concerns** via packages: `core/`, `api/`, `db/`
* **hatchling + uv** for fast builds
* **Retry & rate‑limit** baked into the GitHub adapter; DAL is also wrapped in transactions

---
## Running daily
Add a cron trigger to `crawl.yml`:
```yaml
on:
  schedule:
    - cron: '15 3 * * *'  # every day 03:15 UTC
```