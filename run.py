import os
from app import create_app
from app.extensions import db
from app.cli import seed_users, seed_materials

app = create_app()

# Initialize tables and seeds on startup
with app.app_context():
    db.create_all()
    seed_users()
    seed_materials()

if __name__ == '__main__':
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    app.run(host=host, port=port, debug=app.config.get('DEBUG', True))
