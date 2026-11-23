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
modal deploy deploy/modal_dashboard.py   # → dashboard URL; activates the daily schedule
```

If your inference URL differs from the default, update `DEFAULT_URL` in `src/gridpulse/gridpulse_client.py`.

Seed the hosted archive from `data/forecasts/` and optionally request a forecast now:

```bash
modal run deploy/modal_dashboard.py --seed --refresh
```

Seeding never overwrites remote files, so re-running it with the same filenames fails. Once hosted, the local and remote archives are independent.

## How the daily job behaves

- Only one writer container runs at a time. It skips inference if a valid forecast was already issued that IST calendar day, but still updates actuals.
- Inputs are validated: 56 consecutive demand days, the latest at most 4 days old, and seven aligned weather days. Missing values are never filled in.
- Writes are atomic. A failed run keeps the previous forecast, commits whatever actuals it fetched, and retries twice, 60 s apart.
- The Volume `gridpulse-dashboard-history` (mounted at `/history`) holds `forecasts/*.json` and `dashboard_actuals.json`. Readers reload the Volume before every request.

## Model bundle

The inference app downloads `shishirgarde/gridpulse-ensemble-v1` at a pinned commit (`REVISION` in `deploy/modal_inference.py`). The bundle contains the files committed here under `models/` plus `src/gridpulse/inference.py` and `tcn_model.py`; [`model_card.md`](model_card.md) is its README. To ship a new model, upload a new revision and update `REVISION`.

## Costs and shutting down

Both apps scale to zero. You pay for the daily job, cold starts when someone visits, and storage. No GPU is used. To stop everything, stop the `gridpulse-dashboard` app in Modal (the schedule stops with it) and keep the Volume if you want the history. The inference app is separate.
