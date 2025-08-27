from flask import Flask, render_template, request, redirect, session, url_for
from app.extensions import db, migrate, login_mgr  
from config import DevelopmentConfig
from werkzeug.security import generate_password_hash, check_password_hash

def create_app():
    app = Flask(__name__)
    app.config.from_object(DevelopmentConfig)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_mgr.init_app(app)

    #Routes
    @app.route("/")
    def home():
        if "username" in session:
            return redirect(url_for('dashboard'))
        return render_template("index.html")

    #Login
    @app.route("/login", methods=["POST"])
    def login():
        #collecting info from form
        username = request.form['username']
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template("index.html")

    #Register
    @app.route("/register", methods=["POST"])
    def register():
        username = request.form['username']
        password = request.form["password"]
        if user:
            return render_template("index.html", error="User already registered.")
        else:
            new_user = User(username=username)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            session['username'] = username
            return redirect(url_for('dashboard'))
    
    

    return app
