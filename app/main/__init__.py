from flask import Blueprint

main = Blueprint('main', __name__)
main.strict_slashes = False

from app.main import routes
