from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    dataset: str
    filename: str
    url: str
    md5: str
    size: int


def _zenodo(record: int, name: str) -> str:
    return f"https://zenodo.org/api/records/{record}/files/{name}/content"


_PIADE = 7071747
_BRICK = 17855209


def _s(dataset: str, record: int, name: str, md5: str, size: int) -> Source:
    return Source(dataset, name, _zenodo(record, name), md5, size)


SOURCES: list[Source] = [
    _s("piade", _PIADE, "raw_data.csv", "a0fc01fbfc9414b0f754cd0a8e70c429", 49342406),
    _s("piade", _PIADE, "sequences_1h_data.csv", "5edf8a6806f272228d522c76825d955c", 11663660),
    _s("brick", _BRICK, "OEEdataset.csv", "f271a9a337fe58f8bc5c9eda2d38f43d", 5623),
    _s("brick", _BRICK, "OEEdataset_afterLSS.csv", "806676e334595f3914d4646e286473a3", 4721),
    _s("brick", _BRICK, "DowntimeDataset.csv", "7b46e04694809a1c510c2ff1c48d0a50", 91259),
    _s(
        "brick", _BRICK, "DowntimeDataset_afterLSS.csv", "bb192fb4fccb945f679f85a2c52530e0", 3131020
    ),
    _s("brick", _BRICK, "README.md", "8e4ce0f186f162c902f2bf7acf4386bc", 8185),
]
