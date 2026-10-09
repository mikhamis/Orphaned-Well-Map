import pytest

from owm.util import GridIndex, haversine_m, is_placeholder_operator, normalize_api, state_code


@pytest.mark.parametrize("raw,state,want", [
    ("42-123-45678", None, "4212345678"),
    ("42123456780000", None, "4212345678"),
    ("421234567801", None, "4212345678"),
    ("4212345678.0", None, "4212345678"),
    ("123456789", None, "0123456789"),        # AL/AZ/.. lost leading zero
    ("12345678", "TX", "4212345678"),         # county+unique only
    ("12345678", None, None),
    ("4200000000", None, None),
    ("", None, None),
    ("PERMIT-77", None, None),
])
def test_normalize_api(raw, state, want):
    assert normalize_api(raw, state) == want


def test_state_code():
    assert state_code("pennsylvania") == "PA"
    assert state_code("tx") == "TX"
    assert state_code("Narnia") is None


@pytest.mark.parametrize("name,want", [
    ("UNKNOWN", True), ("Orphan Well Program", True), ("N/A", True), ("", True),
    ("State of Ohio", True), ("Acme Oil Co.", False), ("Unknown Operator", True),
])
def test_placeholder(name, want):
    assert is_placeholder_operator(name) is want


def test_grid_within_matches_bruteforce():
    import random
    rnd = random.Random(1)
    g = GridIndex(0.02)
    pts = [(-98 + rnd.random() * 0.2, 31 + rnd.random() * 0.2) for _ in range(500)]
    for p in pts:
        g.add(*p)
    q = (-97.9, 31.1)
    got = [i for _, i in g.within(*q, 1609)]
    want = sorted((haversine_m(*q, *p), i) for i, p in enumerate(pts) if haversine_m(*q, *p) <= 1609)
    assert got == [i for _, i in want]
    assert got  # fixture should produce hits
