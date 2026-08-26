from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db          = SQLAlchemy()     # ORM
migrate     = Migrate()        # Alembic migrations
login_mgr   = LoginManager()   # User session management
csrf        = CSRFProtect()   # CSRF tokens on every state-changing request
