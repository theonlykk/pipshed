This message has a line count at the bottom

# RAILWAY SERVICES -- HOW EACH ONE STARTS

The start commands live in Railway (service -> Settings -> Deploy ->
Custom Start Command), NOT in this repo. Do not add a `railway.toml` or a
`Procfile` to fix that: every service below builds from this one repo,
and a repo-level config would also apply to `archive-worker` (which is
not a web server). This file is the record; check it against Railway
after any service is duplicated or rebuilt.

| service | domain | start command | since |
|---|---|---|---|
| pipshed | pipshed.com (all EA pushes, archive intake, A's page) | `gunicorn app:app --bind 0.0.0.0:8080 --workers 4 --threads 8 --timeout 30 --keep-alive 5` | 2 Oct 2026 ~14:27Z |
| pipshed Copy | linux.pipshed.com (Fleet B page) | `gunicorn app:app --bind 0.0.0.0:8080 --workers 2 --threads 8 --timeout 30 --keep-alive 5` | 2 Oct 2026 ~15:00Z |
| pipshed Fleet C | linuxc.pipshed.com | as pipshed Copy | 2 Oct 2026 ~15:00Z |
| pipshed Fleet D | linuxd.pipshed.com | as pipshed Copy | 2 Oct 2026 ~15:00Z |
| archive-worker | (none) | `python archive_worker.py` | ADR-130 |

All four web services previously ran `flask run --host=0.0.0.0 --port=8080`
(Flask's development server).

## WHY (2 OCT 2026 OUTAGE)

The development server starts one thread per request, has no request
timeout and runs on one core. On 2 Oct pipshed.com slowed from ~10:00Z,
the EAs abandoned posts at their 200 ms WebRequest timeout and re-sent
the same, growing archive batches every 2 s; cut-off bodies were
answered 400, threads piled up (memory 6.5 GB, CPU pinned at 1 vCPU) and
it died at 12:14Z with `RuntimeError: can't start new thread`. A restart
relapsed within ten minutes. Under gunicorn (4 workers x 8 threads) the
backlog drained in ~8 minutes at ~4 vCPU, then 0.5-1.5 vCPU, ~0.75 GB,
all 2xx. No archive rows were lost (the EAs keep failed batches queued).

`app.py` is safe under several worker processes: no background threads
at import and no per-process caches (each worker opens its own Redis
client at import).

## RULES

- Port 8080 is what the public domains route to: keep `--bind
  0.0.0.0:8080`.
- Changing a start command redeploys that service; a page service can
  be changed at any time, pipshed.com not at 20:50-21:00Z (the nightly
  carry pass posts) and never while it is the only thing holding an
  outage's backlog.
- If a deploy fails to boot, put the previous command back.

Line count: 49
