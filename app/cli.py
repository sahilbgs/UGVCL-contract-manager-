import os
import click
from flask import Blueprint
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash
from app.extensions import db
from app.models import User, Material, MaterialMapping

seed_cli = Blueprint('seed', __name__)

COMMON_MATERIALS = [
    ("Conducto 34mm 2wire", "Mtr", "0102000031"),
    ("Conductor 34mm 5wire", "Mtr", "0102000031"),
    ("PSC Pole 8 MTR", "Nos", "2611000003"),
    ("PSC Pole 10 MTR", "Nos", "2611000010"),
    ("Three Hole Parties", "Nos", None),
    ("V-x arm", "Nos", "2609000034"),
    ("Top Fitting", "Nos", "2601000084"),
    ("Side Clamp", "Nos", "2601000049"),
    ("Earthing Plate/Coil", "Nos", "0901000024"),
    ("G.I. Wire 8 No.", "Kg", "0103000002"),
    ("Stay Wire 7/12", "Kg", "0103000014"),
    ("Stay Clamp Pair", "Pair", "2601000069"),
    ("Turn Buckle", "Nos", "2614000009"),
    ("Eye Bolt", "Nos", "2614000012"),
    ("Stay Insulator", "Nos", "2003000001"),
    ("Anchor Road", "Nos", "2614000002"),
    ("C.C. Block", "Nos", "2614000013"),
    ("U CLAIMP", "Nos", "2601000040"),
    ("LT SHACKLE", "Nos", "2002000001"),
    ("PVC PIPE", "Nos", "2801000016"),
    ("Bolt-2.6\"(with nut)", "Nos", "2010000002"),
    ("Bolt-5.0\"(with nut)", "Nos", "2010000002"),
    ("Bolt-7.0\"(with nut)", "Nos", "2010000002"),
    ("Bolt-11.0\"(with nut)", "Nos", "2010000002"),
    
    # Other items
    ("Conductor 34mm  4wire", "Mtr", "0102000031"),
    ("Conductor 55 mm 3wire", "Mtr", "0102000033"),
    ("Transformer 10 KVA", "Nos", None),
    ("Transformer 25 KVA", "Nos", None),
    ("Transformer 63 KVA", "Nos", None),
    ("11kv Comp Pin Insulator", "Nos", "2001000010"),
    ("11kv Pin Insulator", "Nos", "2001000010"),
    ("11kv G.I. Pin", "Nos", "2010000010"),
    ("11kv Shackle Insulator", "Nos", "2006000006"),
    ("11kv Shackle H/W", "Set.", "2010000077"),
    ("Angle 9' Fut(65*65*6)", "Fut", None),
    ("Angle 9' Fut(50*50*6)", "Fut", None),
    ("Angle 4' Fut", "Fut", None),
    ("Angle 2'.6'' Fut", "Fut", None),
    ("11kv D.O Angle / Fuse", "Nos", None),
    ("L.A ", "Nos", None),
    ("MS Chanal-6 fut", "Nos", None),
]

SEED_MAPPINGS = [
    ('u clamp', '2601000040'),
    ('c clamp', '2601000040'),
    ('u claimp', '2601000040'),
    ('lt shackle', '2002000001'),
    ('shackle insulator', '2002000001'),
    ('440v lt shackle', '2002000001'),
    ('440 v lt shackle', '2002000001'),
    ('earthing coil', '0901000024'),
    ('gi earthing coil', '0901000024'),
    ('earthing plate/coil', '0901000024'),
    ('pvc pipe', '2801000016'),
    ('hd rigid pvc', '2801000016'),
    ('h d rigid pvc', '2801000016'),
    ('wire 8', '0103000002'),
    ('wire no.8', '0103000002'),
    ('wire no. 8', '0103000002'),
    ('gi wire 8', '0103000002'),
    ('gi wire no.8', '0103000002'),
    ('gi wire no. 8', '0103000002'),
    ('conductor 34', '0102000031'),
    ('conducto 34', '0102000031'),
    ('weasel', '0102000031'),
    ('alloy conductor 34', '0102000031'),
    ('aluminium alloy conductor 34', '0102000031'),
    ('stay clamp', '2601000069'),
    ('stay clamp pair', '2601000069'),
    ('anchor rod', '2614000002'),
    ('anchor road', '2614000002'),
    ('turn buckle', '2614000009'),
    ('eye bolt', '2614000012'),
    ('guy insulator', '2003000001'),
    ('stay insulator', '2003000001'),
    ('stay insulator ht', '2003000001'),
    ('pole 8', '2611000003'),
    ('pole-8', '2611000003'),
    ('psc pole 8', '2611000003'),
    ('psc pole-8', '2611000003'),
    ('pole 10', '2611000010'),
    ('pole-10', '2611000010'),
    ('psc pole 10', '2611000010'),
    ('psc pole-10', '2611000010'),
    ('earthing plate', '0901000007'),
    ('wire 10', '0103000003'),
    ('wire no.10', '0103000003'),
    ('wire no. 10', '0103000003'),
    ('gi wire 10', '0103000003'),
    ('gi wire no.10', '0103000003'),
    ('gi wire no. 10', '0103000003'),
    ('cc block', '2614000013'),
    ('c.c.block', '2614000013'),
    ('block', '2614000013'),
    ('stay wire 7/12', '0103000014'),
    ('stay wire', '0103000014'),
    ('conductor 55', '0102000033'),
    ('conducto 55', '0102000033'),
    ('alloy conductor 55', '0102000033'),
    ('side clamp', '2601000049'),
    ('v-cross', '2609000034'),
    ('v cross', '2609000034'),
    ('vcross', '2609000034'),
    ('top fitting', '2601000084'),
    ('comp pin insulator', '2001000010'),
    ('pin insulator', '2001000010'),
    ('gi pin', '2010000010'),
    ('g.i.pin', '2010000010'),
    ('11kv shackle insulator', '2006000006'),
    ('11kv shackle hard ware', '2010000077'),
    ('11kv shackle h/w', '2010000077'),
    ('shackle hard ware', '2010000077'),
    ('shackle h/w', '2010000077'),
    ('bolts + nuts', '2010000002'),
    ('bolts & nuts', '2010000002'),
    ('gi bolts', '2010000002'),
    ('g.i. bolts', '2010000002'),
    ('bolt-2.6', '2010000002'),
    ('bolt-5.0', '2010000002'),
    ('bolt-7.0', '2010000002'),
    ('bolt-11.0', '2010000002'),
]

def seed_users():
    """Seeds admin and manager users from environment variables."""
    admin_user = os.environ.get('ADMIN_USERNAME', 'admin@gmail.com')
    admin_pass = os.environ.get('ADMIN_PASSWORD')
    manager_user = os.environ.get('MANAGER_USERNAME', 'manager@gmail.com')
    manager_pass = os.environ.get('MANAGER_PASSWORD')

    if not admin_pass or not manager_pass:
        print("[WARNING] ADMIN_PASSWORD or MANAGER_PASSWORD environment variables not set. Using local development defaults.")
        admin_pass = admin_pass or 'admin_dev_pass_123'
        manager_pass = manager_pass or 'manager_dev_pass_123'

    try:
        # Seed Admin
        admin = User.query.filter_by(username=admin_user).first()
        if not admin:
            old_admin = User.query.filter_by(username='admin').first()
            if old_admin:
                db.session.delete(old_admin)
            hashed_pw = generate_password_hash(admin_pass, method='pbkdf2:sha256')
            admin = User(username=admin_user, password_hash=hashed_pw, role='admin')
            db.session.add(admin)
            
        # Seed Manager
        manager = User.query.filter_by(username=manager_user).first()
        if not manager:
            hashed_pw = generate_password_hash(manager_pass, method='pbkdf2:sha256')
            manager = User(username=manager_user, password_hash=hashed_pw, role='manager')
            db.session.add(manager)
            
        db.session.commit()
        print(f"Users verified/seeded: {admin_user} and {manager_user}")
    except Exception as e:
        print(f"Error seeding users: {e}")
        db.session.rollback()

def seed_materials():
    """Seeds typical material items and alias mappings into the database."""
    try:
        # Seed Materials
        for name, unit, code in COMMON_MATERIALS:
            m = Material.query.filter_by(name=name).first()
            if not m:
                new_m = Material(name=name, unit=unit, opening_stock=0.0, item_code=code)
                db.session.add(new_m)
            else:
                if code and not m.item_code:
                    m.item_code = code
        db.session.commit()
        
        # Seed Mappings
        for alias, item_code in SEED_MAPPINGS:
            existing = MaterialMapping.query.filter_by(alias=alias).first()
            if not existing:
                new_map = MaterialMapping(alias=alias, item_code=item_code)
                db.session.add(new_map)
        db.session.commit()
        print("Materials and mappings verified/seeded.")
    except Exception as e:
        print(f"Error seeding materials/mappings: {e}")
        db.session.rollback()

@seed_cli.cli.command("seed-users")
@with_appcontext
def seed_users_command():
    """Seeds admin and manager users."""
    seed_users()

@seed_cli.cli.command("seed-materials")
@with_appcontext
def seed_materials_command():
    """Seeds material items and alias mappings."""
    seed_materials()
