# Deployment on Modal

GridPulse runs as two independent Modal apps.

| App | File | What it does | Secrets |
|---|---|---|---|
| `gridpulse-ensemble-v1` | `deploy/modal_inference.py` | `POST` endpoint `gridpulse-predict` behind **Modal proxy auth**. Loads the model bundle from Hugging Face at a pinned revision on container start (CPU, 4 vCPU / 8 GB). | `huggingface-secret` (`HF_TOKEN`) |
| `gridpulse-dashboard` | `deploy/modal_dashboard.py` | Public read-only dashboard (FastAPI), plus `daily_refresh`, a cron job at **14:30 Asia/Kolkata** that fetches inputs, calls the endpoint, and archives the result to a Volume. | `gridpulse-dashboard-proxy` (`MODAL_PROXY_KEY`, `MODAL_PROXY_SECRET`) — attached to the scheduled writer only |

Live dashboard: https://shishir-garde--gridpulse-dashboard.us-east.modal.run/

## One-time setup

```bash
pip install -e ".[deploy]"
modal token new                                  # authenticate the CLI
```

1. **Hugging Face secret.** In Modal → Secrets, create `huggingface-secret` with `HF_TOKEN`. The token needs read access to the model repo.
2. **Proxy-auth token.** In Modal → Settings → Proxy Auth Tokens, create a token. Store it in a Modal Secret named `gridpulse-dashboard-proxy` with keys `MODAL_PROXY_KEY` and `MODAL_PROXY_SECRET`. Put the same values in your local `.env` (see `.env.example`) if you want to refresh from the local dashboard. Never commit `.env` or pass the values on the command line.

## Deploy

Run from the repository root:

```bash
modal run    deploy/modal_inference.py   # smoke test: loads the models, predicts on synthetic input
modal deploy deploy/modal_inference.py   # → https://<workspace>--gridpulse-predict.<region>.modal.run
modal run deploy/modal_dashboard.py --check-source  # verify official API/XLS ingestion inside Modal
modal deploy deploy/modal_dashboard.py   # → dashboard URL; activates the daily schedule
```

`--check-source` uses temporary container storage, no proxy secret, and no history Volume.
It verifies 56 consecutive, current official observations and a second cached sync before
returning the latest actuals. It does not publish forecasts, change hosted data, or deploy
the app. When updating only the dashboard, leave the inference app deployed as it is and
run the dashboard source check before deploying.

On Windows terminals using a legacy encoding, set `$env:PYTHONUTF8="1"` in PowerShell
before invoking the Modal CLI so its progress output can be printed.

If your inference URL differs from the default, update `DEFAULT_URL` in `src/gridpulse/gridpulse_client.py`.

Seed the hosted archive from `data/forecasts/` and optionally request a forecast now:

```bash
modal run deploy/modal_dashboard.py --seed --refresh
```

Seeding never overwrites remote files, so re-running it with the same filenames fails. Once hosted, the local and remote archives are independent.

## How the daily job behaves

- Only one writer container runs at a time. It skips inference if a valid forecast was already issued that IST calendar day, but still updates actuals.
- Demand is fetched directly from Grid-India, not Grid-Sentinel: `POST https://webapi.grid-india.in/api/v1/file` with `_source=GRDW`, `_type=DAILY_PSP_REPORT`, `_fileDate=YYYY-YY` (financial year), and `_month=00`. XLS `FilePath` values are downloaded from `https://webcdn.grid-india.in/`. These are unauthenticated website-backing APIs, not a guaranteed stable public API contract.
- The source check and scheduled writer run in **Mumbai (`ap-south`)**. A US-container source check encountered a connection reset during the Grid-India API's TLS handshake; the Mumbai check successfully fetched all 56 reports. Keep both functions in the same tested source region. The public web function and its URL are unchanged. Modal's narrow-region compute pricing multiplier applies to the writer and source check.
- `xlrd` parses the reports inside Modal; no browser, Playwright, local downloader, or GitHub data-update workflow is required. The initial run downloads up to 56 reports (including the preceding financial year when needed); later runs reuse validated reports unless their listing metadata changes. Missing observations remain missing.
- Inputs are validated: 56 consecutive demand days, the latest at most 4 days old, and seven aligned weather days. Missing values are never filled in.
- Writes are atomic. A failed run keeps the previous forecast, commits whatever actuals it fetched, and retries twice, 60 s apart.
- The Volume `gridpulse-dashboard-history` (mounted at `/history`) holds `forecasts/*.json`, `dashboard_actuals.json` (values, source URLs, revision metadata, and SHA-256 hashes), and `grid_india_reports/*.xls` (immutable raw report versions). Readers reload the Volume before every request.
- API, download, parser, and forecast errors remain visible in the scheduled function's exception chain. Check its Modal logs if the retrieval timestamp stops advancing. Reading the dashboard never initiates ingestion.

## Model bundle

The inference app downloads `shishirgarde/gridpulse-ensemble-v1` at a pinned commit (`REVISION` in `deploy/modal_inference.py`). The bundle contains the files committed here under `models/` plus `src/gridpulse/inference.py` and `tcn_model.py`; [`model_card.md`](model_card.md) is its README. To ship a new model, upload a new revision and update `REVISION`.

## Costs and shutting down

Both apps scale to zero. You pay for the daily job, cold starts when someone visits, and storage. No GPU is used. To stop everything, stop the `gridpulse-dashboard` app in Modal (the schedule stops with it) and keep the Volume if you want the history. The inference app is separate.
