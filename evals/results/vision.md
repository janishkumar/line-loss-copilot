# Vision eval (PatchCore on VisA food subsets)

Date 2026-11-08, commit `d876e4b15245`. Split seed 0; bootstrap 1000 resamples over images, seed 0. Train/eval overlap checked by path and by content hash before scoring.

Assumptions and caveats:

- Costs are relative: a false reject costs 1 and an escaped defect costs r. r = 20 is an assumption, not a measured plant figure; the sensitivity table shows r = 5 to 100.
- Validation and test are 50/50 halves of the official test split; each half holds only dozens of images per class, so intervals are wide and the threshold is noisy.
- The test halves are two thirds anomalous (VisA's official test mix), far above a plant's defect rate. False reject rate and escape rate are per class and transfer; cost per 1000 images and the cost-optimal threshold do not, and at a real defect rate the cost would be dominated by false rejects.
- Images are VisA product photos, not images from the plant; their link to a line is simulated elsewhere in this project and labelled.
- The review band assumes a reviewer decides every image in it correctly and ignores review effort.

## Test split (95% bootstrap interval)

| Subset | Test images (anomalous) | Image AUROC | Pixel AUROC | Pixel AUPRO |
|---|---|---|---|---|
| cashew | 75 (50) | 0.983 (0.958 to 0.999) | 0.990 (0.979 to 0.993) | 0.922 (0.884 to 0.953) |
| chewinggum | 75 (50) | 0.996 (0.986 to 1.000) | 0.988 (0.979 to 0.995) | 0.884 (0.826 to 0.933) |
| fryum | 75 (50) | 0.947 (0.888 to 0.987) | 0.926 (0.895 to 0.960) | 0.788 (0.684 to 0.873) |
| pipe_fryum | 75 (50) | 0.995 (0.983 to 1.000) | 0.992 (0.988 to 0.996) | 0.912 (0.872 to 0.957) |
| macaroni1 | 100 (50) | 0.965 (0.928 to 0.991) | 0.989 (0.977 to 0.995) | 0.949 (0.909 to 0.976) |
| macaroni2 | 100 (50) | 0.695 (0.584 to 0.794) | 0.956 (0.926 to 0.978) | 0.847 (0.736 to 0.927) |

## Full official test split (for comparison with published work)

| Subset | Images (anomalous) | Image AUROC | Pixel AUROC | Pixel AUPRO |
|---|---|---|---|---|
| cashew | 150 (100) | 0.981 | 0.991 | 0.917 |
| chewinggum | 150 (100) | 0.991 | 0.983 | 0.826 |
| fryum | 150 (100) | 0.934 | 0.932 | 0.793 |
| pipe_fryum | 150 (100) | 0.993 | 0.992 | 0.924 |
| macaroni1 | 200 (100) | 0.965 | 0.991 | 0.954 |
| macaroni2 | 200 (100) | 0.725 | 0.945 | 0.813 |

## Threshold, cost and review band (r = 20 default, relative units)

Threshold from validation only. Cost per 1000 images = (false rejects + r x escapes) / images x 1000, on test.

| Subset | Threshold | Cost per 1000 | False reject rate | Escape rate | Review band share (test) | Escapes avoided in band |
|---|---|---|---|---|---|---|
| cashew | 0.828 | 133 | 0.400 | 0.000 | 0.027 | 0 of 0 |
| chewinggum | 0.894 | 200 | 0.600 | 0.000 | 0.053 | 0 of 0 |
| fryum | 0.866 | 240 | 0.720 | 0.000 | 0.067 | 0 of 0 |
| pipe_fryum | 0.849 | 80 | 0.240 | 0.000 | 0.093 | 0 of 0 |
| macaroni1 | 0.815 | 420 | 0.440 | 0.020 | 0.040 | 0 of 1 |
| macaroni2 | 1.021 | 630 | 0.860 | 0.020 | 0.070 | 1 of 1 |

## Sensitivity to r (test)

| Subset | r | Threshold | Cost per 1000 | False reject rate | Escape rate |
|---|---|---|---|---|---|
| cashew | 5 | 0.828 | 133 | 0.400 | 0.000 |
| cashew | 10 | 0.828 | 133 | 0.400 | 0.000 |
| cashew | 20 | 0.828 | 133 | 0.400 | 0.000 |
| cashew | 50 | 0.828 | 133 | 0.400 | 0.000 |
| cashew | 100 | 0.828 | 133 | 0.400 | 0.000 |
| chewinggum | 5 | 0.894 | 200 | 0.600 | 0.000 |
| chewinggum | 10 | 0.894 | 200 | 0.600 | 0.000 |
| chewinggum | 20 | 0.894 | 200 | 0.600 | 0.000 |
| chewinggum | 50 | 0.894 | 200 | 0.600 | 0.000 |
| chewinggum | 100 | 0.894 | 200 | 0.600 | 0.000 |
| fryum | 5 | 0.887 | 253 | 0.560 | 0.020 |
| fryum | 10 | 0.866 | 240 | 0.720 | 0.000 |
| fryum | 20 | 0.866 | 240 | 0.720 | 0.000 |
| fryum | 50 | 0.866 | 240 | 0.720 | 0.000 |
| fryum | 100 | 0.866 | 240 | 0.720 | 0.000 |
| pipe_fryum | 5 | 0.849 | 80 | 0.240 | 0.000 |
| pipe_fryum | 10 | 0.849 | 80 | 0.240 | 0.000 |
| pipe_fryum | 20 | 0.849 | 80 | 0.240 | 0.000 |
| pipe_fryum | 50 | 0.849 | 80 | 0.240 | 0.000 |
| pipe_fryum | 100 | 0.849 | 80 | 0.240 | 0.000 |
| macaroni1 | 5 | 0.845 | 180 | 0.160 | 0.040 |
| macaroni1 | 10 | 0.815 | 320 | 0.440 | 0.020 |
| macaroni1 | 20 | 0.815 | 420 | 0.440 | 0.020 |
| macaroni1 | 50 | 0.815 | 720 | 0.440 | 0.020 |
| macaroni1 | 100 | 0.815 | 1220 | 0.440 | 0.020 |
| macaroni2 | 5 | 1.021 | 480 | 0.860 | 0.020 |
| macaroni2 | 10 | 1.021 | 530 | 0.860 | 0.020 |
| macaroni2 | 20 | 1.021 | 630 | 0.860 | 0.020 |
| macaroni2 | 50 | 1.021 | 930 | 0.860 | 0.020 |
| macaroni2 | 100 | 1.021 | 1430 | 0.860 | 0.020 |

## Published comparison

Source: CCAD: Compressed Global Feature Conditioned Anomaly Detection, https://arxiv.org/html/2512.21459, Table 8 (Appendix D.2, VisA), 'AUROC (Class-level; Pixel-level) comparison with SOTA methods on VisA', column PatchCore, single-class setting. Metrics: image AUROC and pixel AUROC (AUPRO is not reported there).

Setup match with ours: no. Third-party re-run of PatchCore using an LDM (AutoEncoderKL) encoder, 256 x 256 input and a 1000-sample memory bank (the paper's Table 22). Ours: wide_resnet50_2 IMAGENET1K_V1, resize 256, centre crop 224, layers 2 and 3, coreset up to 10% or 16,384 patches. Backbone, crop and coreset differ, so this is a loose reference, not a like for like comparison. Several of its figures (macaroni2 image AUROC 0.472) look weak against other PatchCore reports, which I could not verify from a fetched table.

The VisA paper (arXiv 2207.14315) does not report PatchCore, so no AUPRO figure for PatchCore on VisA was found in a source I could fetch and read.

| Subset | Published image AUROC | Ours (full official test) | Published pixel AUROC | Ours (full official test) |
|---|---|---|---|---|
| cashew | 0.851 | 0.981 | 0.777 | 0.991 |
| chewinggum | 0.925 | 0.991 | 0.921 | 0.983 |
| fryum | 0.769 | 0.934 | 0.885 | 0.932 |
| pipe_fryum | 0.901 | 0.993 | 0.920 | 0.992 |
| macaroni1 | 0.785 | 0.965 | 0.944 | 0.991 |
| macaroni2 | 0.472 | 0.725 | 0.936 | 0.945 |
