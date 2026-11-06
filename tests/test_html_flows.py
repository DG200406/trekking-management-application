import pytest

from models import db, User, Trek, Booking, Payment, AuditLog


def text(resp):
    return resp.get_data(as_text=True)


def trek_form(**overrides):
    form = {
        'name': 'Open Trek', 'location': 'Hills', 'difficulty': 'Easy', 'duration': '2', 'price': '1000',
        'total_slots': '2', 'status': 'Open', 'start_date': '2031-01-01', 'end_date': '2031-01-03',
        'description': 'A test trek.',
    }
    form.update(overrides)
    return form


def slots(query, trek_id):
    return query(lambda: db.session.get(Trek, trek_id).available_slots)


# ---- registration and login ----------------------------------------------

def test_admin_cannot_self_register(anon, query, world):
    resp = anon.post('/register', data={'name': 'Evil', 'email': 'evil@t.com', 'password': 'x1234',
                                        'role': 'admin'}, follow_redirects=True)
    assert 'Invalid role' in text(resp)
    assert query(lambda: User.query.filter_by(email='evil@t.com').first()) is None


def test_staff_registers_as_pending_and_is_held_back(anon, query, world):
    anon.post('/register', data={'name': 'New Staff', 'email': 'ns@t.com', 'password': 'x1234', 'role': 'staff'})
    assert query(lambda: User.query.filter_by(email='ns@t.com').first().status) == 'pending'
    resp = anon.post('/login', data={'email': 'ns@t.com', 'password': 'x1234'})
    assert resp.headers['Location'].endswith('/pending')
    assert anon.get('/staff/dashboard').headers['Location'].endswith('/pending')


def test_trekker_registers_active(anon, query, world):
    anon.post('/register', data={'name': 'New T', 'email': 'nt@t.com', 'password': 'x1234', 'role': 'trekker'})
    assert query(lambda: User.query.filter_by(email='nt@t.com').first().status) == 'active'


def test_duplicate_email_rejected(anon, world):
    resp = anon.post('/register', data={'name': 'Dup', 'email': 'tia@t.com', 'password': 'x1234',
                                        'role': 'trekker'}, follow_redirects=True)
    assert 'already exists' in text(resp)


def test_bad_password_and_blacklisted_login(anon, world):
    resp = anon.post('/login', data={'email': 'tia@t.com', 'password': 'wrong'}, follow_redirects=True)
    assert 'Invalid email or password' in text(resp)
    resp = anon.post('/login', data={'email': 'bob@t.com', 'password': 'pass1234'}, follow_redirects=True)
    assert 'blacklisted' in text(resp)


@pytest.mark.parametrize('key,landing', [
    ('admin', '/admin/dashboard'), ('staff', '/staff/dashboard'), ('tia', '/user/dashboard'),
])
def test_each_role_lands_on_its_own_dashboard(login_as, key, landing):
    assert login_as(key).get('/dashboard').headers['Location'].endswith(landing)


# ---- role guards ----------------------------------------------------------

def test_anonymous_is_sent_to_login(anon, world):
    for path in ('/admin/dashboard', '/staff/dashboard', '/user/dashboard', '/profile'):
        assert '/login' in anon.get(path).headers['Location']


def test_wrong_role_is_bounced_to_own_dashboard(login_as, world):
    assert login_as('tia').get('/admin/dashboard').headers['Location'].endswith('/dashboard')
    assert login_as('staff').get('/admin/treks').headers['Location'].endswith('/dashboard')
    assert login_as('admin').get('/staff/dashboard').headers['Location'].endswith('/dashboard')


# ---- booking, slots, payments --------------------------------------------

def test_booking_takes_a_slot_and_a_payment(login_as, query, world):
    resp = login_as('tia').post(f'/user/book/{world.open_id}', follow_redirects=True)
    assert 'booked successfully' in text(resp)
    assert slots(query, world.open_id) == 1
    payment = query(lambda: Payment.query.one())
    assert (payment.amount, payment.status) == (1000, 'Paid')


def test_duplicate_full_and_closed_bookings_are_blocked(login_as, query, world):
    tia = login_as('tia')
    tia.post(f'/user/book/{world.open_id}')
    assert 'already booked' in text(tia.post(f'/user/book/{world.open_id}', follow_redirects=True))
    assert 'No slots available' in text(tia.post(f'/user/book/{world.full_id}', follow_redirects=True))
    assert 'not open' in text(tia.post(f'/user/book/{world.closed_id}', follow_redirects=True))
    assert query(lambda: Booking.query.count()) == 1


def test_cancelling_gives_the_slot_back_and_refunds(login_as, query, world):
    tia = login_as('tia')
    tia.post(f'/user/book/{world.open_id}')
    booking_id = query(lambda: Booking.query.one().id)
    tia.post(f'/user/bookings/cancel/{booking_id}')
    assert slots(query, world.open_id) == 2
    assert query(lambda: Payment.query.one().status) == 'Refunded'
    assert 'Refunded' in text(tia.get('/user/bookings'))


def test_resizing_a_trek_keeps_the_booked_seats(login_as, query, world):
    login_as('tia').post(f'/user/book/{world.open_id}')
    login_as('admin').post(f'/admin/treks/edit/{world.open_id}', data=trek_form(total_slots='10'))
    assert slots(query, world.open_id) == 9
    login_as('admin').post(f'/admin/treks/edit/{world.open_id}', data=trek_form(total_slots='0'))
    assert slots(query, world.open_id) == 0  # never negative


def test_completing_a_trek_completes_its_bookings_from_admin_and_staff(login_as, query, world):
    login_as('tia').post(f'/user/book/{world.open_id}')
    login_as('admin').post(f'/admin/treks/edit/{world.open_id}', data=trek_form(status='Completed'))
    assert query(lambda: Booking.query.one().status) == 'Completed'

    login_as('tom').post(f'/user/book/{world.other_trek_id}')
    login_as('other_staff').post(f'/staff/trek/{world.other_trek_id}/update',
                                 data={'total_slots': '5', 'status': 'Completed'})
    assert query(lambda: {b.status for b in Booking.query.filter_by(trek_id=world.other_trek_id)}) == {'Completed'}


def test_invalid_trek_status_is_refused(login_as, world):
    assert 'Invalid trek status' in text(login_as('admin').post(
        f'/admin/treks/edit/{world.open_id}', data=trek_form(status='Nope'), follow_redirects=True))
    assert 'Invalid trek status' in text(login_as('staff').post(
        f'/staff/trek/{world.open_id}/update', data={'total_slots': '2', 'status': 'Pending'}, follow_redirects=True))


def test_staff_only_reach_their_own_treks(login_as, world):
    staff = login_as('staff')
    assert staff.get(f'/staff/trek/{world.open_id}/update').status_code == 200
    assert staff.get(f'/staff/trek/{world.other_trek_id}/update').status_code == 404
    assert staff.get(f'/staff/trek/{world.other_trek_id}/participants').status_code == 404
    page = text(staff.get('/staff/dashboard'))
    assert 'Open Trek' in page and 'Other Trek' not in page


# ---- admin management -----------------------------------------------------

def test_staff_approval_flow(login_as, query, world):
    admin = login_as('admin')
    admin.post(f'/admin/staff/approve/{world.pending_staff_id}')
    assert query(lambda: db.session.get(User, world.pending_staff_id).status) == 'active'
    admin.post(f'/admin/staff/blacklist/{world.pending_staff_id}')
    assert query(lambda: db.session.get(User, world.pending_staff_id).status) == 'blacklisted'
    admin.post(f'/admin/staff/reinstate/{world.pending_staff_id}')
    assert query(lambda: db.session.get(User, world.pending_staff_id).status) == 'active'


def test_trekker_blacklist_and_reinstate(login_as, query, world):
    admin = login_as('admin')
    admin.post(f'/admin/users/blacklist/{world.tia_id}')
    assert query(lambda: db.session.get(User, world.tia_id).status) == 'blacklisted'
    admin.post(f'/admin/users/reinstate/{world.tia_id}')
    assert query(lambda: db.session.get(User, world.tia_id).status) == 'active'


def test_admin_routes_cannot_target_the_admin_account(login_as, query, world):
    admin = login_as('admin')
    assert admin.post(f'/admin/staff/blacklist/{world.admin_id}').status_code == 404
    assert admin.post(f'/admin/users/blacklist/{world.admin_id}').status_code == 404
    assert query(lambda: db.session.get(User, world.admin_id).status) == 'active'


def test_assign_staff_only_accepts_active_staff(login_as, query, world):
    admin = login_as('admin')
    admin.post(f'/admin/treks/assign/{world.pending_trek_id}', data={'staff_id': str(world.staff_id)})
    trek = query(lambda: db.session.get(Trek, world.pending_trek_id))
    assert (trek.assigned_staff_id, trek.status) == (world.staff_id, 'Approved')
    resp = admin.post(f'/admin/treks/assign/{world.closed_id}', data={'staff_id': str(world.pending_staff_id)},
                      follow_redirects=True)
    assert 'approved staff member' in text(resp)


def test_admin_dashboard_search(login_as, world):
    admin = login_as('admin')
    page = text(admin.get('/admin/dashboard?q=Open'))
    assert 'Search Results' in page and 'Open Trek' in page
    assert 'Tia Trekker' in text(admin.get('/admin/dashboard?q=tia'))
    assert 'Pat Pending' in text(admin.get(f'/admin/dashboard?q={world.pending_staff_id}'))


# ---- profiles and account deletion ---------------------------------------

def test_staff_profile_round_trip(login_as, query, world):
    staff = login_as('staff')
    staff.post('/profile', data={'name': 'Sam Staff', 'phone': '1', 'experience_years': '7',
                                 'certifications': 'WFR', 'emergency_contact': '2', 'bio': 'hello'})
    profile = query(lambda: db.session.get(User, world.staff_id).staff_profile)
    assert (profile.experience_years, profile.certifications, profile.bio) == (7, 'WFR', 'hello')
    assert 'value="7"' in text(staff.get('/profile'))
    assert 'whole number' in text(staff.post('/profile', data={'name': 'Sam', 'experience_years': '-3'},
                                             follow_redirects=True))


def test_trekker_profile_edit_and_password_change(app, login_as, world):
    tia = login_as('tia')
    tia.post('/profile', data={'name': 'Tia New', 'phone': '123', 'password': 'newpass99'})
    fresh = app.test_client()
    resp = fresh.post('/login', data={'email': 'tia@t.com', 'password': 'newpass99'})
    assert '/login' not in resp.headers['Location']


def test_deleting_a_trekker_account_returns_their_slots(login_as, query, world):
    tia = login_as('tia')
    tia.post(f'/user/book/{world.open_id}')
    assert slots(query, world.open_id) == 1
    tia.post('/profile/delete')
    assert slots(query, world.open_id) == 2
    assert query(lambda: (User.query.filter_by(email='tia@t.com').first(), Booking.query.count(),
                          Payment.query.count())) == (None, 0, 0)


def test_deleting_a_staff_account_unassigns_treks_and_keeps_the_audit_trail(login_as, query, world):
    staff = login_as('staff')
    staff.post(f'/staff/trek/{world.open_id}/update', data={'total_slots': '2', 'status': 'Closed'})
    logged = query(lambda: AuditLog.query.count())
    assert logged >= 1
    staff.post('/profile/delete')
    assert query(lambda: db.session.get(Trek, world.open_id).assigned_staff_id) is None
    assert query(lambda: AuditLog.query.count()) == logged
    assert query(lambda: AuditLog.query.filter_by(actor_name='Sam Staff').first().actor_id) is None


def test_admin_account_cannot_be_deleted(login_as, query, world):
    admin = login_as('admin')
    assert 'cannot be deleted' in text(admin.post('/profile/delete', follow_redirects=True))
    assert query(lambda: db.session.get(User, world.admin_id)) is not None


def test_deleting_a_trek_removes_its_bookings_and_payments(login_as, query, world):
    login_as('tia').post(f'/user/book/{world.open_id}')
    login_as('admin').post(f'/admin/treks/delete/{world.open_id}')
    assert query(lambda: (Booking.query.count(), Payment.query.count())) == (0, 0)


# ---- every page renders ---------------------------------------------------

PUBLIC_PAGES = ['/', '/login', '/register']
PAGES = {
    'admin': ['/admin/dashboard', '/admin/treks', '/admin/treks/add', '/admin/staff', '/admin/users',
              '/admin/bookings', '/admin/audit', '/profile'],
    'staff': ['/staff/dashboard', '/profile'],
    'tia': ['/user/dashboard', '/user/treks', '/user/bookings', '/profile', '/profile/delete'],
}


@pytest.mark.parametrize('path', PUBLIC_PAGES)
def test_public_pages_render(anon, world, path):
    assert anon.get(path).status_code == 200


@pytest.mark.parametrize('role', list(PAGES))
def test_role_pages_render(login_as, world, role):
    client = login_as(role)
    for path in PAGES[role]:
        assert client.get(path).status_code == 200, f'{role} {path}'


def test_pages_that_need_an_id_render(login_as, world):
    admin = login_as('admin')
    assert admin.get(f'/admin/treks/edit/{world.open_id}').status_code == 200
    assert admin.get(f'/admin/treks/assign/{world.open_id}').status_code == 200
    staff = login_as('staff')
    assert staff.get(f'/staff/trek/{world.open_id}/update').status_code == 200
    assert staff.get(f'/staff/trek/{world.open_id}/participants').status_code == 200


def test_sidebar_shows_the_activity_log_to_admin_only(login_as, world):
    assert 'Activity Log' in text(login_as('admin').get('/admin/dashboard'))
    assert 'Activity Log' not in text(login_as('staff').get('/staff/dashboard'))
