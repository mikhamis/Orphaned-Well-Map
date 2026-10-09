import json
from pathlib import Path

from owm import build

FIX = Path(__file__).parent / "fixtures"


def run(tmp_path):
    build.main([
        "--usgs", str(FIX / "usgs_sample.csv"),
        "--states-dir", str(FIX / "states"),
        "--state-file", f"TX={FIX / 'tx_wells.csv'}",
        "--cache", str(tmp_path / "cache"),
        "--out", str(tmp_path / "out"),
    ])
    out = tmp_path / "out"
    return (json.loads((out / "manifest.json").read_text()),
            json.loads((out / "points.json").read_text()),
            json.loads((out / "states" / "TX.json").read_text()))


def test_build_end_to_end(tmp_path):
    manifest, pts, tx = run(tmp_path)
    assert manifest["usgs"]["rows"] == 6
    assert manifest["usgs"]["dropped_bad_location"] == 1      # the 0,0 row
    assert [s["code"] for s in manifest["states"]] == ["OK", "TX"]
    ok, txs = manifest["states"]
    assert ok["configured"] is False and txs["configured"] is True
    assert len(pts["lon"]) == 5 and len(tx) == 4
    assert txs["offset"] == 1

    a, b, c, d = tx
    # latest real operator wins over the later placeholder row
    assert a["m"] == "api" and a["op"] == "Acme Oil Co." and not a.get("opp")
    # two active wells within a mile, the far one excluded
    assert a["na"] == 2 and {n[1] for n in a["nn"]} == {"Gamma Production LP"}
    assert a["no"] == [["Gamma Production LP", 2]]
    # unsigned longitude repaired; placeholder operator flagged
    assert b["m"] == "api" and b["opp"] is True
    assert pts["lon"][2] == -97.01
    # no API in USGS row -> location match within tolerance
    assert c["m"] == "location" and c["op"] == "Beta Energy Inc" and c["md"] < 30
    # not in state file at all
    assert "m" not in d

    assert pts["j"] == [0, 3, 2, 3, 1]
    ops = manifest["operators"]
    assert {o["name"] for o in ops} == {"Acme Oil Co.", "Beta Energy Inc"}
    assert pts["o"][1] == [o["name"] for o in ops].index("Acme Oil Co.")


def test_operator_key_merges_suffixes():
    assert build.operator_key("Acme Oil Co.") == build.operator_key("ACME OIL COMPANY")
    assert build.operator_key("Smith & Sons, LLC") == build.operator_key("Smith and Sons")
