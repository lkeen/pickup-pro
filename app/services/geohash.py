"""Geohash encoding, and the coarse grid used for cache invalidation.

Two different jobs, deliberately kept apart.

Cache keys use a geohash, because raw float coordinates from a browser never
repeat and keying on them gives a hit rate of roughly zero. The cost is that the
search centre moves by up to half a cell -- tens of metres at this precision.

Invalidation tags use a plain latitude/longitude grid instead, because tag
coverage has to be exact: a cell missed when tagging is an entry that never gets
invalidated. Enumerating grid cells across a bounding box is obviously exact,
whereas walking geohash neighbours is easy to get subtly wrong at cell and
meridian boundaries.
"""

import math

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

# ~150 m cells: fine enough that quantising does not move a search
# meaningfully, coarse enough that searches from one place collide.
DEFAULT_PRECISION = 7

# ~55 km cells. One tag each, so a court changing invalidates its own cell only.
TAG_CELL_DEGREES = 0.5


def encode(lat, lng, precision=DEFAULT_PRECISION):
    """Standard geohash. Interleaves longitude and latitude bits, base32."""
    lat_range = [-90.0, 90.0]
    lng_range = [-180.0, 180.0]
    result = []
    bits = 0
    bit_count = 0
    use_lng = True

    while len(result) < precision:
        if use_lng:
            midpoint = sum(lng_range) / 2
            if lng > midpoint:
                bits = (bits << 1) | 1
                lng_range[0] = midpoint
            else:
                bits <<= 1
                lng_range[1] = midpoint
        else:
            midpoint = sum(lat_range) / 2
            if lat > midpoint:
                bits = (bits << 1) | 1
                lat_range[0] = midpoint
            else:
                bits <<= 1
                lat_range[1] = midpoint

        use_lng = not use_lng
        bit_count += 1
        if bit_count == 5:
            result.append(_BASE32[bits])
            bits = 0
            bit_count = 0

    return "".join(result)


def cell_for(lat, lng):
    """The invalidation tag for a single point."""
    return _cell_name(
        math.floor(lat / TAG_CELL_DEGREES),
        math.floor(lng / TAG_CELL_DEGREES),
    )


def cells_covering(lat, lng, radius_km):
    """Every tag cell a search from (lat, lng) could draw results from.

    Over-covering is harmless -- an extra tag means an extra invalidation --
    but under-covering is a correctness bug, so the bounding box is deliberately
    generous.
    """
    lat_delta = radius_km / 111.0

    min_lat = max(lat - lat_delta, -90.0)
    max_lat = min(lat + lat_delta, 90.0)

    # cos() shrinks towards the pole, so the widest longitude span is at the
    # box edge with the largest absolute latitude.
    widest = max(abs(min_lat), abs(max_lat))
    cos_lat = math.cos(math.radians(widest))
    if cos_lat < 1e-6:
        # At or near a pole every longitude is within reach; tag the whole band.
        lng_delta = 180.0
    else:
        lng_delta = min(radius_km / (111.0 * cos_lat), 180.0)

    min_lng = lng - lng_delta
    max_lng = lng + lng_delta

    cells = set()
    lat_index = math.floor(min_lat / TAG_CELL_DEGREES)
    while lat_index <= math.floor(max_lat / TAG_CELL_DEGREES):
        lng_index = math.floor(min_lng / TAG_CELL_DEGREES)
        while lng_index <= math.floor(max_lng / TAG_CELL_DEGREES):
            # Wrap longitude indices across the antimeridian so a search that
            # straddles it tags the cells on both sides.
            span = int(360 / TAG_CELL_DEGREES)
            cells.add(_cell_name(lat_index, ((lng_index + span // 2) % span) - span // 2))
            lng_index += 1
        lat_index += 1
    return cells


def _cell_name(lat_index, lng_index):
    return f"geo:{lat_index}:{lng_index}"
