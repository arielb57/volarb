import json

import pytest

from volarb.cli import main
from volarb.csvio import GridError, read_grid, write_grid

CLEAN = """expiry,t,forward,discount,strike,price
A,0.25,100,1,90,12
A,0.25,100,1,100,5
A,0.25,100,1,110,2
B,0.5,100,1,90,14
B,0.5,100,1,100,9
B,0.5,100,1,110,5
"""


def write(tmp_path, text, name="grid.csv"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_clean_grid_exits_zero(tmp_path, capsys):
    assert main(["check", write(tmp_path, CLEAN)]) == 0
    out = capsys.readouterr().out
    assert "6 quotes in 2 expiries" in out
    assert "no static arbitrage found" in out


def test_arbitrage_grid_prints_table_removal_and_exits_one(tmp_path, capsys):
    bad = CLEAN.replace("A,0.25,100,1,100,5", "A,0.25,100,1,100,8")
    assert main(["check", write(tmp_path, bad)]) == 1
    out = capsys.readouterr().out
    assert "1 violations: 1 convexity" in out
    assert "A@K=90 A@K=100 A@K=110" in out
    # Dropping any one of the three restores convexity; the DP reports one of them.
    assert "minimum removal: 1 of 6 quotes" in out
    assert "calendar (greedy" not in out
    assert "violations after removal: 0" in out


def test_json_output_is_exact(tmp_path, capsys):
    bad = CLEAN.replace("A,0.25,100,1,100,5", "A,0.25,100,1,100,8")
    assert main(["check", "--json", write(tmp_path, bad)]) == 1
    doc = json.loads(capsys.readouterr().out)
    kinds = {v["kind"] for v in doc["violations"]}
    assert kinds == {"convexity"}
    (conv,) = doc["violations"]
    # slopes -2/5 then -3/5 over a strike span of 20: 2 * (1/5) / 20
    assert conv["size"] == "1/50"
    assert conv["quotes"] == [{"expiry": "A", "row": r} for r in (2, 3, 4)]
    assert len(doc["removal"]["A"]) == 1 and doc["removal"]["B"] == []
    assert doc["residual_violations"] == 0


def test_implied_vol_input_is_converted_and_flagged(tmp_path, capsys):
    grid = "expiry,t,forward,discount,strike,iv\n" + "\n".join(
        f"A,0.5,100,0.98,{k},{v}" for k, v in [(80, 0.30), (90, 0.25), (100, 0.22), (110, 0.9)]
    )
    assert main(["check", write(tmp_path, grid)]) == 1
    out = capsys.readouterr().out
    assert "float Black-76" in out
    assert "monotonicity" in out


def test_input_errors_exit_two(tmp_path, capsys):
    assert main(["check", str(tmp_path / "missing.csv")]) == 2
    assert main(["check", write(tmp_path, "expiry,strike,price\nA,1,1\n")]) == 2
    both = "expiry,t,forward,discount,strike,price,iv\nA,1,100,1,100,5,0.2\n"
    assert main(["check", write(tmp_path, both)]) == 2
    err = capsys.readouterr().err
    assert "missing columns" in err and "exactly one" in err


def test_reader_rejects_inconsistent_expiry_metadata_and_bad_numbers():
    with pytest.raises(GridError, match="differ within expiry"):
        read_grid(["expiry,t,forward,discount,strike,price", "A,1,100,1,90,11", "A,1,101,1,95,8"])
    with pytest.raises(GridError, match="not a number"):
        read_grid(["expiry,t,forward,discount,strike,price", "A,1,100,1,ninety,11"])
    with pytest.raises(GridError, match="strike must be > 0"):
        read_grid(["expiry,t,forward,discount,strike,price", "A,1,100,1,0,11"])


def test_decimal_parsing_is_exact():
    surface, from_iv = read_grid(
        ["expiry,t,forward,discount,strike,price", "A,1,100,0.1,90,0.1000000000000000000001"]
    )
    assert not from_iv
    q = surface.expiries[0].quotes[0]
    assert str(q.price) == "1000000000000000000001/10000000000000000000000"
    assert q.row == 2


@pytest.mark.parametrize(
    "inject,kind", [("bump", "convexity"), ("tilt", "monotonicity"), ("calendar", "calendar")]
)
def test_generate_then_check_round_trip(tmp_path, capsys, inject, kind):
    assert main(["generate", "--seed", "3", "--inject", inject]) == 0
    grid = capsys.readouterr().out
    assert main(["check", "--json", write(tmp_path, grid)]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert {v["kind"] for v in doc["violations"]} == {kind}
    assert doc["residual_violations"] == 0


def test_generate_clean_round_trips_through_csv(capsys):
    assert main(["generate", "--seed", "4"]) == 0
    text = capsys.readouterr().out
    surface, _ = read_grid(text.splitlines())
    assert write_grid(surface) == text
