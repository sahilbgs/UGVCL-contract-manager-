import os
from flask import Flask
from config import config_by_name
from app.extensions import db, login_manager, csrf, migrate

def create_app(config_name=None):
    if not config_name:
        config_name = os.environ.get('FLASK_ENV', 'development')
        
    app = Flask(__name__, static_folder='../static')
    
    # Load configuration
    config_class = config_by_name.get(config_name, config_by_name['development'])
    app.config.from_object(config_class())
    
    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    
    # Setup login manager views
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'
    
    # User loader configuration
    from app.models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
        
    # Register blueprints
    from app.auth.routes import auth as auth_blueprint
    from app.main.routes import main as main_blueprint
    from app.work_orders.routes import work_orders as work_orders_blueprint
    from app.inventory.routes import inventory as inventory_blueprint
    from app.manager.routes import manager as manager_blueprint
    
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(main_blueprint)
    app.register_blueprint(work_orders_blueprint, url_prefix='/work-orders')
    app.register_blueprint(inventory_blueprint, url_prefix='/inventory')
    app.register_blueprint(manager_blueprint, url_prefix='/manager')
    
    # Register CLI commands
    from app.cli import seed_cli
    app.register_blueprint(seed_cli)
    
    return app
