import numpy as np
from PIL import Image

from linecopilot.vision import imaging
from linecopilot.vision.patchcore import IMAGENET_MEAN, IMAGENET_STD
from linecopilot.vision.preprocess import SIZE, preprocess_image


def _photo(tmp_path, size=(97, 61)):
    rng = np.random.default_rng(3)
    arr = rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8)
    p = tmp_path / "x.png"
    Image.fromarray(arr).save(p)
    return p


def test_constants_match_the_training_geometry():
    assert imaging.SIZE == SIZE
    assert imaging.IMAGENET_MEAN == tuple(IMAGENET_MEAN)
    assert imaging.IMAGENET_STD == tuple(IMAGENET_STD)


def test_numpy_preprocessing_equals_the_torch_one(tmp_path):
    """The stream scores with the numpy path, the model was fitted with the torch path."""
    p = _photo(tmp_path)
    a = imaging.preprocess_np(p)
    b = preprocess_image(p).numpy()
    assert a.shape == b.shape == (3, 224, 224) and a.dtype == np.float32
    assert np.abs(a - b).max() < 1e-5


def test_overlay_is_a_448_rgb_image_and_scale_is_fixed_by_threshold(tmp_path):
    p = _photo(tmp_path)
    low = np.zeros((224, 224), dtype=np.float32)
    hot = np.full((224, 224), 1.5, dtype=np.float32)
    img_low = imaging.overlay(p, low, 1.0)
    img_hot = imaging.overlay(p, hot, 1.0)
    assert img_low.size == (448, 448) and img_low.mode == "RGB"
    # below half the threshold nothing is drawn: the overlay is just the resized photo
    plain = Image.open(p).convert("RGB").resize((224, 224), Image.BICUBIC)
    plain = plain.resize((448, 448), Image.BICUBIC)
    assert np.abs(np.asarray(img_low, dtype=int) - np.asarray(plain, dtype=int)).max() <= 1
    r_hot = np.asarray(img_hot)[..., 0].mean()
    assert r_hot > np.asarray(img_low)[..., 0].mean()
