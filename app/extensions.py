from flask_sqlalchemy import SQLAlchemy
from flask_migrate    import Migrate
from flask_login      import LoginManager

db          = SQLAlchemy()     # ORM
migrate     = Migrate()        # Alembic migrations
login_mgr   = LoginManager()   # User session management
