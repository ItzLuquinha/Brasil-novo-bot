from app.services.levels import required_xp, level_from_xp

def test_required_xp_is_monotonic() -> None:
    values = [required_xp(level) for level in range(6)]
    assert values == sorted(values)
    assert all(value > 0 for value in values)

def test_level_from_xp_boundaries() -> None:
    assert level_from_xp(0) == 0
    assert level_from_xp(99) == 0
    assert level_from_xp(100) == 1
    assert level_from_xp(499) == 1
    assert level_from_xp(500) == 2
