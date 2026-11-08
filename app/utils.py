import math

EARTH_RADIUS_KM = 6371


def haversine_distance(lat1, lng1, lat2, lng2):
    """Great-circle distance in kilometres.

    Retained as the independent oracle the PostGIS spatial tests assert
    against, not as a query path.
    """
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
    return 2 * math.asin(math.sqrt(a)) * EARTH_RADIUS_KM
