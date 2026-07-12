from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user
from models import db, Material

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role != 'admin':
            flash("Permission Denied: Admin access required.", "danger")
            return redirect(url_for('manager.manager_dashboard'))
        return f(*args, **kwargs)
    return decorated_function

COMMON_MATERIALS = [
    ("PSC Pole 8 MTR", "Nos"),
    ("PSC Pole 10 MTR", "Nos"),
    ("Conducto 34mm 2wire", "Mtr"),
    ("Conductor 34mm  4wire", "Mtr"),
    ("Conductor 55 mm 3wire", "Mtr"),
    ("Transformer 10 KVA", "Nos"),
    ("Transformer 25 KVA", "Nos"),
    ("Transformer 63 KVA", "Nos"),
    ("Three Hole Parties", "Nos"),
    ("V-x arm", "Nos"),
    ("Top Fitting", "Nos"),
    ("Side Clamp", "Nos"),
    ("11kv Comp Pin Insulator", "Nos"),
    ("11kv Pin Insulator", "Nos"),
    ("11kv G.I. Pin", "Nos"),
    ("11kv Shackle Insulator", "Nos"),
    ("11kv Shackle H/W", "Set."),
    ("Earthing Plate/Coil", "Nos"),
    ("G.I. Wire 8 No.", "Kg"),
    ("Stay Wire 7/12", "Kg"),
    ("Stay Clamp Pair", "Pair"),
    ("Turn Buckle", "Nos"),
    ("Eye Bolt", "Nos"),
    ("Stay Insulator", "Nos"),
    ("Anchor Road", "Nos"),
    ("C.C. Block", "Nos"),
    ("Angle 9' Fut(65*65*6)", "Fut"),
    ("Angle 9' Fut(50*50*6)", "Fut"),
    ("Angle 4' Fut", "Fut"),
    ("Angle 2'.6'' Fut", "Fut"),
    ("11kv D.O Angle / Fuse", "Nos"),
    ("U CLAIMP", "Nos"),
    ("LT SHACKLE", "Nos"),
    ("PVC PIPE", "Nos"),
    ("L.A ", "Nos"),
    ("MS Chanal-6 fut", "Nos"),
    ("Bolt-2.6\"(with nut)", "Nos"),
    ("Bolt-5.0\"(with nut)", "Nos"),
    ("Bolt-7.0\"(with nut)", "Nos"),
    ("Bolt-11.0\"(with nut)", "Nos")
]

def seed_materials():
    """Seeds typical material items into central inventory database."""
    try:
        for name, unit in COMMON_MATERIALS:
            m = Material.query.filter_by(name=name).first()
            if not m:
                new_m = Material(name=name, unit=unit, opening_stock=0.0)
                db.session.add(new_m)
        db.session.commit()
    except Exception as e:
        print(f"Error seeding materials: {e}")
        db.session.rollback()
