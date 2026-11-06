import pytest

from models import db, User, Trek, Booking, Payment, AuditLog

# (method, path, role that may call it)
RESTRICTED = [
    ('GET', '/api/admin/stats', 'admin'),
    ('GET', '/api/admin/users', 'admin'),
    ('POST', '/api/admin/treks', 'admin'),
    ('PATCH', '/api/admin/treks/1', 'admin'),
    ('DELETE', '/api/admin/treks/1', 'admin'),
    ('PATCH', '/api/admin/users/1/status', 'admin'),
    ('GET', '/api/staff/treks', 'staff'),
    ('PATCH', '/api/staff/treks/1', 'staff'),
    ('GET', '/api/staff/treks/1/participants', 'staff'),
    ('GET', '/api/bookings', 'trekker'),
    ('POST', '/api/bookings', 'trekker'),
    ('PATCH', '/api/bookings/1/cancel', 'trekker'),
]
ROLE_USERS = {'admin': 'admin', 'staff': 'staff', 'trekker': 'tia'}

NEW_TREK = {
    'name': 'New Trek', 'location': 'Ridge', 'difficulty': 'Hard', 'duration': 3,
    'total_slots': 10, 'price': 4000, 'start_date': '2031-05-01', 'end_date': '2031-05-04',
}


def call(client, method, path, body=None):
    return client.open(path, method=method, json=body if body is not None else {})


# ---- access control -------------------------------------------------------

def test_there_are_twelve_restricted_endpoints():
    assert len(RESTRICTED) == 12


@pytest.mark.parametrize('method,path,role', RESTRICTED)
def test_anonymous_gets_json_401(anon, world, method, path, role):
    resp = call(anon, method, path)
    assert resp.status_code == 401
    assert resp.get_json()['error']


@pytest.mark.parametrize('method,path,role', RESTRICTED)
def test_other_roles_get_json_403(login_as, world, method, path, role):
    for other_role, key in ROLE_USERS.items():
        if other_role == role:
            continue
        resp = call(login_as(key), method, path)
        assert resp.status_code == 403, f'{key} reached {method} {path}'
        assert resp.get_json()['error']


def test_pending_staff_can_log_in_but_not_use_the_api(login_as, world):
    client = login_as('pending_staff')
    assert call(client, 'GET', '/api/staff/treks').status_code == 403


def test_blacklisted_account_cannot_log_in(app, world):
    resp = app.test_client().post('/login', data={'email': 'bob@t.com', 'password': 'pass1234'})
    assert resp.status_code == 302 and '/login' in resp.headers['Location']


def test_blacklisting_mid_session_cuts_api_access(login_as, world):
    tia, admin = login_as('tia'), login_as('admin')
    assert call(tia, 'GET', '/api/bookings').status_code == 200
    assert call(admin, 'PATCH', f'/api/admin/users/{world.tia_id}/status', {'status': 'blacklisted'}).status_code == 200
    assert call(tia, 'GET', '/api/bookings').status_code == 403
    assert call(tia, 'GET', '/api/bookings').status_code == 401  # session was cleared


# ---- public endpoints -----------------------------------------------------

def test_public_list_shows_open_treks_only(anon, world):
    names = {t['name'] for t in anon.get('/api/treks').get_json()}
    assert names == {'Open Trek', 'Full Trek', 'Other Trek'}


def test_public_detail_hides_non_open_treks(anon, world):
    assert anon.get(f'/api/treks/{world.open_id}').status_code == 200
    assert anon.get(f'/api/treks/{world.pending_trek_id}').status_code == 404
    assert anon.get(f'/api/treks/{world.closed_id}').status_code == 404
    assert anon.get('/api/treks/99999').get_json() == {'error': 'Not found.'}


# ---- admin ----------------------------------------------------------------

def test_admin_stats(login_as, world):
    data = login_as('admin').get('/api/admin/stats').get_json()
    assert data == {'treks': 5, 'trekkers': 3, 'staff': 3, 'bookings': 0, 'pending_staff': 1}


def test_admin_user_list_and_filters(login_as, world):
    admin = login_as('admin')
    assert len(admin.get('/api/admin/users').get_json()) == 6  # admin account is never listed
    staff = admin.get('/api/admin/users?role=staff').get_json()
    assert {u['role'] for u in staff} == {'staff'}
    pending = admin.get('/api/admin/users?status=pending').get_json()
    assert [u['name'] for u in pending] == ['Pat Pending']
    assert admin.get('/api/admin/users?role=admin').status_code == 400


def test_admin_creates_trek(login_as, query, world):
    resp = call(login_as('admin'), 'POST', '/api/admin/treks', NEW_TREK)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['status'] == 'Pending' and data['available_slots'] == data['total_slots'] == 10
    assert data['price'] == 4000
    assert query(lambda: AuditLog.query.filter_by(action='trek.create', target_id=data['id']).count()) == 1


@pytest.mark.parametrize('change,fragment', [
    ({'difficulty': 'Brutal'}, 'difficulty'),
    ({'duration': True}, 'duration'),
    ({'total_slots': 0}, 'total_slots'),
    ({'price': -5}, 'price'),
    ({'start_date': '31/01/2031'}, 'start_date'),
    ({'end_date': '2031-04-01'}, 'end_date cannot be before'),
    ({'status': 'Open'}, 'Unknown fields'),
])
def test_admin_create_validation(login_as, change, fragment):
    resp = call(login_as('admin'), 'POST', '/api/admin/treks', {**NEW_TREK, **change})
    assert resp.status_code == 400
    assert fragment in resp.get_json()['error']


def test_admin_create_requires_the_core_fields(login_as):
    body = {k: v for k, v in NEW_TREK.items() if k != 'name'}
    resp = call(login_as('admin'), 'POST', '/api/admin/treks', body)
    assert resp.status_code == 400
    assert 'Missing fields: name' in resp.get_json()['error']


def test_create_rejects_non_json_body(login_as):
    resp = login_as('admin').post('/api/admin/treks', data='not json', content_type='text/plain')
    assert resp.status_code == 400


def test_admin_updates_trek_fields_slots_status_and_staff(login_as, query, world):
    admin = login_as('admin')
    url = f'/api/admin/treks/{world.pending_trek_id}'
    resp = call(admin, 'PATCH', url, {'price': 2500, 'total_slots': 8, 'assigned_staff_id': world.staff_id})
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['price'] == 2500 and data['total_slots'] == 8 and data['available_slots'] == 8
    assert data['assigned_staff'] == 'Sam Staff'
    assert data['status'] == 'Approved'  # assigning staff promotes Pending -> Approved
    assert call(admin, 'PATCH', url, {'status': 'Open'}).get_json()['status'] == 'Open'
    actions = query(lambda: {a.action for a in AuditLog.query.filter_by(target_id=world.pending_trek_id)})
    assert {'trek.update', 'trek.slots', 'trek.assign', 'trek.status'} <= actions


def test_admin_patch_validation(login_as, world):
    admin = login_as('admin')
    url = f'/api/admin/treks/{world.open_id}'
    assert call(admin, 'PATCH', url, {}).status_code == 400
    assert call(admin, 'PATCH', url, {'status': 'Done'}).status_code == 400
    assert call(admin, 'PATCH', url, {'assigned_staff_id': world.pending_staff_id}).status_code == 400
    assert call(admin, 'PATCH', url, {'assigned_staff_id': world.tia_id}).status_code == 400
    assert call(admin, 'PATCH', url, {'assigned_staff_id': 'x'}).status_code == 400
    assert call(admin, 'PATCH', url, {'start_date': '2099-01-01'}).status_code == 400  # after end_date
    assert call(admin, 'PATCH', '/api/admin/treks/99999', {'price': 1}).status_code == 404


def test_failed_patch_changes_nothing(login_as, query, world):
    admin = login_as('admin')
    url = f'/api/admin/treks/{world.open_id}'
    call(admin, 'PATCH', url, {'name': 'Renamed', 'assigned_staff_id': world.pending_staff_id})
    assert query(lambda: db.session.get(Trek, world.open_id).name) == 'Open Trek'


def test_admin_can_unassign_staff(login_as, world):
    resp = call(login_as('admin'), 'PATCH', f'/api/admin/treks/{world.open_id}', {'assigned_staff_id': None})
    assert resp.get_json()['assigned_staff'] is None


def test_completing_a_trek_through_the_api_completes_its_bookings(login_as, query, world):
    call(login_as('tia'), 'POST', '/api/bookings', {'trek_id': world.open_id})
    call(login_as('tom'), 'POST', '/api/bookings', {'trek_id': world.open_id})
    call(login_as('admin'), 'PATCH', f'/api/admin/treks/{world.open_id}', {'status': 'Completed'})
    assert query(lambda: {b.status for b in Booking.query.filter_by(trek_id=world.open_id)}) == {'Completed'}
    entry = query(lambda: AuditLog.query.filter_by(action='trek.status').first().detail)
    assert '2 bookings completed' in entry


def test_admin_deletes_trek_with_its_bookings_and_payments(login_as, query, world):
    call(login_as('tia'), 'POST', '/api/bookings', {'trek_id': world.open_id})
    resp = login_as('admin').delete(f'/api/admin/treks/{world.open_id}')
    assert resp.status_code == 204 and resp.data == b''
    assert query(lambda: db.session.get(Trek, world.open_id)) is None
    assert query(lambda: (Booking.query.count(), Payment.query.count())) == (0, 0)
    assert login_as('admin').delete(f'/api/admin/treks/{world.open_id}').status_code == 404


def test_admin_sets_account_status(login_as, query, world):
    admin = login_as('admin')
    url = f'/api/admin/users/{world.pending_staff_id}/status'
    assert call(admin, 'PATCH', url, {'status': 'active'}).get_json()['status'] == 'active'
    assert query(lambda: AuditLog.query.filter_by(action='staff.approve').count()) == 1
    assert call(admin, 'PATCH', url, {'status': 'blacklisted'}).get_json()['status'] == 'blacklisted'
    assert call(admin, 'PATCH', f'/api/admin/users/{world.bob_id}/status', {'status': 'active'}).status_code == 200
    assert query(lambda: AuditLog.query.filter_by(action='user.reinstate').count()) == 1


def test_account_status_validation_and_admin_is_untouchable(login_as, world):
    admin = login_as('admin')
    url = f'/api/admin/users/{world.tia_id}/status'
    assert call(admin, 'PATCH', url, {'status': 'pending'}).status_code == 400
    assert call(admin, 'PATCH', url, {'status': 'active', 'role': 'admin'}).status_code == 400
    assert call(admin, 'PATCH', url, {}).status_code == 400
    assert call(admin, 'PATCH', f'/api/admin/users/{world.admin_id}/status', {'status': 'blacklisted'}).status_code == 404


# ---- staff ----------------------------------------------------------------

def test_staff_sees_only_their_own_treks(login_as, world):
    staff = login_as('staff')
    call(login_as('tia'), 'POST', '/api/bookings', {'trek_id': world.open_id})
    treks = staff.get('/api/staff/treks').get_json()
    assert {t['name'] for t in treks} == {'Open Trek', 'Full Trek', 'Closed Trek'}
    counts = {t['name']: t['participant_count'] for t in treks}
    assert counts['Open Trek'] == 1 and counts['Closed Trek'] == 0


def test_staff_updates_slots_and_status(login_as, query, world):
    staff = login_as('staff')
    url = f'/api/staff/treks/{world.open_id}'
    call(login_as('tia'), 'POST', '/api/bookings', {'trek_id': world.open_id})
    data = call(staff, 'PATCH', url, {'total_slots': 6}).get_json()
    assert data['total_slots'] == 6 and data['available_slots'] == 5  # the booked seat is kept
    assert call(staff, 'PATCH', url, {'status': 'Closed'}).get_json()['status'] == 'Closed'
    who = query(lambda: {(a.actor_role, a.action) for a in AuditLog.query})
    assert ('staff', 'trek.slots') in who and ('staff', 'trek.status') in who


def test_staff_cannot_set_statuses_outside_their_remit(login_as, world):
    staff = login_as('staff')
    url = f'/api/staff/treks/{world.open_id}'
    assert call(staff, 'PATCH', url, {'status': 'Pending'}).status_code == 400
    assert call(staff, 'PATCH', url, {'status': 'Bogus'}).status_code == 400
    assert call(staff, 'PATCH', url, {'price': 1}).status_code == 400  # staff cannot reprice
    assert call(staff, 'PATCH', url, {}).status_code == 400


def test_staff_cannot_touch_treks_assigned_to_someone_else(login_as, world):
    staff = login_as('staff')
    assert call(staff, 'PATCH', f'/api/staff/treks/{world.other_trek_id}', {'status': 'Closed'}).status_code == 404
    assert staff.get(f'/api/staff/treks/{world.other_trek_id}/participants').status_code == 404
    assert staff.get(f'/api/staff/treks/{world.pending_trek_id}/participants').status_code == 404


def test_staff_participants(login_as, world):
    call(login_as('tia'), 'POST', '/api/bookings', {'trek_id': world.open_id})
    rows = login_as('staff').get(f'/api/staff/treks/{world.open_id}/participants').get_json()
    assert len(rows) == 1
    assert rows[0]['trekker']['name'] == 'Tia Trekker' and rows[0]['status'] == 'Booked'


# ---- trekker --------------------------------------------------------------

def test_trekker_books_and_pays(login_as, query, world):
    resp = call(login_as('tia'), 'POST', '/api/bookings', {'trek_id': world.open_id})
    data = resp.get_json()
    assert resp.status_code == 201
    assert data['status'] == 'Booked' and data['payment'] == {'amount': 1000, 'status': 'Paid'}
    assert query(lambda: db.session.get(Trek, world.open_id).available_slots) == 1


def test_booking_rules_return_409(login_as, world):
    tia = login_as('tia')
    call(tia, 'POST', '/api/bookings', {'trek_id': world.open_id})
    assert call(tia, 'POST', '/api/bookings', {'trek_id': world.open_id}).status_code == 409   # duplicate
    assert call(tia, 'POST', '/api/bookings', {'trek_id': world.full_id}).status_code == 409   # full
    assert call(tia, 'POST', '/api/bookings', {'trek_id': world.closed_id}).status_code == 409  # not open
    assert call(tia, 'POST', '/api/bookings', {'trek_id': world.pending_trek_id}).status_code == 409


def test_booking_input_validation(login_as):
    tia = login_as('tia')
    assert call(tia, 'POST', '/api/bookings', {}).status_code == 400
    assert call(tia, 'POST', '/api/bookings', {'trek_id': '1'}).status_code == 400
    assert call(tia, 'POST', '/api/bookings', {'trek_id': True}).status_code == 400
    assert call(tia, 'POST', '/api/bookings', {'trek_id': 99999}).status_code == 404


def test_slots_run_out_exactly_at_capacity(login_as, query, world):
    # the open trek has 2 slots: tia and tom fill it
    assert call(login_as('tia'), 'POST', '/api/bookings', {'trek_id': world.open_id}).status_code == 201
    assert call(login_as('tom'), 'POST', '/api/bookings', {'trek_id': world.open_id}).status_code == 201
    assert query(lambda: db.session.get(Trek, world.open_id).available_slots) == 0
    resp = call(login_as('tia'), 'POST', '/api/bookings', {'trek_id': world.open_id})
    assert resp.status_code == 409 and 'No slots' in resp.get_json()['error']


def test_trekker_cancels_and_is_refunded(login_as, query, world):
    tia = login_as('tia')
    booking_id = call(tia, 'POST', '/api/bookings', {'trek_id': world.open_id}).get_json()['id']
    resp = call(tia, 'PATCH', f'/api/bookings/{booking_id}/cancel')
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'Cancelled' and resp.get_json()['payment']['status'] == 'Refunded'
    assert query(lambda: db.session.get(Trek, world.open_id).available_slots) == 2
    assert call(tia, 'PATCH', f'/api/bookings/{booking_id}/cancel').status_code == 409  # already cancelled


def test_trekker_cannot_cancel_someone_elses_booking(login_as, world):
    booking_id = call(login_as('tia'), 'POST', '/api/bookings', {'trek_id': world.open_id}).get_json()['id']
    assert call(login_as('tom'), 'PATCH', f'/api/bookings/{booking_id}/cancel').status_code == 404


def test_trekker_only_sees_their_own_bookings(login_as, world):
    call(login_as('tia'), 'POST', '/api/bookings', {'trek_id': world.open_id})
    call(login_as('tom'), 'POST', '/api/bookings', {'trek_id': world.other_trek_id})
    mine = login_as('tia').get('/api/bookings').get_json()
    assert [b['trek_name'] for b in mine] == ['Open Trek']
