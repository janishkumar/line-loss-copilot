# Shortage eval (synthetic data)

- Synthetic data: generation 2, seed 7, content sha256 `4b0b07cf42cb27e6be715b107a264ea78fff2a4bc680f66b78691380a3cc0651`
- Date (UTC): 2026-11-07T16:33:54+00:00
- Git commit: e12d4057349b (uncommitted changes)
- 46 orders, 6 planted shortages, 4 decoys (counted as negatives)

The detector and the generator share the netting definition (need date, allocation order, receipts at or before the need time, sub-assembly netting before raw explosion), so a perfect detector score shows the code implements the definition, not real-world accuracy. The naive rule flags a material when on hand is below its total gross requirement and flags every order that uses it. Both are scored on raw materials only; sub-assemblies the naive rule flags are dropped. Decoys are built to be cases the naive rule flags, so its precision depends on the number of decoys and its recall of 1.00 holds by construction. The data is synthetic; planted shortages test the software.

Per-kind rows: false positives are the decoys of that kind; the `all` row counts every prediction outside the planted shortages as a false positive.

## (material, order) pairs

| Method | Kind | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|---|
| netting detector | all | 6 | 0 | 0 | 1.000 | 1.000 |
| netting detector | plain | 2 | 0 | 0 | 1.000 | 1.000 |
| netting detector | timing | 2 | 0 | 0 | 1.000 | 1.000 |
| netting detector | level_two | 2 | 0 | 0 | 1.000 | 1.000 |
| naive rule | all | 6 | 4 | 0 | 0.600 | 1.000 |
| naive rule | plain | 2 | 0 | 0 | 1.000 | 1.000 |
| naive rule | timing | 2 | 2 | 0 | 0.500 | 1.000 |
| naive rule | level_two | 2 | 2 | 0 | 0.500 | 1.000 |

## Materials

| Method | Kind | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|---|
| netting detector | all | 6 | 0 | 0 | 1.000 | 1.000 |
| netting detector | plain | 2 | 0 | 0 | 1.000 | 1.000 |
| netting detector | timing | 2 | 0 | 0 | 1.000 | 1.000 |
| netting detector | level_two | 2 | 0 | 0 | 1.000 | 1.000 |
| naive rule | all | 6 | 4 | 0 | 0.600 | 1.000 |
| naive rule | plain | 2 | 0 | 0 | 1.000 | 1.000 |
| naive rule | timing | 2 | 2 | 0 | 0.500 | 1.000 |
| naive rule | level_two | 2 | 2 | 0 | 0.500 | 1.000 |

Flags outside the planted cases: detector 0, naive rule 0. Decoys flagged: detector 0 of 4, naive rule 4 of 4.
