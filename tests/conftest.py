import os
import tempfile
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from werkzeug.security import generate_password_hash

# must be set before app is imported so the tests never touch trekking.db
os.environ['TREK_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'test.db')

from app import app as flask_app  # noqa: E402
from models import db, User, Trek  # noqa: E402

PASSWORD = 'pass1234'
PASSWORD_HASH = generate_password_hash(PASSWORD)  # hashing is slow, so do it once
EMAILS = {
    'admin': 'admin@t.com',
    'staff': 'staff@t.com',
    'other_staff': 'other@t.com',
    'pending_staff': 'pending@t.com',
    'tia': 'tia@t.com',
    'tom': 'tom@t.com',
    'bob': 'bob@t.com',
}


@pytest.fixture
def app():
    flask_app.config['TESTING'] = True
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    return flask_app


@pytest.fixture
def world(app):
    """A small, known dataset. Returns ids only, so nothing is tied to a closed session."""
    with app.app_context():
        def user(name, key, role, status='active'):
            u = User(name=name, email=EMAILS[key], password_hash=PASSWORD_HASH,
                     role=role, status=status, phone='9000000000')
            db.session.add(u)
            return u

        admin = user('Admin', 'admin', 'admin')
        staff = user('Sam Staff', 'staff', 'staff')
        other = user('Olly Staff', 'other_staff', 'staff')
        pending = user('Pat Pending', 'pending_staff', 'staff', 'pending')
        tia = user('Tia Trekker', 'tia', 'trekker')
        tom = user('Tom Trekker', 'tom', 'trekker')
        bob = user('Bob Blocked', 'bob', 'trekker', 'blacklisted')
        db.session.commit()

        today = date.today()

        def trek(name, status, total, available, owner=None, price=1000):
            t = Trek(name=name, location='Hills', difficulty='Easy', duration=2, price=price,
                     total_slots=total, available_slots=available,
                     assigned_staff_id=owner.id if owner else None, status=status,
                     start_date=today + timedelta(days=10), end_date=today + timedelta(days=12),
                     description='A test trek.')
            db.session.add(t)
            return t

        open_trek = trek('Open Trek', 'Open', 2, 2, staff)
        full_trek = trek('Full Trek', 'Open', 1, 0, staff)
        closed_trek = trek('Closed Trek', 'Closed', 5, 5, staff)
        pending_trek = trek('Pending Trek', 'Pending', 5, 5)
        other_trek = trek('Other Trek', 'Open', 5, 5, other)
        db.session.commit()

        return SimpleNamespace(
            admin_id=admin.id, staff_id=staff.id, other_staff_id=other.id,
            pending_staff_id=pending.id, tia_id=tia.id, tom_id=tom.id, bob_id=bob.id,
            open_id=open_trek.id, full_id=full_trek.id, closed_id=closed_trek.id,
            pending_trek_id=pending_trek.id, other_trek_id=other_trek.id,
        )


@pytest.fixture
def login_as(app, world):
    def _login(key):
        client = app.test_client()
        resp = client.post('/login', data={'email': EMAILS[key], 'password': PASSWORD})
        # a failed login also redirects, but back to /login
        assert resp.status_code == 302 and '/login' not in resp.headers['Location'], f'login failed for {key}'
        return client
    return _login


@pytest.fixture
def anon(app):
    return app.test_client()


@pytest.fixture
def query(app):
    """Run a function inside its own app context and return what it returns."""
    def _run(fn):
        with app.app_context():
            return fn()
    return _run
