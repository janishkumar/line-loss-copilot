# Vision eval (PatchCore on VisA food subsets)

Date 2026-11-09, commit `08b963ed3365`. Split seed 0; bootstrap 1000 resamples over images, seed 0. Train/eval overlap checked by path and by content hash before scoring. Images are resized whole to 224 x 224 (no crop).

Assumptions and caveats:

- Costs are relative. A false reject costs 1 and an escaped defect costs r = 20; defects are assumed to be p = 2% of items. Both are assumptions, not plant figures; the sensitivity grid covers r = 5 to 100 and p = 0.5% to 5%.
- Rates are per class (share of normals rejected, share of defects passed) and are weighted by p, so the threshold does not depend on VisA's test mix (two thirds anomalous). Cost per 1000 items is the weighted cost times 1000.
- Validation and test are 50/50 halves of the official test split, so each half holds only 25 to 50 normal and 50 anomalous images: intervals are wide and thresholds are noisy.
- Images are VisA product photos, not images from the plant; their link to a line is simulated elsewhere in this project and labelled.
- The review band assumes a reviewer decides every image in it correctly and ignores review effort. Its width is set on validation so that 10% of items, weighted by p, are routed to review.
- Pixel metrics are computed on the 224 x 224 maps and masks, not at the original resolution.

## Test split (95% bootstrap interval)

| Subset | Test images (anomalous) | Image AUROC | Pixel AUROC | Pixel AUPRO |
|---|---|---|---|---|
| cashew | 75 (50) | 0.974 (0.939 to 0.997) | 0.993 (0.980 to 0.995) | 0.927 (0.892 to 0.955) |
| chewinggum | 75 (50) | 0.997 (0.988 to 1.000) | 0.988 (0.979 to 0.995) | 0.892 (0.836 to 0.938) |
| fryum | 75 (50) | 0.906 (0.828 to 0.962) | 0.960 (0.940 to 0.979) | 0.781 (0.656 to 0.880) |
| pipe_fryum | 75 (50) | 0.986 (0.957 to 1.000) | 0.995 (0.992 to 0.997) | 0.902 (0.850 to 0.955) |
| macaroni1 | 100 (50) | 0.888 (0.820 to 0.942) | 0.970 (0.952 to 0.983) | 0.855 (0.764 to 0.930) |
| macaroni2 | 100 (50) | 0.654 (0.548 to 0.759) | 0.940 (0.911 to 0.964) | 0.812 (0.719 to 0.893) |

## Full official test split (for comparison with published work)

| Subset | Images (anomalous) | Image AUROC | Pixel AUROC | Pixel AUPRO |
|---|---|---|---|---|
| cashew | 150 (100) | 0.974 | 0.994 | 0.921 |
| chewinggum | 150 (100) | 0.995 | 0.982 | 0.831 |
| fryum | 150 (100) | 0.924 | 0.964 | 0.793 |
| pipe_fryum | 150 (100) | 0.990 | 0.995 | 0.925 |
| macaroni1 | 200 (100) | 0.885 | 0.971 | 0.844 |
| macaroni2 | 200 (100) | 0.619 | 0.941 | 0.810 |

## Threshold, cost and review band (r = 20, p = 2% defects, relative units)

Threshold from validation only. Cost per 1000 items = 1000 x ((1 - p) x false reject rate + p x r x escape rate), on test. Review band: 10% of items, weighted by p, from validation.

| Subset | Threshold | Cost per 1000 items | False reject rate | Escape rate | Items to review per 1000 | Escape rate with review |
|---|---|---|---|---|---|---|
| cashew | 0.881 | 63.2 | 0.040 | 0.060 | 39 | 0.060 |
| chewinggum | 0.872 | 47.2 | 0.040 | 0.020 | 0 | 0.020 |
| fryum | 0.915 | 159.2 | 0.040 | 0.300 | 40 | 0.240 |
| pipe_fryum | 0.869 | 63.2 | 0.040 | 0.060 | 0 | 0.040 |
| macaroni1 | 0.834 | 256.4 | 0.180 | 0.200 | 99 | 0.160 |
| macaroni2 | 1.191 | 407.2 | 0.040 | 0.920 | 60 | 0.840 |

## Sensitivity: test cost per 1000 items by r and p

| Subset | p | r = 5 | r = 10 | r = 20 | r = 50 | r = 100 |
|---|---|---|---|---|---|---|
| cashew | 0.5% | 41.3 | 42.8 | 45.8 | 54.8 | 69.8 |
| cashew | 1.0% | 42.6 | 45.6 | 51.6 | 69.6 | 99.6 |
| cashew | 2.0% | 45.2 | 51.2 | 63.2 | 99.2 | 355.2 |
| cashew | 5.0% | 53.0 | 68.0 | 98.0 | 378.0 | 404.0 |
| chewinggum | 0.5% | 40.3 | 40.8 | 41.8 | 44.8 | 49.8 |
| chewinggum | 1.0% | 40.6 | 41.6 | 43.6 | 49.6 | 59.6 |
| chewinggum | 2.0% | 41.2 | 43.2 | 47.2 | 59.2 | 79.2 |
| chewinggum | 5.0% | 43.0 | 48.0 | 58.0 | 88.0 | 138.0 |
| fryum | 0.5% | 47.3 | 54.8 | 69.8 | 114.8 | 189.8 |
| fryum | 1.0% | 54.6 | 69.6 | 99.6 | 189.6 | 536.0 |
| fryum | 2.0% | 69.2 | 99.2 | 159.2 | 532.0 | 551.2 |
| fryum | 5.0% | 113.0 | 188.0 | 520.0 | 568.0 | 832.0 |
| pipe_fryum | 0.5% | 41.3 | 42.8 | 45.8 | 54.8 | 69.8 |
| pipe_fryum | 1.0% | 42.6 | 45.6 | 51.6 | 69.6 | 99.6 |
| pipe_fryum | 2.0% | 45.2 | 51.2 | 63.2 | 99.2 | 159.2 |
| pipe_fryum | 5.0% | 53.0 | 68.0 | 98.0 | 188.0 | 338.0 |
| macaroni1 | 0.5% | 41.4 | 62.9 | 105.9 | 229.1 | 279.1 |
| macaroni1 | 1.0% | 62.8 | 105.8 | 135.8 | 278.2 | 437.2 |
| macaroni1 | 2.0% | 105.6 | 135.6 | 256.4 | 434.4 | 552.0 |
| macaroni1 | 5.0% | 221.0 | 271.0 | 426.0 | 580.0 | 780.0 |
| macaroni2 | 0.5% | 25.0 | 50.0 | 100.0 | 269.8 | 519.6 |
| macaroni2 | 1.0% | 50.0 | 100.0 | 223.6 | 519.2 | 793.6 |
| macaroni2 | 2.0% | 100.0 | 223.2 | 407.2 | 787.2 | 947.2 |
| macaroni2 | 5.0% | 268.0 | 516.0 | 768.0 | 1008.0 | 1074.0 |

## Test-set rates for every r and p

| Subset | r | p | Threshold | False reject rate | Escape rate |
|---|---|---|---|---|---|
| cashew | 5 | 0.5% | 0.881 | 0.040 | 0.060 |
| cashew | 5 | 1.0% | 0.881 | 0.040 | 0.060 |
| cashew | 5 | 2.0% | 0.881 | 0.040 | 0.060 |
| cashew | 5 | 5.0% | 0.881 | 0.040 | 0.060 |
| cashew | 10 | 0.5% | 0.881 | 0.040 | 0.060 |
| cashew | 10 | 1.0% | 0.881 | 0.040 | 0.060 |
| cashew | 10 | 2.0% | 0.881 | 0.040 | 0.060 |
| cashew | 10 | 5.0% | 0.881 | 0.040 | 0.060 |
| cashew | 20 | 0.5% | 0.881 | 0.040 | 0.060 |
| cashew | 20 | 1.0% | 0.881 | 0.040 | 0.060 |
| cashew | 20 | 2.0% | 0.881 | 0.040 | 0.060 |
| cashew | 20 | 5.0% | 0.881 | 0.040 | 0.060 |
| cashew | 50 | 0.5% | 0.881 | 0.040 | 0.060 |
| cashew | 50 | 1.0% | 0.881 | 0.040 | 0.060 |
| cashew | 50 | 2.0% | 0.881 | 0.040 | 0.060 |
| cashew | 50 | 5.0% | 0.848 | 0.240 | 0.060 |
| cashew | 100 | 0.5% | 0.881 | 0.040 | 0.060 |
| cashew | 100 | 1.0% | 0.881 | 0.040 | 0.060 |
| cashew | 100 | 2.0% | 0.848 | 0.240 | 0.060 |
| cashew | 100 | 5.0% | 0.820 | 0.320 | 0.020 |
| chewinggum | 5 | 0.5% | 0.872 | 0.040 | 0.020 |
| chewinggum | 5 | 1.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 5 | 2.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 5 | 5.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 10 | 0.5% | 0.872 | 0.040 | 0.020 |
| chewinggum | 10 | 1.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 10 | 2.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 10 | 5.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 20 | 0.5% | 0.872 | 0.040 | 0.020 |
| chewinggum | 20 | 1.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 20 | 2.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 20 | 5.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 50 | 0.5% | 0.872 | 0.040 | 0.020 |
| chewinggum | 50 | 1.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 50 | 2.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 50 | 5.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 100 | 0.5% | 0.872 | 0.040 | 0.020 |
| chewinggum | 100 | 1.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 100 | 2.0% | 0.872 | 0.040 | 0.020 |
| chewinggum | 100 | 5.0% | 0.872 | 0.040 | 0.020 |
| fryum | 5 | 0.5% | 0.915 | 0.040 | 0.300 |
| fryum | 5 | 1.0% | 0.915 | 0.040 | 0.300 |
| fryum | 5 | 2.0% | 0.915 | 0.040 | 0.300 |
| fryum | 5 | 5.0% | 0.915 | 0.040 | 0.300 |
| fryum | 10 | 0.5% | 0.915 | 0.040 | 0.300 |
| fryum | 10 | 1.0% | 0.915 | 0.040 | 0.300 |
| fryum | 10 | 2.0% | 0.915 | 0.040 | 0.300 |
| fryum | 10 | 5.0% | 0.915 | 0.040 | 0.300 |
| fryum | 20 | 0.5% | 0.915 | 0.040 | 0.300 |
| fryum | 20 | 1.0% | 0.915 | 0.040 | 0.300 |
| fryum | 20 | 2.0% | 0.915 | 0.040 | 0.300 |
| fryum | 20 | 5.0% | 0.845 | 0.400 | 0.140 |
| fryum | 50 | 0.5% | 0.915 | 0.040 | 0.300 |
| fryum | 50 | 1.0% | 0.915 | 0.040 | 0.300 |
| fryum | 50 | 2.0% | 0.845 | 0.400 | 0.140 |
| fryum | 50 | 5.0% | 0.822 | 0.440 | 0.060 |
| fryum | 100 | 0.5% | 0.915 | 0.040 | 0.300 |
| fryum | 100 | 1.0% | 0.845 | 0.400 | 0.140 |
| fryum | 100 | 2.0% | 0.822 | 0.440 | 0.060 |
| fryum | 100 | 5.0% | 0.803 | 0.560 | 0.060 |
| pipe_fryum | 5 | 0.5% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 5 | 1.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 5 | 2.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 5 | 5.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 10 | 0.5% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 10 | 1.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 10 | 2.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 10 | 5.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 20 | 0.5% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 20 | 1.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 20 | 2.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 20 | 5.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 50 | 0.5% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 50 | 1.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 50 | 2.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 50 | 5.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 100 | 0.5% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 100 | 1.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 100 | 2.0% | 0.869 | 0.040 | 0.060 |
| pipe_fryum | 100 | 5.0% | 0.869 | 0.040 | 0.060 |
| macaroni1 | 5 | 0.5% | 1.019 | 0.020 | 0.860 |
| macaroni1 | 5 | 1.0% | 1.019 | 0.020 | 0.860 |
| macaroni1 | 5 | 2.0% | 1.019 | 0.020 | 0.860 |
| macaroni1 | 5 | 5.0% | 0.834 | 0.180 | 0.200 |
| macaroni1 | 10 | 0.5% | 1.019 | 0.020 | 0.860 |
| macaroni1 | 10 | 1.0% | 1.019 | 0.020 | 0.860 |
| macaroni1 | 10 | 2.0% | 0.927 | 0.020 | 0.580 |
| macaroni1 | 10 | 5.0% | 0.834 | 0.180 | 0.200 |
| macaroni1 | 20 | 0.5% | 1.019 | 0.020 | 0.860 |
| macaroni1 | 20 | 1.0% | 0.927 | 0.020 | 0.580 |
| macaroni1 | 20 | 2.0% | 0.834 | 0.180 | 0.200 |
| macaroni1 | 20 | 5.0% | 0.813 | 0.280 | 0.160 |
| macaroni1 | 50 | 0.5% | 0.834 | 0.180 | 0.200 |
| macaroni1 | 50 | 1.0% | 0.834 | 0.180 | 0.200 |
| macaroni1 | 50 | 2.0% | 0.813 | 0.280 | 0.160 |
| macaroni1 | 50 | 5.0% | 0.795 | 0.400 | 0.080 |
| macaroni1 | 100 | 0.5% | 0.834 | 0.180 | 0.200 |
| macaroni1 | 100 | 1.0% | 0.813 | 0.280 | 0.160 |
| macaroni1 | 100 | 2.0% | 0.795 | 0.400 | 0.080 |
| macaroni1 | 100 | 5.0% | 0.795 | 0.400 | 0.080 |
| macaroni2 | 5 | 0.5% | 1.305 | 0.000 | 1.000 |
| macaroni2 | 5 | 1.0% | 1.305 | 0.000 | 1.000 |
| macaroni2 | 5 | 2.0% | 1.305 | 0.000 | 1.000 |
| macaroni2 | 5 | 5.0% | 1.191 | 0.040 | 0.920 |
| macaroni2 | 10 | 0.5% | 1.305 | 0.000 | 1.000 |
| macaroni2 | 10 | 1.0% | 1.305 | 0.000 | 1.000 |
| macaroni2 | 10 | 2.0% | 1.191 | 0.040 | 0.920 |
| macaroni2 | 10 | 5.0% | 1.164 | 0.080 | 0.880 |
| macaroni2 | 20 | 0.5% | 1.305 | 0.000 | 1.000 |
| macaroni2 | 20 | 1.0% | 1.191 | 0.040 | 0.920 |
| macaroni2 | 20 | 2.0% | 1.191 | 0.040 | 0.920 |
| macaroni2 | 20 | 5.0% | 0.999 | 0.640 | 0.160 |
| macaroni2 | 50 | 0.5% | 1.191 | 0.040 | 0.920 |
| macaroni2 | 50 | 1.0% | 1.164 | 0.080 | 0.880 |
| macaroni2 | 50 | 2.0% | 0.999 | 0.640 | 0.160 |
| macaroni2 | 50 | 5.0% | 0.999 | 0.640 | 0.160 |
| macaroni2 | 100 | 0.5% | 1.164 | 0.080 | 0.880 |
| macaroni2 | 100 | 1.0% | 0.999 | 0.640 | 0.160 |
| macaroni2 | 100 | 2.0% | 0.999 | 0.640 | 0.160 |
| macaroni2 | 100 | 5.0% | 0.954 | 0.920 | 0.040 |

## Published comparison

Primary source: Zou et al., SPot-the-Difference self-supervised pre-training for anomaly detection and segmentation (the VisA paper), https://arxiv.org/html/2207.14315, Table 6, '1-class performance evaluation on VisA and MVTec-AD with PatchCore', backbone Wide ResNet50, row 'Sup. pre-train', VisA columns. Published PatchCore average (average over VisA's 12 classes, one model per class; the table does not state the input resolution or AUPRO): image AUROC 92.4, pixel AUROC 98.4.
Ours, mean over the six food subsets on the full official test split: image AUROC 89.8, pixel AUROC 97.4. These averages cover different sets of classes (12 published, 6 ours), so the comparison is indicative only.

Setup match: partly. Ours: wide_resnet50_2 IMAGENET1K_V1, whole image resized to 224 x 224 without cropping, layers 2 and 3, coreset up to 10% or 16,384 patches, one model per subset, official 1cls train. Backbone and one-class protocol match the primary source, whose figures are averages over 12 classes while ours are averages over the six food subsets, so the two averages cover different sets of classes. No source found reports PatchCore AUPRO per class on VisA.

Per-class reference: SoftPatch+ (Fully unsupervised anomaly detection with noisy data), https://arxiv.org/html/2412.20870, Table 3 (image AUROC) and Table 4 (pixel AUROC), 'upperbound' column of the 'No Overlap' setting, which is PatchCore trained on clean normal images, Wide-ResNet50, 10% coreset. The test set is that paper's 8%-noise protocol variant, not necessarily the official 1cls test split, and its VisA input resolution is not stated (it states 256 resize with 224 centre crop for MVTec AD only).

| Subset | Image AUROC (ours, full official test) | Image AUROC (published) | Pixel AUROC (ours) | Pixel AUROC (published) | Pixel AUPRO (ours) |
|---|---|---|---|---|---|
| cashew | 0.974 | 0.989 | 0.994 | 0.985 | 0.921 |
| chewinggum | 0.995 | 0.991 | 0.982 | 0.994 | 0.831 |
| fryum | 0.924 | 0.954 | 0.964 | 0.925 | 0.793 |
| pipe_fryum | 0.990 | 0.997 | 0.995 | 0.989 | 0.925 |
| macaroni1 | 0.885 | 0.975 | 0.971 | 0.999 | 0.844 |
| macaroni2 | 0.619 | 0.767 | 0.941 | 0.981 | 0.810 |

## First run with a centre crop

First run used a resize to 256 and a centre crop to 224, which cut the defect entirely out of the image for 18 of 100 macaroni2 anomalies (24 had under half inside). The preprocessing now resizes the whole image to 224 x 224 and the models were refitted. Image AUROC did not improve on the macaroni subsets (macaroni1 and macaroni2 are lower); this was not investigated further, and squeezing a wide image into a square, which makes small defects smaller, is one possible factor.

Before (centre crop; recorded from the first run, not reproducible from this commit) and after (whole image resized), image AUROC, pixel AUROC, pixel AUPRO, full official test split:

| Subset | Before | After |
|---|---|---|
| cashew | 0.981 / 0.991 / 0.917 | 0.974 / 0.994 / 0.921 |
| chewinggum | 0.991 / 0.983 / 0.826 | 0.995 / 0.982 / 0.831 |
| fryum | 0.934 / 0.932 / 0.793 | 0.924 / 0.964 / 0.793 |
| pipe_fryum | 0.993 / 0.992 / 0.924 | 0.990 / 0.995 / 0.925 |
| macaroni1 | 0.965 / 0.991 / 0.954 | 0.885 / 0.971 / 0.844 |
| macaroni2 | 0.725 / 0.945 / 0.813 | 0.619 / 0.941 / 0.810 |
