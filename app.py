# Run seed_db.py first to create the database.
# Admin login: admin@trek.com / admin123  (see README.md for all demo accounts)

import os
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, StaffProfile, Trek, Booking, Payment, AuditLog
from services import (
    RuleError, TREK_STATUSES, STAFF_STATUSES,
    create_booking, cancel_booking, add_trek, apply_trek_fields,
    set_total_slots, set_trek_status, assign_staff, delete_trek,
    set_account_status,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('TREK_DB_PATH') or os.path.join(BASE_DIR, 'trekking.db')

app = Flask(__name__)
app.config['SECRET_KEY'] = 'trekking-management-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DB_PATH
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to continue.'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def role_required(role):
    # checks role AND account status, not just role
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role != role:
                flash('You are not authorized to view that page.', 'danger')
                return redirect(url_for('dashboard_redirect'))
            if current_user.status == 'pending':
                flash('Your account is awaiting admin approval.', 'warning')
                return redirect(url_for('pending'))
            if current_user.status == 'blacklisted':
                flash('Your account has been blacklisted by the admin.', 'danger')
                logout_user()
                return redirect(url_for('login'))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard_redirect'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        phone = request.form.get('phone', '').strip()
        role = request.form['role']  # staff | trekker

        if role not in ('staff', 'trekker'):
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'danger')
            return redirect(url_for('register'))

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            phone=phone,
            # staff need admin approval before they can use the dashboard
            status='pending' if role == 'staff' else 'active',
        )
        db.session.add(user)
        db.session.commit()

        if role == 'staff':
            flash('Registered! Your staff account needs admin approval before you can log in.', 'info')
        else:
            flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash('Invalid email or password.', 'danger')
            return redirect(url_for('login'))

        if user.status == 'blacklisted':
            flash('This account has been blacklisted by the admin.', 'danger')
            return redirect(url_for('login'))

        login_user(user)

        if user.status == 'pending':
            return redirect(url_for('pending'))
        return redirect(url_for('dashboard_redirect'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


@app.route('/pending')
@login_required
def pending():
    return render_template('pending.html')


@app.route('/dashboard')
@login_required
def dashboard_redirect():
    if current_user.status == 'pending':
        return redirect(url_for('pending'))
    if current_user.status == 'blacklisted':
        logout_user()
        return redirect(url_for('login'))
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    if current_user.role == 'staff':
        return redirect(url_for('staff_dashboard'))
    return redirect(url_for('user_dashboard'))


@app.route('/admin/dashboard')
@role_required('admin')
def admin_dashboard():
    stats = {
        'trek_count': Trek.query.count(),
        'user_count': User.query.filter_by(role='trekker').count(),
        'staff_count': User.query.filter_by(role='staff').count(),
        'booking_count': Booking.query.count(),
        'pending_staff': User.query.filter_by(role='staff', status='pending').count(),
    }
    recent_bookings = Booking.query.order_by(Booking.booking_date.desc()).limit(5).all()

    q = request.args.get('q', '').strip()
    search_treks, search_staff, search_users = [], [], []
    if q:
        like = f'%{q}%'
        as_id = int(q) if q.isdigit() else -1
        search_treks = Trek.query.filter(
            db.or_(Trek.name.ilike(like), Trek.location.ilike(like), Trek.id == as_id)
        ).all()
        search_staff = User.query.filter(
            User.role == 'staff',
            db.or_(User.name.ilike(like), User.email.ilike(like), User.id == as_id)
        ).all()
        search_users = User.query.filter(
            User.role == 'trekker',
            db.or_(User.name.ilike(like), User.email.ilike(like), User.id == as_id)
        ).all()

    return render_template(
        'admin/dashboard.html', stats=stats, recent_bookings=recent_bookings,
        q=q, search_treks=search_treks, search_staff=search_staff, search_users=search_users,
    )


@app.route('/admin/treks')
@role_required('admin')
def admin_treks():
    treks = Trek.query.order_by(Trek.created_at.desc()).all()
    return render_template('admin/treks.html', treks=treks)


@app.route('/admin/treks/add', methods=['GET', 'POST'])
@role_required('admin')
def admin_add_trek():
    if request.method == 'POST':
        trek = Trek(
            name=request.form['name'].strip(),
            location=request.form['location'].strip(),
            difficulty=request.form['difficulty'],
            duration=int(request.form['duration']),
            price=int(request.form.get('price') or 0),
            total_slots=int(request.form['total_slots']),
            available_slots=int(request.form['total_slots']),
            status='Pending',
            start_date=datetime.strptime(request.form['start_date'], '%Y-%m-%d').date(),
            end_date=datetime.strptime(request.form['end_date'], '%Y-%m-%d').date(),
            description=request.form.get('description', '').strip(),
        )
        add_trek(trek)
        db.session.commit()
        flash('Trek created.', 'success')
        return redirect(url_for('admin_treks'))
    return render_template('admin/trek_form.html', trek=None)


@app.route('/admin/treks/edit/<int:trek_id>', methods=['GET', 'POST'])
@role_required('admin')
def admin_edit_trek(trek_id):
    trek = Trek.query.get_or_404(trek_id)
    if request.method == 'POST':
        status = request.form['status']
        if status not in TREK_STATUSES:
            flash('Invalid trek status.', 'danger')
            return redirect(url_for('admin_edit_trek', trek_id=trek.id))

        values = {
            'name': request.form['name'].strip(),
            'location': request.form['location'].strip(),
            'difficulty': request.form['difficulty'],
            'duration': int(request.form['duration']),
            'start_date': datetime.strptime(request.form['start_date'], '%Y-%m-%d').date(),
            'end_date': datetime.strptime(request.form['end_date'], '%Y-%m-%d').date(),
            'description': request.form.get('description', '').strip(),
        }
        if request.form.get('price'):
            values['price'] = int(request.form['price'])

        apply_trek_fields(trek, values)
        set_total_slots(trek, int(request.form['total_slots']))
        set_trek_status(trek, status)
        db.session.commit()
        flash('Trek updated.', 'success')
        return redirect(url_for('admin_treks'))
    return render_template('admin/trek_form.html', trek=trek)


@app.route('/admin/treks/delete/<int:trek_id>', methods=['POST'])
@role_required('admin')
def admin_delete_trek(trek_id):
    trek = Trek.query.get_or_404(trek_id)
    delete_trek(trek)
    db.session.commit()
    flash('Trek deleted.', 'info')
    return redirect(url_for('admin_treks'))


@app.route('/admin/treks/assign/<int:trek_id>', methods=['GET', 'POST'])
@role_required('admin')
def admin_assign_staff(trek_id):
    trek = Trek.query.get_or_404(trek_id)
    approved_staff = User.query.filter_by(role='staff', status='active').all()
    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        try:
            assign_staff(trek, int(staff_id) if staff_id else None)
        except RuleError as e:
            flash(e.message, e.level)
            return redirect(url_for('admin_assign_staff', trek_id=trek.id))
        db.session.commit()
        flash('Staff assignment updated.', 'success')
        return redirect(url_for('admin_treks'))
    return render_template('admin/assign_staff.html', trek=trek, staff_list=approved_staff)


@app.route('/admin/staff')
@role_required('admin')
def admin_staff():
    staff_list = User.query.filter_by(role='staff').order_by(User.created_at.desc()).all()
    return render_template('admin/staff.html', staff_list=staff_list)


@app.route('/admin/staff/approve/<int:user_id>', methods=['POST'])
@role_required('admin')
def admin_approve_staff(user_id):
    staff = User.query.filter_by(id=user_id, role='staff').first_or_404()
    set_account_status(staff, 'active')
    db.session.commit()
    flash(f'{staff.name} approved.', 'success')
    return redirect(url_for('admin_staff'))


@app.route('/admin/staff/blacklist/<int:user_id>', methods=['POST'])
@role_required('admin')
def admin_blacklist_staff(user_id):
    staff = User.query.filter_by(id=user_id, role='staff').first_or_404()
    set_account_status(staff, 'blacklisted')
    db.session.commit()
    flash(f'{staff.name} blacklisted.', 'warning')
    return redirect(url_for('admin_staff'))


@app.route('/admin/staff/reinstate/<int:user_id>', methods=['POST'])
@role_required('admin')
def admin_reinstate_staff(user_id):
    staff = User.query.filter_by(id=user_id, role='staff').first_or_404()
    set_account_status(staff, 'active')
    db.session.commit()
    flash(f'{staff.name} reinstated.', 'success')
    return redirect(url_for('admin_staff'))


@app.route('/admin/users')
@role_required('admin')
def admin_users():
    users = User.query.filter_by(role='trekker').order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)


@app.route('/admin/users/blacklist/<int:user_id>', methods=['POST'])
@role_required('admin')
def admin_blacklist_user(user_id):
    user = User.query.filter_by(id=user_id, role='trekker').first_or_404()
    set_account_status(user, 'blacklisted')
    db.session.commit()
    flash(f'{user.name} blacklisted.', 'warning')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/reinstate/<int:user_id>', methods=['POST'])
@role_required('admin')
def admin_reinstate_user(user_id):
    user = User.query.filter_by(id=user_id, role='trekker').first_or_404()
    set_account_status(user, 'active')
    db.session.commit()
    flash(f'{user.name} reinstated.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/bookings')
@role_required('admin')
def admin_bookings():
    bookings = Booking.query.order_by(Booking.booking_date.desc()).all()
    return render_template('admin/bookings.html', bookings=bookings)


@app.route('/admin/audit')
@role_required('admin')
def admin_audit():
    entries = AuditLog.query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(200).all()
    return render_template('admin/audit.html', entries=entries)


@app.route('/staff/dashboard')
@role_required('staff')
def staff_dashboard():
    treks = Trek.query.filter_by(assigned_staff_id=current_user.id).order_by(Trek.start_date).all()
    participant_counts = {
        trek.id: Booking.query.filter_by(trek_id=trek.id, status='Booked').count()
        for trek in treks
    }
    return render_template('staff/dashboard.html', treks=treks, participant_counts=participant_counts)


@app.route('/staff/trek/<int:trek_id>/update', methods=['GET', 'POST'])
@role_required('staff')
def staff_update_trek(trek_id):
    trek = Trek.query.filter_by(id=trek_id, assigned_staff_id=current_user.id).first_or_404()
    if request.method == 'POST':
        status = request.form['status']
        if status not in STAFF_STATUSES:
            flash('Invalid trek status.', 'danger')
            return redirect(url_for('staff_update_trek', trek_id=trek.id))
        set_total_slots(trek, int(request.form['total_slots']))
        set_trek_status(trek, status)
        db.session.commit()
        flash('Trek details updated.', 'success')
        return redirect(url_for('staff_dashboard'))
    return render_template('staff/update_trek.html', trek=trek)


@app.route('/staff/trek/<int:trek_id>/participants')
@role_required('staff')
def staff_trek_participants(trek_id):
    trek = Trek.query.filter_by(id=trek_id, assigned_staff_id=current_user.id).first_or_404()
    bookings = Booking.query.filter_by(trek_id=trek.id).order_by(Booking.booking_date.desc()).all()
    return render_template('staff/participants.html', trek=trek, bookings=bookings)


@app.route('/user/dashboard')
@role_required('trekker')
def user_dashboard():
    open_treks = Trek.query.filter_by(status='Open').order_by(Trek.start_date).limit(6).all()
    my_bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).all()
    return render_template('user/dashboard.html', open_treks=open_treks, my_bookings=my_bookings)


@app.route('/user/treks')
@role_required('trekker')
def user_treks():
    query = Trek.query.filter_by(status='Open')
    difficulty = request.args.get('difficulty', '')
    location = request.args.get('location', '').strip()
    q = request.args.get('q', '').strip()

    if difficulty:
        query = query.filter_by(difficulty=difficulty)
    if location:
        query = query.filter(Trek.location.ilike(f'%{location}%'))
    if q:
        query = query.filter(Trek.name.ilike(f'%{q}%'))

    treks = query.order_by(Trek.start_date).all()
    booked_trek_ids = {
        b.trek_id for b in Booking.query.filter_by(user_id=current_user.id, status='Booked').all()
    }
    return render_template(
        'user/treks.html', treks=treks, difficulty=difficulty, location=location, q=q,
        booked_trek_ids=booked_trek_ids
    )


@app.route('/user/book/<int:trek_id>', methods=['POST'])
@role_required('trekker')
def user_book_trek(trek_id):
    trek = Trek.query.get_or_404(trek_id)
    try:
        create_booking(current_user, trek)
    except RuleError as e:
        flash(e.message, e.level)
        return redirect(url_for('user_treks'))
    flash(f'Trek "{trek.name}" booked successfully!', 'success')
    return redirect(url_for('user_bookings'))


@app.route('/user/bookings')
@role_required('trekker')
def user_bookings():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).all()
    return render_template('user/bookings.html', bookings=bookings)


@app.route('/user/bookings/cancel/<int:booking_id>', methods=['POST'])
@role_required('trekker')
def user_cancel_booking(booking_id):
    booking = Booking.query.filter_by(id=booking_id, user_id=current_user.id).first_or_404()
    if booking.status == 'Booked':
        cancel_booking(booking)
        flash('Booking cancelled.', 'info')
    return redirect(url_for('user_bookings'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        if current_user.role == 'staff':
            try:
                years = int(request.form.get('experience_years') or 0)
            except ValueError:
                years = -1
            if years < 0:
                flash('Experience must be a whole number of years.', 'danger')
                return redirect(url_for('profile'))
            sp = current_user.staff_profile or StaffProfile(user_id=current_user.id)
            sp.experience_years = years
            sp.certifications = request.form.get('certifications', '').strip()
            sp.emergency_contact = request.form.get('emergency_contact', '').strip()
            sp.bio = request.form.get('bio', '').strip()
            db.session.add(sp)

        current_user.name = request.form['name'].strip()
        current_user.phone = request.form.get('phone', '').strip()
        new_password = request.form.get('password', '').strip()
        if new_password:
            current_user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html')


@app.route('/profile/delete', methods=['GET'])
@login_required
def profile_delete_confirm():
    if current_user.role == 'admin':
        flash('The admin account cannot be deleted.', 'danger')
        return redirect(url_for('profile'))
    return render_template('profile_delete_confirm.html')


@app.route('/profile/delete', methods=['POST'])
@login_required
def profile_delete():
    if current_user.role == 'admin':
        flash('The admin account cannot be deleted.', 'danger')
        return redirect(url_for('profile'))

    user = current_user._get_current_object()

    if user.role == 'trekker':
        for b in Booking.query.filter_by(user_id=user.id):
            if b.status == 'Booked':
                b.trek.available_slots += 1
            if b.payment:
                db.session.delete(b.payment)
            db.session.delete(b)
    elif user.role == 'staff':
        Trek.query.filter_by(assigned_staff_id=user.id).update({'assigned_staff_id': None})
        if user.staff_profile:
            db.session.delete(user.staff_profile)

    # keep the audit entries, just detach them from the deleted account
    AuditLog.query.filter_by(actor_id=user.id).update({'actor_id': None})
    db.session.delete(user)
    db.session.commit()
    logout_user()
    flash('Your account has been permanently deleted.', 'info')
    return redirect(url_for('login'))


def trek_to_dict(t):
    return {
        'id': t.id,
        'name': t.name,
        'location': t.location,
        'difficulty': t.difficulty,
        'duration': t.duration,
        'available_slots': t.available_slots,
        'total_slots': t.total_slots,
        'status': t.status,
        'start_date': t.start_date.isoformat(),
        'end_date': t.end_date.isoformat(),
        'assigned_staff': t.staff.name if t.staff else None,
    }


@app.route('/api/treks', methods=['GET'])
def api_treks():
    treks = Trek.query.filter_by(status='Open').order_by(Trek.start_date).all()
    return jsonify([trek_to_dict(t) for t in treks])


@app.route('/api/treks/<int:trek_id>', methods=['GET'])
def api_trek_detail(trek_id):
    trek = Trek.query.get_or_404(trek_id)
    data = trek_to_dict(trek)
    data['description'] = trek.description
    return jsonify(data)


@app.route('/api/bookings', methods=['GET'])
@login_required
def api_bookings():
    if current_user.role != 'trekker':
        return jsonify({'error': 'Only trekker accounts have bookings.'}), 403
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).all()
    return jsonify([{
        'id': b.id,
        'trek_id': b.trek_id,
        'trek_name': b.trek.name,
        'booking_date': b.booking_date.isoformat(),
        'status': b.status,
    } for b in bookings])


if __name__ == '__main__':
    app.run(debug=True)
