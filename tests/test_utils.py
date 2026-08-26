"""Unit tests for the Haversine helper.

These matter beyond the function itself: a later branch moves distance filtering
into PostGIS, and this stays as the independent oracle that the database results
are checked against.
"""

import math

import pytest

from app.utils import haversine_distance

# (name, lat1, lng1, lat2, lng2, expected_km) -- great-circle distances between
# well-known points, accurate to roughly a kilometre.
KNOWN_DISTANCES = [
    ("Athens GA to Atlanta GA", 33.9519, -83.3576, 33.7490, -84.3880, 97.8),
    ("New York to Los Angeles", 40.7128, -74.0060, 34.0522, -118.2437, 3936.0),
    ("London to Paris", 51.5074, -0.1278, 48.8566, 2.3522, 343.5),
    ("Equator quarter-circumference", 0.0, 0.0, 0.0, 90.0, 10007.5),
    ("Pole to pole via prime meridian", 90.0, 0.0, -90.0, 0.0, 20015.1),
]


@pytest.mark.parametrize("name,lat1,lng1,lat2,lng2,expected", KNOWN_DISTANCES)
def test_matches_known_distances(name, lat1, lng1, lat2, lng2, expected):
    actual = haversine_distance(lat1, lng1, lat2, lng2)
    assert actual == pytest.approx(expected, rel=0.01), name


def test_zero_distance_for_identical_points():
    assert haversine_distance(33.9519, -83.3576, 33.9519, -83.3576) == 0.0


def test_is_symmetric():
    a = haversine_distance(33.9519, -83.3576, 40.7128, -74.0060)
    b = haversine_distance(40.7128, -74.0060, 33.9519, -83.3576)
    assert a == pytest.approx(b)


def test_handles_the_origin():
    """lat=0/lng=0 is a real place, not a missing value."""
    assert haversine_distance(0.0, 0.0, 0.0, 1.0) == pytest.approx(111.19, rel=0.01)


def test_antimeridian_is_not_the_long_way_round():
    """Points either side of the date line are close, not half a world apart."""
    km = haversine_distance(0.0, 179.9, 0.0, -179.9)
    assert km == pytest.approx(22.24, rel=0.01)


def test_never_returns_nan_for_antipodal_points():
    """Floating point can push the Haversine 'a' term just above 1.0."""
    km = haversine_distance(45.0, 0.0, -45.0, 180.0)
    assert not math.isnan(km)
    assert km == pytest.approx(20015.1, rel=0.01)
