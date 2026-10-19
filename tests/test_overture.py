import httpx
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import shapely

from pleasant_rides import overture

# stands in for Overture's STAC index
INDEX = pa.table({"collection": ["segment"]})


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
        INDEX,
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
    assert (
        overture._read("2026-01-01.0", INDEX, "segment", (0, 0, 1, 1), ["geometry"])
        is None
    )


def test_read_without_an_index_reads_all_the_files(monkeypatch):
    sources = []

    def dataset(source):
        sources.append(source)
        return ds.dataset(roads(["primary"], [0.5]))

    monkeypatch.setattr(overture, "_dataset", dataset)
    read = overture._read("2026-01-01.0", None, "segment", (0, 0, 1, 1), ["class"])
    assert read is not None and read.num_rows == 1
    assert sources == [
        "overturemaps-us-west-2/release/2026-01-01.0/theme=transportation/type=segment/"
    ]


def test_stac_index_backs_off_after_a_failure(monkeypatch):
    monkeypatch.setattr(overture, "_stac_indexes", {})
    monkeypatch.setattr(overture, "_stac_failed_at", None)
    calls = []

    def rate_limited(release):
        calls.append(release)
        request = httpx.Request("GET", "https://stac.overturemaps.org/")
        raise httpx.HTTPStatusError(
            "429", request=request, response=httpx.Response(429, request=request)
        )

    assert overture.stac_index("r1", rate_limited) is None
    assert overture.stac_index("r1", rate_limited) is None
    assert calls == ["r1"]

    # and asks again once it's waited long enough
    monkeypatch.setattr(overture, "_stac_failed_at", -overture.STAC_RETRY_S)
    assert overture.stac_index("r1", lambda release: INDEX) is INDEX
    assert overture.stac_index("r1", rate_limited) is INDEX
