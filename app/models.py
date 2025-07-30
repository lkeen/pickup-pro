from datetime import datetime
from app.extensions import db

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key = True)
    username = db.Column(db.String(64), unique = True, nullable = False)
    password = db.Column(db.String(64), unique = False, nullable = False)
    email = db.Column(db.String(254), unique = True, nullable = False)
    created_at = db.Column(db.DateTime, default = datetime.now)

class Court(db.Model):
    __tablename__ = "courts"
    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.String(64), nullable = False)
    address = db.Column(db.String(120), nullable = False)
    lat = db.Column(db.Float, nullable = False)
    lng = db.Column(db.Float, nullable = False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable = False)

class Game(db.Model):
    __tablename__ = "games"
    id = db.Column(db.Integer, primary_key = True)
    court_id = db.Column(db.Integer, db.ForeignKey("courts.id"), nullable = False)
    host_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable = False)
    time = db.Column(db.DateTime, nullable = False)
    max_players = db.Column(db.Integer, default = 10)

class GamePlayer(db.Model):
    __tablename__ = "game_players"
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), primary_key = True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key = True)
    joined_at = db.Column(db.DateTime, default = datetime.now)

class PlayerStats(db.Model):
    __tablename__ = "player_stats"
    id = db.Column(db.Integer, primary_key = True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable = False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable = False)
    points = db.Column(db.Integer, default = 0)
    rebounds = db.Column(db.Integer, default = 0)
    assists = db.Column(db.Integer, default = 0)

class PlayerRatings(db.Model):
    __tablename__ = "player_ratings"
    id = db.Column(db.Integer, primary_key = True)
    from_user = db.Column(db.Integer, db.ForeignKey("users.id"), nullable = False)
    to_user = db.Column(db.Integer, db.ForeignKey("users.id"), nullable = False)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable = False)
    score = db.Column(db.Integer, nullable = False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default = datetime.now)
