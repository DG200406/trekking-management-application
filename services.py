from datetime import datetime

from models import db, User, Booking, Payment

TREK_STATUSES = ('Pending', 'Approved', 'Open', 'Closed', 'Completed')
STAFF_STATUSES = ('Approved', 'Open', 'Closed', 'Completed')


class RuleError(Exception):
    # level is the flash category for HTML pages, status is the HTTP code for the API
    def __init__(self, message, level='danger', status=409):
        super().__init__(message)
        self.message = message
        self.level = level
        self.status = status


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


def set_total_slots(trek, new_total):
    # keep the number of people already booked, resize only the free part
    booked = trek.total_slots - trek.available_slots
    trek.available_slots = max(new_total - booked, 0)
    trek.total_slots = new_total


def set_trek_status(trek, status):
    trek.status = status
    if status == 'Completed':
        Booking.query.filter_by(trek_id=trek.id, status='Booked').update({'status': 'Completed'})


def assign_staff(trek, staff_id):
    if staff_id is None:
        trek.assigned_staff_id = None
        return
    staff = User.query.filter_by(id=staff_id, role='staff', status='active').first()
    if staff is None:
        raise RuleError('Choose an approved staff member.', status=400)
    trek.assigned_staff_id = staff.id
    if trek.status == 'Pending':
        trek.status = 'Approved'


def delete_trek(trek):
    booking_ids = [b.id for b in Booking.query.filter_by(trek_id=trek.id)]
    if booking_ids:
        Payment.query.filter(Payment.booking_id.in_(booking_ids)).delete(synchronize_session=False)
    Booking.query.filter_by(trek_id=trek.id).delete()
    db.session.delete(trek)
