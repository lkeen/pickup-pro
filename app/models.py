from datetime import datetime
from app.extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key = True)
    username = db.Column(db.String(64), unique = True, nullable = False)
    password_hash = db.Column(db.String(255), unique = False, nullable = False)
    email = db.Column(db.String(254), unique = True, nullable = False)
    created_at = db.Column(db.DateTime, default = datetime.now)

    courts = db.relationship('Court', backref='creator', lazy=True)
    hosted_games = db.relationship('Game', backref='host', lazy=True)
    games = db.relationship('Game', secondary='game_players', back_populates='players')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Court(db.Model):
    __tablename__ = "courts"
    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.String(64), nullable = False)
    address = db.Column(db.String(120), nullable = False)
    lat = db.Column(db.Float, nullable = False)
    lng = db.Column(db.Float, nullable = False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable = False)
    created_at = db.Column(db.DateTime, default = datetime.now)

    games = db.relationship('Game', backref='court', lazy=True)

class Game(db.Model):
    __tablename__ = "games"
    id = db.Column(db.Integer, primary_key = True)
    court_id = db.Column(db.Integer, db.ForeignKey("courts.id"), nullable = False)
    host_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable = False)
    time = db.Column(db.DateTime, nullable = False)
    max_players = db.Column(db.Integer, default = 10)
    created_at = db.Column(db.DateTime, default = datetime.now)

    players = db.relationship('User', secondary='game_players', back_populates='games')

    @property
    def current_players(self):
        return len(self.players)

    @property
    def spots_available(self):
        return self.max_players - self.current_players

    def can_join(self, user):
        return (self.current_players < self.max_players and
                user not in self.players)

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
    created_at = db.Column(db.DateTime, default = datetime.now)
    updated_at = db.Column(db.DateTime, default = datetime.now, onupdate = datetime.now)

    game = db.relationship('Game', backref='player_stats')
    user = db.relationship('User', backref='player_stats')

    __table_args__ = (db.UniqueConstraint('game_id', 'user_id', name='unique_game_user_stats'),)

class PlayerRating(db.Model):
    __tablename__ = "player_ratings"
    id = db.Column(db.Integer, primary_key = True)
    from_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable = False)
    to_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable = False)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable = False)
    rating = db.Column(db.Integer, nullable = False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default = datetime.now)

    game = db.relationship('Game', backref='player_ratings')
    from_user = db.relationship('User', foreign_keys=[from_user_id], backref='ratings_given')
    to_user = db.relationship('User', foreign_keys=[to_user_id], backref='ratings_received')

    __table_args__ = (
        db.UniqueConstraint('from_user_id', 'to_user_id', 'game_id', name='unique_game_user_rating'),
        db.CheckConstraint('rating >= 1 AND rating <= 5', name='rating_range'),
        db.CheckConstraint('from_user_id != to_user_id', name='no_self_rating')
    )
