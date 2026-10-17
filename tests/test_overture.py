import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import shapely

from pleasant_rides import overture


def roads(classes, corners):
    """Roads with `classes`, each with a bbox from (corner, corner) to (corner, corner)."""
    return pa.table(
        {
            "id": [f"road{i}" for i in range(len(classes))],
            "geometry": shapely.to_wkb([shapely.Point(0, 0)] * len(classes)),
            "class": classes,
            "bbox": pa.StructArray.from_arrays(
                [pa.array(corners)] * 4, names=["xmin", "xmax", "ymin", "ymax"]
            ),
        }
    )


def test_read_keeps_only_matching_features_in_the_bbox(monkeypatch):
    # the last road is outside the bbox
    table = roads(["motorway", "residential", "primary", "primary"], [0.1, 0.2, 0.3, 5])
    monkeypatch.setattr(overture, "_files", lambda *args: ["roads"])
    monkeypatch.setattr(overture, "_dataset", lambda files: ds.dataset(table))
    read = overture._read(
        "2026-01-01.0",
        "segment",
        (0, 0, 1, 1),
        ["geometry", "class"],
        pc.field("class").isin(["motorway", "primary"]),
    )
    assert read is not None
    assert read.column_names == ["geometry", "class"]
    assert read["class"].to_pylist() == ["motorway", "primary"]


def test_read_without_files(monkeypatch):
    monkeypatch.setattr(overture, "_files", lambda *args: [])
    assert overture._read("2026-01-01.0", "segment", (0, 0, 1, 1), ["geometry"]) is None
