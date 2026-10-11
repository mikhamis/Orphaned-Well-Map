import json
from pathlib import Path

from owm import build

FIX = Path(__file__).parent / "fixtures"


def run(tmp_path, usgs="usgs_2026_sample.csv"):
    build.main([
        "--usgs", str(FIX / usgs),
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
    assert b["so"] == "DOI / NPS" and b["mo"] == "federal / oil and gas"
    assert a["n"] == "SYNTH A 1" and a["src"] == "Synthetic Commission"
    ok_rows = json.loads((tmp_path / "out" / "states" / "OK.json").read_text())
    assert ok_rows[0]["id"] == "12345"          # KY-style permit kept as ID, not an API
    ops = manifest["operators"]
    assert {o["name"] for o in ops} == {"Acme Oil Co.", "Beta Energy Inc"}
    assert pts["o"][1] == [o["name"] for o in ops].index("Acme Oil Co.")


def test_operator_key_merges_suffixes():
    assert build.operator_key("Acme Oil Co.") == build.operator_key("ACME OIL COMPANY")
    assert build.operator_key("Smith & Sons, LLC") == build.operator_key("Smith and Sons")


def test_legacy_2022_style_columns(tmp_path):
    manifest, pts, tx = run(tmp_path, "usgs_sample.csv")
    assert len(pts["lon"]) == 5 and tx[0]["op"] == "Acme Oil Co."


def test_usgs_api_rules():
    from owm.usgs import usgs_api
    assert usgs_api("42-001-00001", "API", "", "TX", True) == "4200100001"
    assert usgs_api("1234567890", "KYPermit", "", "KY", True) is None
    assert usgs_api("1234567890", "", "", "TX", True) is None          # wrong state prefix
    assert usgs_api("", "", "4200100009", "TX", True) == "4200100009"  # untyped secondary


def test_original_operator_states_excluded_from_national_count(tmp_path):
    import shutil
    states = tmp_path / "states"
    shutil.copytree(FIX / "states", states)
    cfg = json.loads((states / "TX.json").read_text())
    cfg["operator_kind"] = "original"
    (states / "TX.json").write_text(json.dumps(cfg))
    build.main(["--usgs", str(FIX / "usgs_2026_sample.csv"), "--states-dir", str(states),
                "--state-file", f"TX={FIX / 'tx_wells.csv'}", "--out", str(tmp_path / "out")])
    m = json.loads((tmp_path / "out" / "manifest.json").read_text())
    acme = next(o for o in m["operators"] if o["name"] == "Acme Oil Co.")
    assert acme["count"] == 0 and acme["by_state"] == {"TX": 1}
    assert next(s for s in m["states"] if s["code"] == "TX")["operator_kind"] == "original"
