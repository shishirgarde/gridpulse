---
license: apache-2.0
tags:
- time-series-forecasting
- electricity
- pytorch
- chronos
- tcn
- ensemble
---

# GridPulse Ensemble v1

> This is the model card published with the Hugging Face model bundle; the weekly-naive reference row was added afterwards. Source and research: this repository.

Seven-day electricity-supplied forecasting for Delhi, India.

## Architecture

A frozen 50/50 ensemble of:

1. Amazon Chronos-2 with a calendar-only LoRA adapter.
2. A lightweight Temporal Convolutional Network trained from scratch.

The Chronos-2 branch uses historical electricity supplied
and calendar features.

The TCN branch uses historical electricity supplied, future
temperature forecasts, calendar features, and availability masks.

Both models predict the next seven daily electricity-supplied
values in million units (MU).

## Evaluation

| Model | 2024 MAE | 2025–2026 MAE | 2025–2026 RMSE |
|---|---:|---:|---:|
| Weekly naive (reference) | 8.4486 | 9.9387 | 13.8306 |
| Chronos-2 calendar LoRA | 6.8693 | 7.7173 | 11.0767 |
| TCN | 7.2733 | 9.0218 | 11.4240 |
| 50/50 Ensemble | 6.0547 | 7.4817 | 9.8990 |

The external evaluation covers 617 rolling forecast origins and
4,319 origin-horizon prediction pairs.

The ensemble weights were selected using 2024 validation data
and frozen before the 2025–2026 evaluation.

## Input contract

- Forecast-origin date
- Exactly 56 chronological daily electricity observations (MU)
- Exactly seven daily temperature forecasts, ordered by target date
- Each temperature forecast contains mean, maximum, and minimum values in °C

The model returns seven daily predictions from each component
and their 50/50 ensemble.

## Limitations

- Intended for Delhi electricity supplied, not unrestricted
  underlying electricity demand.
- Validation uses overlapping rolling forecasts.
- Historical GFS weather forecasts come from Open-Meteo's
  Previous Runs API. Exact forecast issuance and publication
  times were not independently verified.
- Historical backtesting is not equivalent to live deployment.
- Performance may deteriorate under distribution shift.
- This is a research prototype, not an operational grid-control system.

## Reproducibility

The repository contains:

- Chronos-2 LoRA adapter
- TCN checkpoint and saved normalization parameters
- Python inference implementation
- Ensemble metadata
- Dependency manifest

The Chronos-2 base model is loaded separately from
`amazon/chronos-2`.

See `gridpulse/inference.py` for the inference interface.

## Research status

Training and historical external evaluation are complete.
Live operational performance has not been established.
