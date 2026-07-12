import os
from werkzeug.utils import secure_filename
from flask import current_app

ALLOWED_EXTENSIONS = {'pdf', 'xlsx', 'xls', 'png', 'jpg', 'jpeg'}

def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_secure_filepath(file_storage, subfolder: str = '') -> tuple[str, str]:
    """
    Validates file upload, secures filename, saves to target upload directory,
    and returns tuple of (filename, absolute_filepath).
    """
    if not file_storage or file_storage.filename == '':
        raise ValueError("No file provided for upload.")
        
    filename = secure_filename(file_storage.filename)
    if not allowed_file(filename):
        raise ValueError("Invalid file extension. Allowed: PDF, Excel, PNG, JPG.")
        
    upload_dir = current_app.config.get('UPLOAD_FOLDER', os.path.join(current_app.root_path, 'static', 'uploads'))
    if subfolder:
        upload_dir = os.path.join(upload_dir, subfolder)
    os.makedirs(upload_dir, exist_ok=True)
    
    filepath = os.path.join(upload_dir, filename)
    file_storage.save(filepath)
    return filename, filepath
