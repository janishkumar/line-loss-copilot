# Vision: ONNX export and CPU latency

Date: 2026-11-09; commit `f1c66d06a8b9`.

Machine: Apple M4, 10 cores; onnxruntime 1.31.1, torch 2.15.0, opset 17; CPUExecutionProvider, batch 1.

System load average (1 min) at the start of the run: 4.9. Latency was measured on a laptop in normal use, so expect run-to-run noise of tens of percent; more threads did not help much because one image is a small workload.

Protocol: 20 warm-up runs excluded, 200 timed runs, p50 and p95 in ms. The graph takes the preprocessed 1 x 3 x 224 x 224 tensor and returns (score, map); preprocessing is outside the graph and timed separately. The PyTorch rows run `PatchCore.score` with the same protocol, for context.

| Subset | Model MB | Max rel. score diff | Max abs map diff | ONNX 1 thread p50 / p95 | ONNX 4 threads p50 / p95 | PyTorch 1 thread p50 / p95 | PyTorch 4 threads p50 / p95 | Preprocess p50 / p95 |
|---|---|---|---|---|---|---|---|---|
| cashew | 172.9 | 2.91e-06 | 4.47e-06 | 102.6 / 112.6 | 99.4 / 110.3 | 96.7 / 102.6 | 84.2 / 88.1 | 12.8 / 16.1 |
| chewinggum | 172.9 | 1.51e-06 | 5.48e-06 | 109.3 / 164.0 | 99.0 / 127.9 | 93.0 / 107.8 | 82.2 / 91.3 | 10.4 / 11.5 |
| fryum | 172.9 | 2.28e-06 | 6.38e-06 | 99.7 / 107.2 | 97.0 / 106.0 | 92.0 / 96.4 | 82.4 / 87.2 | 10.2 / 10.8 |
| pipe_fryum | 172.9 | 2.25e-06 | 7.51e-06 | 98.7 / 103.1 | 96.2 / 103.2 | 91.9 / 97.6 | 83.0 / 87.9 | 10.2 / 10.7 |
| macaroni1 | 172.9 | 9.48e-07 | 5.78e-06 | 66.6 / 68.1 | 52.1 / 53.2 | 61.7 / 63.0 | 48.0 / 50.2 | 5.9 / 6.1 |
| macaroni2 | 172.9 | 1.77e-06 | 5.48e-06 | 67.3 / 68.4 | 52.5 / 53.4 | 61.7 / 62.9 | 47.6 / 49.1 | 5.8 / 6.0 |

Parity: 10 real test-split images per subset, tolerance 1e-03 relative on the score; the export fails if it is exceeded. The PyTorch scorer uses `torch.cdist`; the graph uses the exact matmul form of the distance and a fixed matrix for the channel reduction, so differences are float rounding only.
