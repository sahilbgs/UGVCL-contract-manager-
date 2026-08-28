import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'default-safe-fallback-secret-key-for-development-and-testing')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload limit
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload folder: top-level uploads/ directory
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')

class DevConfig(Config):
    DEBUG = True
    
    def __init__(self):
        super().__init__()
        # If SECRET_KEY is the default fallback, alert the developer but don't crash
        if self.SECRET_KEY == 'default-safe-fallback-secret-key-for-development-and-testing':
            print("[WARNING] SECRET_KEY not found in environment. Using default local development key.")
            
        db_user = os.environ.get('MYSQL_USER', '')
        if db_user:
            db_host = os.environ.get('MYSQL_HOST', 'localhost')
            db_pass = os.environ.get('MYSQL_PASSWORD', '')
            db_name = os.environ.get('MYSQL_DATABASE', 'ugvcl_contract_manager')
            import urllib.parse
            encoded_pass = urllib.parse.quote_plus(db_pass)
            self.SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{db_user}:{encoded_pass}@{db_host}/{db_name}"
        else:
            self.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(self.BASE_DIR, 'ugvcl_contract_manager.db')

class ProdConfig(Config):
    DEBUG = False
    TESTING = False
    
    def __init__(self):
        super().__init__()
        # Enforce that a customized secret key is provided in production
        env_secret = os.environ.get('SECRET_KEY')
        if not env_secret or env_secret == 'default-safe-fallback-secret-key-for-development-and-testing':
            raise RuntimeError("CRITICAL SECURITY ERROR: SECRET_KEY environment variable is missing or insecure in production environment!")
            
        db_user = os.environ.get('MYSQL_USER', '')
        if db_user:
            db_host = os.environ.get('MYSQL_HOST', 'localhost')
            db_pass = os.environ.get('MYSQL_PASSWORD', '')
            db_name = os.environ.get('MYSQL_DATABASE', 'ugvcl_contract_manager')
            import urllib.parse
            encoded_pass = urllib.parse.quote_plus(db_pass)
            self.SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{db_user}:{encoded_pass}@{db_host}/{db_name}"
        else:
            print("[CRITICAL WARNING] Running SQLite in production mode! High risk of database write concurrency locks.")
            self.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(self.BASE_DIR, 'ugvcl_contract_manager.db')

class TestingConfig(Config):
    DEBUG = False
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

config_by_name = {
    'development': DevConfig,
    'production': ProdConfig,
    'testing': TestingConfig
}
