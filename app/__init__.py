from flask import Flask, render_template, request, redirect
from app.extensions import db, migrate, login_mgr  
from config import DevelopmentConfig

def create_app():
    app = Flask(__name__)
    app.config.from_object(DevelopmentConfig)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_mgr.init_app(app)

    #Flask Login
    @app.route("/")
    def index():
        return render_template("index.html")

    return app
