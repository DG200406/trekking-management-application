from datetime import date
from functools import wraps

from flask import Blueprint, jsonify, request
from flask_login import current_user, logout_user

from models import db, User, Trek, Booking
from services import (
    RuleError, TREK_STATUSES, STAFF_STATUSES,
    create_booking, cancel_booking, add_trek, apply_trek_fields,
    set_total_slots, set_trek_status, assign_staff, delete_trek,
    set_account_status,
)

api_bp = Blueprint('api', __name__, url_prefix='/api')

DIFFICULTIES = ('Easy', 'Moderate', 'Hard')
CREATE_FIELDS = (
    'name', 'location', 'difficulty', 'duration', 'price',
    'total_slots', 'start_date', 'end_date', 'description',
)
CREATE_REQUIRED = (
    'name', 'location', 'difficulty', 'duration',
    'total_slots', 'start_date', 'end_date',
)
ADMIN_PATCH_FIELDS = CREATE_FIELDS + ('status', 'assigned_staff_id')
STAFF_PATCH_FIELDS = ('total_slots', 'status')


def api_role_required(role):
    # same rules as role_required, but answers with JSON instead of redirecting
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify(error='Authentication required.'), 401
            if current_user.status == 'blacklisted':
                logout_user()
                return jsonify(error='This account has been blacklisted.'), 403
            if current_user.status == 'pending':
                return jsonify(error='This account is awaiting admin approval.'), 403
            if current_user.role != role:
                return jsonify(error=f'This endpoint is for {role} accounts only.'), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


@api_bp.errorhandler(RuleError)
def handle_rule_error(e):
    return jsonify(error=e.message), e.status


@api_bp.errorhandler(404)
def handle_not_found(e):
    return jsonify(error='Not found.'), 404


def trek_to_dict(t):
    return {
        'id': t.id,
        'name': t.name,
        'location': t.location,
        'difficulty': t.difficulty,
        'duration': t.duration,
        'price': t.price,
        'available_slots': t.available_slots,
        'total_slots': t.total_slots,
        'status': t.status,
        'start_date': t.start_date.isoformat(),
        'end_date': t.end_date.isoformat(),
        'assigned_staff': t.staff.name if t.staff else None,
    }


def booking_to_dict(b):
    payment = None
    if b.payment:
        payment = {'amount': b.payment.amount, 'status': b.payment.status}
    return {
        'id': b.id,
        'trek_id': b.trek_id,
        'trek_name': b.trek.name,
        'booking_date': b.booking_date.isoformat(),
        'status': b.status,
        'payment': payment,
    }


def user_to_dict(u):
    return {
        'id': u.id,
        'name': u.name,
        'email': u.email,
        'phone': u.phone,
        'role': u.role,
        'status': u.status,
    }


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise RuleError('Request body must be a JSON object.', status=400)
    return data


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def parse_trek_fields(data, allowed):
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise RuleError('Unknown fields: ' + ', '.join(unknown), status=400)

    out = {}
    for f in ('name', 'location'):
        if f in data:
            if not isinstance(data[f], str) or not data[f].strip():
                raise RuleError(f'{f} must be a non-empty string.', status=400)
            out[f] = data[f].strip()
    if 'difficulty' in data:
        if data['difficulty'] not in DIFFICULTIES:
            raise RuleError('difficulty must be Easy, Moderate or Hard.', status=400)
        out['difficulty'] = data['difficulty']
    for f, minimum in (('duration', 1), ('total_slots', 1), ('price', 0)):
        if f in data:
            if not is_int(data[f]) or data[f] < minimum:
                raise RuleError(f'{f} must be an integer >= {minimum}.', status=400)
            out[f] = data[f]
    for f in ('start_date', 'end_date'):
        if f in data:
            try:
                out[f] = date.fromisoformat(data[f])
            except (TypeError, ValueError):
                raise RuleError(f'{f} must be a date like 2030-01-31.', status=400)
    if 'description' in data:
        if data['description'] is not None and not isinstance(data['description'], str):
            raise RuleError('description must be a string.', status=400)
        out['description'] = (data['description'] or '').strip()
    if 'status' in data:
        if data['status'] not in TREK_STATUSES:
            raise RuleError('status must be one of: ' + ', '.join(TREK_STATUSES) + '.', status=400)
        out['status'] = data['status']
    if 'assigned_staff_id' in data:
        value = data['assigned_staff_id']
        if value is not None and not is_int(value):
            raise RuleError('assigned_staff_id must be an integer or null.', status=400)
        out['assigned_staff_id'] = value
    return out


# public, read-only

@api_bp.get('/treks')
def list_open_treks():
    treks = Trek.query.filter_by(status='Open').order_by(Trek.start_date).all()
    return jsonify([trek_to_dict(t) for t in treks])


@api_bp.get('/treks/<int:trek_id>')
def get_open_trek(trek_id):
    trek = Trek.query.filter_by(id=trek_id, status='Open').first_or_404()
    data = trek_to_dict(trek)
    data['description'] = trek.description
    return jsonify(data)


# admin

@api_bp.get('/admin/stats')
@api_role_required('admin')
def admin_stats():
    return jsonify(
        treks=Trek.query.count(),
        trekkers=User.query.filter_by(role='trekker').count(),
        staff=User.query.filter_by(role='staff').count(),
        bookings=Booking.query.count(),
        pending_staff=User.query.filter_by(role='staff', status='pending').count(),
    )


@api_bp.get('/admin/users')
@api_role_required('admin')
def admin_list_users():
    query = User.query.filter(User.role.in_(('staff', 'trekker')))
    role = request.args.get('role')
    status = request.args.get('status')
    if role:
        if role not in ('staff', 'trekker'):
            raise RuleError('role must be "staff" or "trekker".', status=400)
        query = query.filter_by(role=role)
    if status:
        if status not in ('active', 'pending', 'blacklisted'):
            raise RuleError('status must be active, pending or blacklisted.', status=400)
        query = query.filter_by(status=status)
    return jsonify([user_to_dict(u) for u in query.order_by(User.name).all()])


@api_bp.post('/admin/treks')
@api_role_required('admin')
def admin_create_trek():
    data = json_body()
    missing = [f for f in CREATE_REQUIRED if f not in data]
    if missing:
        raise RuleError('Missing fields: ' + ', '.join(missing), status=400)
    fields = parse_trek_fields(data, CREATE_FIELDS)
    if fields['end_date'] < fields['start_date']:
        raise RuleError('end_date cannot be before start_date.', status=400)

    trek = Trek(
        name=fields['name'],
        location=fields['location'],
        difficulty=fields['difficulty'],
        duration=fields['duration'],
        price=fields.get('price', 0),
        total_slots=fields['total_slots'],
        available_slots=fields['total_slots'],
        status='Pending',
        start_date=fields['start_date'],
        end_date=fields['end_date'],
        description=fields.get('description', ''),
    )
    add_trek(trek)
    db.session.commit()
    return jsonify(trek_to_dict(trek)), 201


@api_bp.patch('/admin/treks/<int:trek_id>')
@api_role_required('admin')
def admin_update_trek(trek_id):
    trek = db.get_or_404(Trek, trek_id)
    fields = parse_trek_fields(json_body(), ADMIN_PATCH_FIELDS)
    if not fields:
        raise RuleError('Nothing to update.', status=400)
    if fields.get('end_date', trek.end_date) < fields.get('start_date', trek.start_date):
        raise RuleError('end_date cannot be before start_date.', status=400)

    new_total = fields.pop('total_slots', None)
    status = fields.pop('status', None)
    assigning = 'assigned_staff_id' in fields
    staff_id = fields.pop('assigned_staff_id', None)

    apply_trek_fields(trek, fields)
    if new_total is not None:
        set_total_slots(trek, new_total)
    if assigning:
        assign_staff(trek, staff_id)
    if status is not None:
        set_trek_status(trek, status)
    db.session.commit()
    return jsonify(trek_to_dict(trek))


@api_bp.delete('/admin/treks/<int:trek_id>')
@api_role_required('admin')
def admin_delete_trek(trek_id):
    trek = db.get_or_404(Trek, trek_id)
    delete_trek(trek)
    db.session.commit()
    return '', 204


@api_bp.patch('/admin/users/<int:user_id>/status')
@api_role_required('admin')
def admin_set_user_status(user_id):
    user = User.query.filter(User.id == user_id, User.role.in_(('staff', 'trekker'))).first_or_404()
    data = json_body()
    if set(data) != {'status'}:
        raise RuleError('Body must be {"status": "active"} or {"status": "blacklisted"}.', status=400)
    set_account_status(user, data['status'])
    db.session.commit()
    return jsonify(user_to_dict(user))


# staff

@api_bp.get('/staff/treks')
@api_role_required('staff')
def staff_list_treks():
    treks = Trek.query.filter_by(assigned_staff_id=current_user.id).order_by(Trek.start_date).all()
    out = []
    for t in treks:
        item = trek_to_dict(t)
        item['participant_count'] = Booking.query.filter_by(trek_id=t.id, status='Booked').count()
        out.append(item)
    return jsonify(out)


@api_bp.patch('/staff/treks/<int:trek_id>')
@api_role_required('staff')
def staff_update_trek(trek_id):
    trek = Trek.query.filter_by(id=trek_id, assigned_staff_id=current_user.id).first_or_404()
    fields = parse_trek_fields(json_body(), STAFF_PATCH_FIELDS)
    if not fields:
        raise RuleError('Nothing to update.', status=400)
    if 'status' in fields and fields['status'] not in STAFF_STATUSES:
        raise RuleError('Staff can set status to: ' + ', '.join(STAFF_STATUSES) + '.', status=400)

    if 'total_slots' in fields:
        set_total_slots(trek, fields['total_slots'])
    if 'status' in fields:
        set_trek_status(trek, fields['status'])
    db.session.commit()
    return jsonify(trek_to_dict(trek))


@api_bp.get('/staff/treks/<int:trek_id>/participants')
@api_role_required('staff')
def staff_trek_participants(trek_id):
    trek = Trek.query.filter_by(id=trek_id, assigned_staff_id=current_user.id).first_or_404()
    bookings = Booking.query.filter_by(trek_id=trek.id).order_by(Booking.booking_date.desc()).all()
    return jsonify([{
        'booking_id': b.id,
        'status': b.status,
        'booking_date': b.booking_date.isoformat(),
        'trekker': {'id': b.trekker.id, 'name': b.trekker.name, 'phone': b.trekker.phone},
    } for b in bookings])


# trekker

@api_bp.get('/bookings')
@api_role_required('trekker')
def my_bookings():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).all()
    return jsonify([booking_to_dict(b) for b in bookings])


@api_bp.post('/bookings')
@api_role_required('trekker')
def create_my_booking():
    trek_id = json_body().get('trek_id')
    if not is_int(trek_id):
        raise RuleError('trek_id must be an integer.', status=400)
    trek = db.get_or_404(Trek, trek_id)
    booking = create_booking(current_user, trek)
    return jsonify(booking_to_dict(booking)), 201


@api_bp.patch('/bookings/<int:booking_id>/cancel')
@api_role_required('trekker')
def cancel_my_booking(booking_id):
    booking = Booking.query.filter_by(id=booking_id, user_id=current_user.id).first_or_404()
    cancel_booking(booking)
    return jsonify(booking_to_dict(booking))
