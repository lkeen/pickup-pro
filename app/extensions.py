from authlib.integrations.flask_client import OAuth
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db          = SQLAlchemy()     # ORM
migrate     = Migrate()        # Alembic migrations
login_mgr   = LoginManager()   # User session management
csrf        = CSRFProtect()   # CSRF tokens on every state-changing request
limiter     = Limiter(key_func=get_remote_address)  # brute-force throttling
oauth       = OAuth()          # third-party sign-in (Google)
cache       = Cache()          # response/query cache (Redis)
