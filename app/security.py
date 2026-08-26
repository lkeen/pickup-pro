"""Authorization decorators.

Authentication answers "who are you"; these answer "may you do this to that".
The distinction matters here because the app got the second one wrong: being
logged in and on a game's roster was treated as permission to write stats and
ratings for *anybody*, with the foreign key as the only thing narrowing it to
real users.

Failures abort with 403 rather than flashing and redirecting. The UI never
produces these requests -- the buttons only render for rostered players -- so a
request that reaches here is forged or stale, and a status code is a more honest
answer than a friendly redirect.
"""

from functools import wraps

from flask import abort, g, request
from flask_login import current_user

from app.extensions import db
from app.models import Game, GamePlayer


def is_on_roster(game_id, user_id):
    """Whether a user is on a game's roster.

    An EXISTS query rather than `user in game.players`, which loads the whole
    roster to answer a yes/no question.
    """
    return db.session.query(
        db.session.query(GamePlayer)
        .filter(GamePlayer.game_id == game_id, GamePlayer.user_id == user_id)
        .exists()
    ).scalar()


def _load_game_or_404(game_id):
    game = db.session.get(Game, game_id)
    if game is None:
        abort(404)
    return game


def require_roster(view):
    """The caller must be on the roster of the game in the URL.

    Stashes the game on ``g.game`` so the view does not load it a second time.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        game_id = kwargs["game_id"]
        g.game = _load_game_or_404(game_id)
        if not is_on_roster(game_id, current_user.id):
            abort(403, "Only rostered players can do that.")
        return view(*args, **kwargs)

    return wrapped


def require_target_on_roster(field):
    """The user identified by ``field`` in the form must be on the same roster.

    This is the check that was missing. Without it, any rostered player could
    submit stats for, or rate, any user in the database by editing a hidden
    form field.
    """

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            raw = request.form.get(field)
            try:
                target_id = int(raw)
            except (TypeError, ValueError):
                abort(400, f"{field} must be an integer.")

            if not is_on_roster(kwargs["game_id"], target_id):
                abort(403, "That player is not on this game's roster.")

            g.target_user_id = target_id
            return view(*args, **kwargs)

        return wrapped

    return decorator


def forbid_self(field):
    """Reject an action aimed at the caller themselves."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            raw = request.form.get(field)
            try:
                target_id = int(raw)
            except (TypeError, ValueError):
                abort(400, f"{field} must be an integer.")
            if target_id == current_user.id:
                abort(403, "You cannot do that to yourself.")
            return view(*args, **kwargs)

        return wrapped

    return decorator
