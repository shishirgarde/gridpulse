# Research notebooks

Read them in order. Each one opens with its purpose, key results, and a link to the next.

| # | Notebook | Question | Headline |
|---|---|---|---|
| 01 | [Data exploration and baselines](01_data_exploration_and_baselines.ipynb) | Is the data usable? What does "good" mean? | Only 52% of windows usable; weekly naive ≈ 8 MU MAE |
| 02 | [XGBoost baseline](02_xgboost_baseline.ipynb) | How far do lag features go? | −27% vs naive on validation |
| 03 | [Walk-forward validation](03_walk_forward_validation.ipynb) | Does it hold across years? | −12% (2019), −16% (2021) |
| 04 | [Zero-shot Chronos-Bolt](04_zero_shot_chronos_bolt.ipynb) | Do foundation models help out of the box? | Wins day 1, loses overall; 56-day context best |
| 05 | [Zero-shot TimesFM 2.5](05_zero_shot_timesfm.ipynb) | Same, with TimesFM | Similar; a hybrid gains only 1.8% |
| 06 | [Foundation models across years](06_foundation_models_walk_forward.ipynb) | Is the ranking stable? | No; it flips between 2019 and 2021 |
| 07 | [Dataset v2 and distribution shift](07_v2_data_and_distribution_shift.ipynb) | Better data, stricter protocol | XGBoost loses to naive on 2024 record peaks |
| 08 | [Chronos-2 LoRA fine-tuning](08_chronos2_lora_finetuning.ipynb) | Does fine-tuning plus weather help? | Calendar-only LoRA 6.87; GFS covariates break it |
| 09 | [LightGBM with GFS](09_lightgbm_with_gfs.ipynb) | Can trees use forecasts? | Helps (8.82 vs 10.67), still behind |
| 10 | [TCN and ensemble](10_tcn_and_ensemble.ipynb) | A model built for the weather signal | Ensemble 6.05 on 2024; weights frozen |
| 11 | [External validation and packaging](11_external_validation_and_packaging.ipynb) | Does it generalise? Is the deployment faithful? | 7.48 on 2025–26; parity < 1e-5 MU end to end |
| 12 | [Live forecasting prototype](12_live_forecasting_prototype.ipynb) | Can it run on live data? | The loop that became the dashboard |

Outputs are kept so the notebooks read on GitHub without being run. Paths are relative to this folder. Install the dependencies with `pip install -e ".[research]"`.
