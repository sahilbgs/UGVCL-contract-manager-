from flask import Blueprint

auth = Blueprint('auth', __name__)
auth.strict_slashes = False

from app.auth import routes
