"""Flask CLI commands.

`flask seed` exists so that a fresh clone can reach a working, populated app in
one command. An empty database makes a project look broken.
"""

import random
from datetime import timedelta

import click
from flask import Blueprint

from app.extensions import db
from app.models import Court, Game, GamePlayer, PlayerRating, PlayerStats, User
from app.services import caching
from app.timeutils import utcnow

bp = Blueprint("cli", __name__, cli_group=None)

# Real courts in Athens, GA, so the map opens somewhere recognisable rather than
# in the Atlantic.
COURTS = [
    ("Legion Field", "195 Sanford Dr, Athens, GA", 33.9482, -83.3745),
    ("Bishop Park", "705 Sunset Dr, Athens, GA", 33.9743, -83.3960),
    ("Rocksprings Park", "291 Henderson Ext, Athens, GA", 33.9433, -83.3968),
    ("Ramsey Center", "330 River Rd, Athens, GA", 33.9391, -83.3737),
    ("Memorial Park", "293 Gran Ellen Dr, Athens, GA", 33.9490, -83.4080),
    ("East Athens Community Center", "400 McKinley Dr, Athens, GA", 33.9569, -83.3502),
]

PLAYERS = [
    "jordan", "maya", "andre", "priya", "chris", "tasha",
    "diego", "kenji", "sam", "riley", "nia", "omar",
]

SEED_PASSWORD = "pickup-demo-password"


@bp.cli.command("seed")
@click.option("--force", is_flag=True, help="Wipe existing data first.")
def seed(force):
    """Populate the database with a small, plausible dataset."""
    if User.query.count() and not force:
        click.echo("Database already has data. Re-run with --force to replace it.")
        return

    if force:
        for model in (PlayerRating, PlayerStats, GamePlayer, Game, Court, User):
            db.session.query(model).delete()
        db.session.commit()
        click.echo("Cleared existing data.")

    rng = random.Random(20260826)  # deterministic, so the demo looks the same each time

    users = []
    for name in PLAYERS:
        user = User(username=name, email=f"{name}@example.com")
        user.set_password(SEED_PASSWORD)
        db.session.add(user)
        users.append(user)
    db.session.commit()

    courts = []
    for name, address, lat, lng in COURTS:
        court = Court(name=name, address=address, lat=lat, lng=lng, created_by=users[0].id)
        db.session.add(court)
        courts.append(court)
    db.session.commit()

    now = utcnow()
    games = []
    # A mix of past games (which can have stats) and upcoming ones (which show
    # up in search).
    for offset in (-12, -9, -6, -4, -2, -1, 1, 2, 3, 5, 8, 11):
        court = rng.choice(courts)
        host = rng.choice(users)
        game = Game(
            court_id=court.id,
            host_id=host.id,
            time=(now + timedelta(days=offset)).replace(minute=0, second=0, microsecond=0),
            max_players=rng.choice([8, 10, 10, 12]),
        )
        db.session.add(game)
        db.session.flush()

        roster = rng.sample(users, rng.randint(4, min(len(users), game.max_players)))
        if host not in roster:
            roster[0] = host
        for player in roster:
            db.session.add(GamePlayer(game_id=game.id, user_id=player.id))

        games.append((game, roster, offset < 0))
    db.session.commit()

    for game, roster, is_past in games:
        if not is_past:
            continue
        for player in roster:
            db.session.add(
                PlayerStats(
                    game_id=game.id,
                    user_id=player.id,
                    points=rng.randint(0, 28),
                    rebounds=rng.randint(0, 12),
                    assists=rng.randint(0, 9),
                )
            )
        for rater in roster:
            for target in rng.sample([p for p in roster if p != rater], min(2, len(roster) - 1)):
                exists = PlayerRating.query.filter_by(
                    game_id=game.id, from_user_id=rater.id, to_user_id=target.id
                ).first()
                if not exists:
                    db.session.add(
                        PlayerRating(
                            game_id=game.id,
                            from_user_id=rater.id,
                            to_user_id=target.id,
                            rating=rng.randint(3, 5),
                        )
                    )
    db.session.commit()
    caching.clear_all()

    click.echo(
        f"Seeded {len(users)} players, {len(courts)} courts, {len(games)} games.\n"
        f"Log in as any of: {', '.join(PLAYERS[:4])} …  password: {SEED_PASSWORD}"
    )


@bp.cli.command("cache-clear")
def cache_clear():
    """Empty the cache."""
    caching.clear_all()
    click.echo("Cache cleared.")
