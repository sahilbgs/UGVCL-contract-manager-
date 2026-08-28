from flask import Blueprint

work_orders = Blueprint('work_orders', __name__)
work_orders.strict_slashes = False

from app.work_orders import routes
