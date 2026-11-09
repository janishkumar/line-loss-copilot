# Vision: ONNX export and CPU latency

Machine: Apple M4, 10 cores (macOS-26.6.2-arm64-arm-64bit); onnxruntime 1.31.1, torch 2.15.0, opset 17; CPUExecutionProvider, batch 1. This is the only machine measured.

Provenance: 120 blocks measured on 2026-11-09 at commit(s) ecbabc773b23; 1-minute load average before each block 2.39 to 3.98 (median 3.63), limit 4.0 (the load average includes the benchmark's own threads, which alone settle near 2.5). Each block's own date, commit and load are in `vision_latency.json`.

Protocol: 5 rounds; each round runs every subset x {ONNX 1 thread, ONNX 4 threads, PyTorch 1 thread, PyTorch 4 threads} once in a seeded shuffled order, so load drifts across all of them equally. Each block is 20 warm-up runs (excluded) then 40 timed runs on one fixed random input (the graph's cost does not depend on pixel values). Figures are the median of the per-round p50s in ms, with the range of those round medians in brackets. The graph takes the preprocessed 1 x 3 x 224 x 224 tensor and returns (score, map); preprocessing is outside the graph and timed separately. The PyTorch rows run `PatchCore.score`, for context.

All six graphs have the same shape and cost (same 16384 x 1024 bank, same input), so differences between subsets are noise, not model effects. The pooled row is the one number to quote.

| Subset | ONNX 1 thread | ONNX 4 threads | PyTorch 1 thread | PyTorch 4 threads |
|---|---|---|---|---|
| pipe_fryum | 66.9 (59.7 to 118.1) | 51.6 (48.7 to 53.6) | 61.7 (56.5 to 79.8) | 48.7 (43.5 to 73.9) |
| cashew | 67.5 (58.4 to 113.4) | 49.0 (48.7 to 64.8) | 57.7 (57.4 to 65.1) | 46.9 (43.6 to 74.9) |
| macaroni1 | 67.6 (60.0 to 116.3) | 52.3 (48.8 to 53.3) | 58.4 (57.5 to 61.9) | 44.4 (43.6 to 77.1) |
| chewinggum | 67.2 (59.7 to 90.0) | 52.7 (48.9 to 87.8) | 58.7 (57.4 to 80.9) | 44.0 (43.5 to 75.8) |
| fryum | 61.1 (59.7 to 69.9) | 49.8 (48.7 to 56.4) | 58.5 (57.5 to 124.4) | 48.0 (44.3 to 48.8) |
| macaroni2 | 67.8 (59.6 to 70.5) | 48.9 (48.8 to 53.8) | 61.1 (57.6 to 89.6) | 45.1 (44.3 to 50.4) |
| **all subsets** | 67.4 (58.4 to 118.1) | 49.6 (48.7 to 87.8) | 58.7 (56.5 to 124.4) | 47.5 (43.5 to 77.1) |

p95 per block, median over rounds and subsets: onnx-1 71.7, onnx-4 53.9, torch-1 65.1, torch-4 51.8.

| Subset | Model MB | of which memory bank | of which backbone | Max rel. score diff | Max abs map diff | Preprocess p50 / p95 ms | Exported |
|---|---|---|---|---|---|---|---|
| cashew | 172.9 | 67.1 | 105.8 | 2.91e-06 | 4.47e-06 | 7.0 / 7.3 | 2026-11-09 `b2e30047a135` load 4.14 |
| chewinggum | 172.9 | 67.1 | 105.8 | 1.51e-06 | 5.48e-06 | 6.0 / 6.9 | 2026-11-09 `b2e30047a135` load 4.14 |
| fryum | 172.9 | 67.1 | 105.8 | 2.28e-06 | 6.38e-06 | 5.8 / 6.0 | 2026-11-09 `b2e30047a135` load 4.13 |
| pipe_fryum | 172.9 | 67.1 | 105.8 | 2.25e-06 | 7.51e-06 | 5.8 / 6.2 | 2026-11-09 `b2e30047a135` load 4.13 |
| macaroni1 | 172.9 | 67.1 | 105.8 | 9.48e-07 | 5.78e-06 | 5.8 / 6.0 | 2026-11-09 `b2e30047a135` load 4.13 |
| macaroni2 | 172.9 | 67.1 | 105.8 | 1.77e-06 | 5.48e-06 | 5.6 / 5.8 | 2026-11-09 `b2e30047a135` load 4.04 |

Parity: 10 real test-split images per subset; the export fails if the score differs by more than 1e-03 relative or the map by more than 1e-03 absolute. The PyTorch scorer uses `torch.cdist`; the graph uses the exact matmul form of the distance and a fixed matrix for the channel reduction, so differences are float rounding only.

Not demonstrated: suitability for a small plant computer. Only an Apple M4 laptop was measured. No x86 or older or low-power CPU, no RAM use, no quantisation and no smaller memory bank were tried; each model file is about 173 MB (six subsets, about 1 GB).
