from __future__ import annotations

from scoredclub.geocode import apply_geocoding, geocode_district
from scoredclub.schemas import EntityProfile


def test_geocode_known_district():
    assert geocode_district("Friedrichshain") == (52.5155, 13.4540)
    # Case-insensitive.
    assert geocode_district("mitte") == (52.5200, 13.4050)


def test_geocode_composite_name():
    # "Friedrichshain-Kreuzberg" resolves via the first matching part.
    coords = geocode_district("Friedrichshain-Kreuzberg")
    assert coords in {(52.5155, 13.4540), (52.4990, 13.4030)}


def test_geocode_unknown():
    assert geocode_district("Hamburg-Altona") is None
    assert geocode_district(None) is None
    assert geocode_district("") is None


def test_apply_geocoding_fills_geo():
    p = EntityProfile(entity_id="berghain", name="Berghain", type="club", district="Friedrichshain")
    assert p.geo.lat is None
    changed = apply_geocoding(p)
    assert changed is True
    # Within ~jitter of the Friedrichshain centroid.
    assert abs(p.geo.lat - 52.5155) < 0.01
    assert abs(p.geo.lon - 13.4540) < 0.01


def test_apply_geocoding_is_deterministic():
    a = EntityProfile(entity_id="x", name="X", type="club", district="Mitte")
    b = EntityProfile(entity_id="x", name="X2", type="club", district="Mitte")
    apply_geocoding(a)
    apply_geocoding(b)
    assert (a.geo.lat, a.geo.lon) == (b.geo.lat, b.geo.lon)  # jitter keyed on entity_id


def test_apply_geocoding_respects_existing_and_unknown():
    # Existing coordinates are left untouched.
    p = EntityProfile(entity_id="a", name="A", type="club", district="Mitte",
                      geo={"lat": 1.0, "lon": 2.0})
    assert apply_geocoding(p) is False
    assert (p.geo.lat, p.geo.lon) == (1.0, 2.0)
    # Unknown district -> no change.
    q = EntityProfile(entity_id="b", name="B", type="collective", district="Nowhere")
    assert apply_geocoding(q) is False
    assert q.geo.lat is None
