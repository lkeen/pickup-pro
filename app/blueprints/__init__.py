"""Blueprint registration.

Routes were previously all defined inside ``create_app``. They are grouped here
by resource so that each area of the app has an obvious home.
"""

from app.blueprints.api import bp as api_bp
from app.blueprints.auth import bp as auth_bp
from app.blueprints.courts import bp as courts_bp
from app.blueprints.games import bp as games_bp
from app.blueprints.leaderboard import bp as leaderboard_bp
from app.blueprints.oauth import bp as oauth_bp
from app.blueprints.profiles import bp as profiles_bp
from app.blueprints.stats import bp as stats_bp

ALL_BLUEPRINTS = (
    auth_bp,
    oauth_bp,
    courts_bp,
    games_bp,
    stats_bp,
    profiles_bp,
    leaderboard_bp,
    api_bp,
)


def register_blueprints(app):
    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)
