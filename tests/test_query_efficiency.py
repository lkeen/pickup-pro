"""N+1 regression cover for the game listing.

The listing template reads game.court, game.host, game.players and
game.can_join() for every row. With lazy loading that is roughly four extra
round trips per row: rendering 20 games took 25 queries, and rendering 200 would
have taken 241.
"""


def _make_games(count, user_factory, court_factory, game_factory):
    host = user_factory()
    others = [user_factory() for _ in range(3)]
    for i in range(count):
        court = court_factory(name=f"Court {i}", lat=33.0 + i * 0.01, lng=-83.0, created_by=host.id)
        game_factory(court=court, host=host, players=[host, *others])
    return host


def test_listing_queries_do_not_grow_with_the_number_of_games(
    db, login, user_factory, court_factory, game_factory, query_counter
):
    """The property that matters. A fixed expected count would just need
    updating whenever the page changes; this fails only on an actual N+1."""
    host = _make_games(3, user_factory, court_factory, game_factory)
    client = login(host)

    client.get("/games")  # warm any first-request work
    query_counter.reset()
    client.get("/games")
    with_three = query_counter.count

    for i in range(3, 18):
        court = court_factory(name=f"Extra {i}", lat=34.0 + i * 0.01, lng=-83.0, created_by=host.id)
        game_factory(court=court, host=host, players=[host])

    query_counter.reset()
    client.get("/games")
    with_eighteen = query_counter.count

    assert with_eighteen == with_three, (
        f"query count grew from {with_three} to {with_eighteen} when the listing "
        f"went from 3 games to 18 -- lazy loading has come back"
    )


def test_listing_stays_within_a_small_query_budget(
    db, login, user_factory, court_factory, game_factory, query_counter
):
    host = _make_games(20, user_factory, court_factory, game_factory)
    client = login(host)

    client.get("/games")
    query_counter.reset()
    response = client.get("/games")

    assert response.status_code == 200
    # Base query, court, host, roster -- plus session lookups. Comfortably under
    # the 25 this page used to issue for the same 20 games.
    assert query_counter.count <= 8, f"{query_counter.count} queries to render 20 games"
