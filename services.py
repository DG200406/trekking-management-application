from datetime import datetime

from flask_login import current_user

from models import db, User, Booking, Payment, AuditLog

TREK_STATUSES = ('Pending', 'Approved', 'Open', 'Closed', 'Completed')
STAFF_STATUSES = ('Approved', 'Open', 'Closed', 'Completed')


class RuleError(Exception):
    # level is the flash category for HTML pages, status is the HTTP code for the API
    def __init__(self, message, level='danger', status=409):
        super().__init__(message)
        self.message = message
        self.level = level
        self.status = status


def log_action(action, target_type=None, target_id=None, detail=None):
    db.session.add(AuditLog(
        actor_id=current_user.id,
        actor_name=current_user.name,
        actor_role=current_user.role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    ))


def create_booking(user, trek):
    if trek.status != 'Open':
        raise RuleError('This trek is not open for booking.')
    if trek.available_slots <= 0:
        raise RuleError('No slots available for this trek.')
    if Booking.query.filter_by(user_id=user.id, trek_id=trek.id, status='Booked').first():
        raise RuleError('You have already booked this trek.', level='warning')

    booking = Booking(user_id=user.id, trek_id=trek.id, status='Booked')
    booking.payment = Payment(amount=trek.price, status='Paid')
    trek.available_slots -= 1
    db.session.add(booking)
    db.session.commit()
    return booking


def cancel_booking(booking):
    if booking.status != 'Booked':
        raise RuleError('Only active bookings can be cancelled.', level='info')

    booking.status = 'Cancelled'
    booking.trek.available_slots += 1
    if booking.payment:
        booking.payment.status = 'Refunded'
        booking.payment.refunded_at = datetime.utcnow()
    db.session.commit()


def add_trek(trek):
    db.session.add(trek)
    db.session.flush()
    log_action('trek.create', 'trek', trek.id, trek.name)


def apply_trek_fields(trek, values):
    # values maps column name -> new value; only real changes are written and logged
    # (None and '' both mean "empty", so they don't count as a change)
    changed = [f for f, v in values.items() if getattr(trek, f) != v and (getattr(trek, f) or v)]
    for f in changed:
        setattr(trek, f, values[f])
    if changed:
        log_action('trek.update', 'trek', trek.id, f'{trek.name}: changed {", ".join(changed)}')


def set_total_slots(trek, new_total):
    old_total = trek.total_slots
    # keep the number of people already booked, resize only the free part
    booked = trek.total_slots - trek.available_slots
    trek.available_slots = max(new_total - booked, 0)
    trek.total_slots = new_total
    if old_total != new_total:
        log_action('trek.slots', 'trek', trek.id, f'{trek.name}: {old_total} -> {new_total} slots')


def set_trek_status(trek, status):
    old = trek.status
    trek.status = status
    completed = 0
    if status == 'Completed':
        completed = Booking.query.filter_by(trek_id=trek.id, status='Booked').update({'status': 'Completed'})
    if old != status:
        detail = f'{trek.name}: {old} -> {status}'
        if completed:
            detail += f' ({completed} bookings completed)'
        log_action('trek.status', 'trek', trek.id, detail)


def assign_staff(trek, staff_id):
    old = trek.assigned_staff_id
    if staff_id is None:
        trek.assigned_staff_id = None
        if old is not None:
            log_action('trek.assign', 'trek', trek.id, f'{trek.name} -> unassigned')
        return

    staff = User.query.filter_by(id=staff_id, role='staff', status='active').first()
    if staff is None:
        raise RuleError('Choose an approved staff member.', status=400)
    trek.assigned_staff_id = staff.id
    detail = f'{trek.name} -> {staff.name}'
    promoted = trek.status == 'Pending'
    if promoted:
        trek.status = 'Approved'
        detail += ' (status Pending -> Approved)'
    if old != staff.id or promoted:
        log_action('trek.assign', 'trek', trek.id, detail)


def delete_trek(trek):
    log_action('trek.delete', 'trek', trek.id, trek.name)
    booking_ids = [b.id for b in Booking.query.filter_by(trek_id=trek.id)]
    if booking_ids:
        Payment.query.filter(Payment.booking_id.in_(booking_ids)).delete(synchronize_session=False)
    Booking.query.filter_by(trek_id=trek.id).delete()
    db.session.delete(trek)


def set_account_status(user, new_status):
    if new_status not in ('active', 'blacklisted'):
        raise RuleError('Status must be "active" or "blacklisted".', status=400)
    old = user.status
    user.status = new_status
    if new_status == 'blacklisted':
        verb = 'blacklist'
    elif old == 'pending':
        verb = 'approve'
    else:
        verb = 'reinstate'
    kind = 'staff' if user.role == 'staff' else 'user'
    log_action(f'{kind}.{verb}', 'user', user.id, f'{user.name} ({old} -> {new_status})')
