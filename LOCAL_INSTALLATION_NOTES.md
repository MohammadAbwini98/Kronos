# Kronos Local Installation Notes

## Installed Folders

- Repository: `C:\AI\Kronos`
- Virtual environment: `C:\AI\Kronos\.venv`
- Model root: `C:\AI\Models\Kronos`
- Kronos model: `C:\AI\Models\Kronos\Kronos-base`
- Kronos tokenizer: `C:\AI\Models\Kronos\Kronos-Tokenizer-base`

## Exact Model Names

- `NeoQuasar/Kronos-base`
- `NeoQuasar/Kronos-Tokenizer-base`

Both snapshots were downloaded to local folders and should be loaded by local path for future integration.

## Activate The Environment

From PowerShell:

```powershell
cd C:\AI\Kronos
.\.venv\Scripts\Activate.ps1
```

PowerShell execution policy on this machine is `RemoteSigned`, which is sufficient for the local venv activation script.

## Run Verification

Standard load verification:

```powershell
C:\AI\Kronos\run_verify_kronos.ps1
```

Non-interactive verification:

```powershell
C:\AI\Kronos\run_verify_kronos.ps1 -NoPause
```

Optional tiny synthetic OHLCV forecast smoke test:

```powershell
C:\AI\Kronos\run_verify_kronos.ps1 -SmokeTest
```

## CPU And GPU Behavior

The verification script uses:

- `cuda:0` when `torch.cuda.is_available()` is `True`
- `cpu` otherwise

To force CPU for later integration code, pass `device="cpu"` when creating `KronosPredictor`. To use GPU, pass `device="cuda:0"` or leave device selection to the same CUDA check used in `verify_kronos_local.py`.

## Installed Python Packages

The environment was created with Python 3.12.10. PyTorch was installed from the CUDA wheel index before installing Kronos requirements so GPU acceleration is available when supported by the NVIDIA driver.

Key packages:

- `torch`
- `huggingface_hub`
- `numpy`
- `pandas`
- `einops`
- `safetensors`
- `matplotlib`
- `tqdm`

## Known Limitations

- Kronos is a forecasting model. Its outputs should be treated as one input to a broader research, risk, and execution pipeline.
- This setup does not include live market data ingestion.
- This setup does not include broker APIs, Binance APIs, order placement, or live trading.
- Forecast quality depends on data quality, market regime, symbol, interval, lookback window, and downstream validation.
- GPU use requires a compatible NVIDIA driver and a CUDA-enabled PyTorch build.

## Trading Safety Reminder

Kronos output should be used as a forecasting input only. It should not be wired directly to a trade executor without independent validation, risk controls, position sizing, monitoring, and explicit human approval.
