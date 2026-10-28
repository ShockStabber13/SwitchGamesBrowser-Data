#!/usr/bin/env python3
"""Offline regression test for the real NotUltraNX catalog generator.

Exercises the generator with complete/incomplete cached HTML listing pages,
without contacting NotUltraNX or changing production JSON.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools/build_notultranx_catalog.py"

def record(id_, name="", card_text=""):
    return {"id": id_, "name": name, "cardText": card_text}

def id_for(index):
    return f"{index:016X}"

with tempfile.TemporaryDirectory(prefix="notultranx-regression-") as workspace:
    base = Path(workspace)
    pages = base / "pages"
    pages.mkdir()
    seed = base / "seed.json"
    out = base / "catalog.json"
    original = {"schemaVersion": 1, "games": [record(id_for(i), f"Original Game {i}") for i in range(20)]}
    seed.write_text(json.dumps(original), encoding="utf-8")
    out.write_text(json.dumps(original), encoding="utf-8")

    def make_page(number, indexes):
        html = "<html><body>" + "".join(
            f'<a href="/en/game/{id_for(i)}"><strong>Sample Game {i}</strong></a>'
            for i in indexes
        ) + "</body></html>"
        (pages / f"notultranx-page-{number}.html").write_text(html, encoding="utf-8")

    make_page(1, range(0, 45))
    make_page(2, range(45, 90))
    make_page(3, range(90, 125))  # A short final page marks completeness.

    command = [
        sys.executable, str(BUILDER),
        "--seed", str(seed), "--output", str(out),
        "--pages-dir", str(pages), "--max-pages", "4", "--skip-metadata",
    ]
    ok = subprocess.run(command, text=True, capture_output=True)
    assert ok.returncode == 0, ok.stdout + "\n" + ok.stderr
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert len(saved["games"]) == 125
    indexed = {row["id"]: row for row in saved["games"]}
    assert indexed[id_for(0)]["name"] == "Original Game 0"
    assert indexed[id_for(124)]["name"] == "Sample Game 124"
    assert "Complete site scan: 125 IDs, 105 added" in ok.stdout

    # Removing the final HTML page must fail without overwriting the catalog.
    (pages / "notultranx-page-3.html").unlink()
    previous_bytes = out.read_bytes()
    fail = subprocess.run(command, text=True, capture_output=True)
    assert fail.returncode != 0, "Partial listing scan unexpectedly succeeded"
    assert out.read_bytes() == previous_bytes, "Failure overwrote previous catalog"


# Exercise the generator's real game-page heading parser and missing-name
# fallback independently of the network, using realistic HTML fixtures.
import importlib.util
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("notultranx_builder", BUILDER)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
assert builder.game_page_name(
    '<html><h1 class="game-title">KINGDOM HEARTS <span>-HD 1.5+2.5 ReMIX-</span></h1></html>'
) == 'KINGDOM HEARTS -HD 1.5+2.5 ReMIX-'
assert builder.game_page_name('<html><h1>404</h1></html>') == ""
assert builder.game_page_name('<html><h2>No title here</h2></html>') == ""

target = "010090C022978000"
other = "0100A0902789A000"
catalog = {target: record(target), other: record(other, "Existing verified name")}
with patch.object(builder, "fetch", return_value=(
    b'<h1>KINGDOM HEARTS -HD 1.5+2.5 ReMIX-</h1>'
)) as mock_fetch, patch.object(builder.time, "sleep", return_value=None):
    builder.enrich_missing_site_names(catalog)
    mock_fetch.assert_called_once_with(
        "https://not.ultranx.ru/en/game/" + target, 4 * 1024 * 1024
    )
assert catalog[target]["name"] == "KINGDOM HEARTS -HD 1.5+2.5 ReMIX-"
assert catalog[other]["name"] == "Existing verified name"

print("NotUltraNX: complete scan, ID merge, name preservation and partial-scan rejection and detail-page title enrichment PASS")
