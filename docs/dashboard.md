# Dashboard

A dependency-light dashboard (Python standard library HTTP server, plus `requests`, `python-dotenv`, and `xlrd`; plain HTML/CSS/JS with no build step). The same code runs locally and, wrapped in FastAPI, on Modal.

```bash
pip install -e .
python dashboard/dashboard.py        # http://127.0.0.1:8050   (set GRIDPULSE_PORT to change)
```

Set `GRIDPULSE_DATA_DIR` to read and write archives somewhere other than `data/`.

## What the page shows

- **Overview cards:** latest observation, 7-day forecast average, forecast peak, and the historical holdout MAE (clearly labelled as *not* live accuracy).
- **Demand outlook:** 14 or 56 days of observed demand, followed by the 7-day ensemble forecast. Chronos-2 and TCN components can be toggled on.
- **Daily detail:** per-day predictions from each model, with the weather inputs.
- **Input health:** demand freshness, context window, weather coverage, issue and retrieval times.
- **Track record:** for the last seven completed days, the archived forecast against the reported actual, with an optional fixed horizon (D+1 … D+7). Only forecasts issued *before* the target day began (IST) qualify. Nothing is backfilled, and days without an eligible forecast stay empty.

## Behaviour and safeguards

- Opening the page reads the latest valid archive and makes no model call. **Refresh** (local only) fetches demand and weather, validates them, calls the Modal endpoint, and writes a new archive atomically. Concurrent refreshes are rejected, and a failed refresh keeps the previous forecast.
- The browser receives an explicit allow-list of fields. Credentials and the filesystem are never served. Responses carry `Content-Security-Policy`, `X-Content-Type-Options` and `Cache-Control: no-store` headers.
- `POST` endpoints require a custom header and reject cross-site requests. The local server binds to `127.0.0.1` only.
- Actuals come directly from Grid-India's official Daily PSP report-listing API and XLS downloads. There is no Grid-Sentinel, browser, or local scheduler dependency in the hosted pipeline.
- The first actuals update downloads up to 56 completed-day XLS reports. Subsequent updates download only new or revised reports, as identified by the listing's URL, file ID, and modification time. The reporting date must be the observation day plus one, and Delhi's value must come from the state table's **Energy Met (MU)** column; missing or ambiguous cells are rejected, not filled.
- Actuals and report provenance are cached atomically in `data/dashboard_actuals.json`; content-addressed raw XLS reports are retained in `data/grid_india_reports/`. Both are git-ignored. A legacy CSV cache is rebuilt from official reports. If ingestion fails, the previous cache remains available and the page reports the failure.
- The track record shows both the retrieval timestamp and the latest observation day. A recent retrieval does not mean the publisher has supplied yesterday's actuals.

## Caveats

Energy met can differ from unconstrained demand, and sources may revise values. Weather is one Delhi coordinate. Point forecasts carry no uncertainty band. The local dashboard does not schedule forecasts, so refresh daily or use the hosted version to build a track record.
