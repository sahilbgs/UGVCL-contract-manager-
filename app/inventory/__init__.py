from flask import Blueprint

inventory = Blueprint('inventory', __name__)
inventory.strict_slashes = False

from app.inventory import routes
