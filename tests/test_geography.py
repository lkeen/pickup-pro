"""The generated geography column on courts.

geog is GENERATED ALWAYS AS ... STORED, derived by PostgreSQL from lat/lng. The
application never writes it, which is the point: it cannot drift out of sync
however the row was created.
"""

import pytest
from sqlalchemy import text

from app.models import Court
from app.utils import haversine_distance

# PostGIS geography measures on the WGS84 spheroid; the Haversine helper assumes
# a sphere. They agree to within about a quarter of a percent, which is the
# difference between the two models rather than an error in either.
SPHEROID_VS_SPHERE = 0.005


def _wkt(db, court_id):
    return db.session.execute(
        text("SELECT ST_AsText(geog) FROM courts WHERE id = :id"), {"id": court_id}
    ).scalar()


def test_geography_is_derived_without_the_application_setting_it(db, court_factory):
    court = court_factory(lat=33.9519, lng=-83.3576)
    assert _wkt(db, court.id) == "POINT(-83.3576 33.9519)"


def test_longitude_comes_first_in_the_point(db, court_factory):
    """ST_MakePoint takes (x, y) -- longitude then latitude. Getting this
    backwards is the classic PostGIS mistake and puts everything in the wrong
    hemisphere."""
    court = court_factory(lat=10.0, lng=20.0)
    assert _wkt(db, court.id) == "POINT(20 10)"


def test_geography_follows_a_moved_court(db, court_factory):
    court = court_factory(lat=33.9519, lng=-83.3576)
    court.lat, court.lng = 40.7128, -74.0060
    db.session.commit()
    assert _wkt(db, court.id) == "POINT(-74.006 40.7128)"


def test_geography_cannot_be_written_directly(db, court_factory):
    court = court_factory()
    with pytest.raises(Exception) as excinfo:
        db.session.execute(
            text("UPDATE courts SET geog = ST_GeogFromText('SRID=4326;POINT(0 0)') WHERE id = :id"),
            {"id": court.id},
        )
        db.session.commit()
    db.session.rollback()
    assert "generated" in str(excinfo.value).lower()


def test_a_court_at_the_origin_gets_a_valid_point(db, court_factory):
    """Null Island is a real coordinate, not a missing value."""
    court = court_factory(name="Null Island", lat=0.0, lng=0.0)
    assert _wkt(db, court.id) == "POINT(0 0)"


def test_the_srid_is_4326(db, court_factory):
    court = court_factory()
    srid = db.session.execute(
        text("SELECT ST_SRID(geog::geometry) FROM courts WHERE id = :id"), {"id": court.id}
    ).scalar()
    assert srid == 4326


@pytest.mark.parametrize(
    "name,lat1,lng1,lat2,lng2",
    [
        ("Athens to Atlanta", 33.9519, -83.3576, 33.7490, -84.3880),
        ("New York to Los Angeles", 40.7128, -74.0060, 34.0522, -118.2437),
        ("London to Paris", 51.5074, -0.1278, 48.8566, 2.3522),
        ("across the antimeridian", 0.0, 179.9, 0.0, -179.9),
    ],
)
def test_postgis_agrees_with_the_haversine_oracle(db, name, lat1, lng1, lat2, lng2):
    """The Haversine helper is kept as an independent check on the database.

    Two implementations that agree are far better evidence than one that looks
    right -- particularly for the antimeridian case, where a naive
    implementation goes most of the way around the world.
    """
    postgis_km = db.session.execute(
        text(
            "SELECT ST_Distance("
            "  ST_SetSRID(ST_MakePoint(:lng1, :lat1), 4326)::geography,"
            "  ST_SetSRID(ST_MakePoint(:lng2, :lat2), 4326)::geography) / 1000.0"
        ),
        {"lat1": lat1, "lng1": lng1, "lat2": lat2, "lng2": lng2},
    ).scalar()
    oracle_km = haversine_distance(lat1, lng1, lat2, lng2)
    assert postgis_km == pytest.approx(oracle_km, rel=SPHEROID_VS_SPHERE), name


def test_existing_rows_gained_a_geography_when_the_column_was_added(db, court_factory):
    """The column was added as GENERATED ... STORED, so PostgreSQL computed a
    value for every pre-existing row rather than leaving them null."""
    court_factory(lat=1.0, lng=2.0)
    nulls = db.session.query(Court).filter(Court.geog.is_(None)).count()
    assert nulls == 0
