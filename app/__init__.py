from flask import Flask
from app.extensions import db, migrate, login_mgr  

def create_app():
    app = Flask(__name__)
    app.config.from_object("config.DevelopmentConfig")

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_mgr.init_app(app)

    return app