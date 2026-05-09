Checked read-only, no interruption.

Current auto-finetune outcome: successful.

Training request: kft_20260507_53288d
Started: May 7, 2026 14:27 local
Completed: May 7, 2026 15:39 local
Exit code: 0
Duration: about 72.9 minutes
Dataset: 3000 rows
Train/validation split: 2100 / 900
Device: CPU
Epochs: 1
Training loss: 2.3181
Validation loss: 2.5430
Best model saved successfully.
Artifacts are present:

KRONOS-MODEL/model/Kronos-auto-finetuned/config.json
KRONOS-MODEL/model/Kronos-auto-finetuned/model.safetensors
KRONOS-MODEL/model/Kronos-auto-finetuned/README.md
KRONOS-MODEL/model/Kronos-auto-finetuned/auto_finetune_manifest.json
Current worker state:

auto_finetune_worker: OK
State: sleeping
Action: skip
Reason: new_rows_below_threshold (0/1000)
Active model ready: true
Promotion status: pending_evaluation
Auto model running: false
Current shadow/evaluation signal:

Shadow model: Kronos-auto-shadow
Samples: 66
Wins: 12
Losses: 29
Resolved win rate: about 29.3%
Still not promoted.
Observed issue:

Candidate model registration hit a warning:
Object of type datetime is not JSON serializable
Because of that, candidate_model_version_id is still null in auto_finetune_status.json, even though the model artifacts exist and the dashboard shadow model is visible.
Bottom line: training succeeded and produced usable artifacts, but promotion is correctly still pending. The main remaining issue is candidate registry serialization, not training failure.