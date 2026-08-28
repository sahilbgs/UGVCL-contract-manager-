from flask import Blueprint

manager = Blueprint('manager', __name__)
manager.strict_slashes = False

from app.manager import routes
