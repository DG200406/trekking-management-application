"""
Admin login: admin@trek.com / admin123
(see README.md for the full list of seeded demo accounts)
"""
import os
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

from app import app, DB_PATH
from models import db, User, StaffProfile, Trek, Booking, Payment, AuditLog

DB_FILE = DB_PATH


def seed():
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    with app.app_context():
        db.create_all()

        # users
        admin = User(
            name='Admin', email='admin@trek.com',
            password_hash=generate_password_hash('admin123'),
            role='admin', phone='9999999999', status='active',
        )

        staff_ravi = User(
            name='Ravi Sharma', email='ravi@trek.com',
            password_hash=generate_password_hash('staff123'),
            role='staff', phone='9876500001', status='active',
        )
        staff_meena = User(
            name='Meena Rawat', email='meena@trek.com',
            password_hash=generate_password_hash('staff123'),
            role='staff', phone='9876500002', status='active',
        )
        staff_pending = User(
            name='Karan Bisht', email='karan@trek.com',
            password_hash=generate_password_hash('staff123'),
            role='staff', phone='9876500003', status='pending',
        )
        staff_blacklisted = User(
            name='Suresh Rana', email='suresh@trek.com',
            password_hash=generate_password_hash('staff123'),
            role='staff', phone='9876500004', status='blacklisted',
        )

        user_aditi = User(
            name='Aditi Verma', email='aditi@example.com',
            password_hash=generate_password_hash('user123'),
            role='trekker', phone='9123456701', status='active',
        )
        user_rohan = User(
            name='Rohan Gupta', email='rohan@example.com',
            password_hash=generate_password_hash('user123'),
            role='trekker', phone='9123456702', status='active',
        )
        user_sneha = User(
            name='Sneha Iyer', email='sneha@example.com',
            password_hash=generate_password_hash('user123'),
            role='trekker', phone='9123456703', status='active',
        )
        user_blacklisted = User(
            name='Vikram Singh', email='vikram@example.com',
            password_hash=generate_password_hash('user123'),
            role='trekker', phone='9123456704', status='blacklisted',
        )

        db.session.add_all([
            admin, staff_ravi, staff_meena, staff_pending, staff_blacklisted,
            user_aditi, user_rohan, user_sneha, user_blacklisted,
        ])
        db.session.commit()

        # staff profiles
        db.session.add_all([
            StaffProfile(
                user_id=staff_ravi.id, experience_years=8,
                certifications='Wilderness First Responder, NIMAS Basic',
                emergency_contact='9876500101',
                bio='Leads Himalayan winter treks and high-altitude expeditions.',
            ),
            StaffProfile(
                user_id=staff_meena.id, experience_years=5,
                certifications='Wilderness First Aid',
                emergency_contact='9876500102',
                bio='Specialises in flower-valley and monsoon treks.',
            ),
            StaffProfile(
                user_id=staff_pending.id, experience_years=2,
                certifications='', emergency_contact='9876500103',
                bio='Recently moved from city-run day hikes to multi-day treks.',
            ),
        ])
        db.session.commit()

        # treks
        today = date.today()

        trek_kedar = Trek(
            name='Kedarkantha Trek', location='Uttarakhand', difficulty='Moderate',
            duration=6, price=8500, total_slots=20, available_slots=17,
            assigned_staff_id=staff_ravi.id, status='Open',
            start_date=today + timedelta(days=20), end_date=today + timedelta(days=26),
            description='A classic winter snow trek through pine and oak forests.',
        )
        trek_valley = Trek(
            name='Valley of Flowers', location='Uttarakhand', difficulty='Easy',
            duration=4, price=6500, total_slots=15, available_slots=15,
            assigned_staff_id=staff_meena.id, status='Open',
            start_date=today + timedelta(days=35), end_date=today + timedelta(days=39),
            description='UNESCO World Heritage site famous for endemic alpine flowers.',
        )
        trek_everest = Trek(
            name='Everest Base Camp', location='Nepal', difficulty='Hard',
            duration=14, price=65000, total_slots=10, available_slots=10,
            assigned_staff_id=staff_ravi.id, status='Closed',
            start_date=today + timedelta(days=60), end_date=today + timedelta(days=74),
            description='The iconic high-altitude trek to the base of Mt. Everest.',
        )
        trek_hampta = Trek(
            name='Hampta Pass', location='Himachal Pradesh', difficulty='Moderate',
            duration=5, price=9000, total_slots=18, available_slots=18,
            assigned_staff_id=None, status='Pending',
            start_date=today + timedelta(days=45), end_date=today + timedelta(days=50),
            description='Crosses from the green Kullu valley to arid Lahaul.',
        )
        trek_sandakphu = Trek(
            name='Sandakphu Trek', location='West Bengal', difficulty='Easy',
            duration=5, price=7000, total_slots=12, available_slots=12,
            assigned_staff_id=staff_meena.id, status='Approved',
            start_date=today + timedelta(days=50), end_date=today + timedelta(days=55),
            description='Highest peak of West Bengal with views of four 8000m peaks.',
        )
        trek_completed = Trek(
            name='Triund Trek', location='Himachal Pradesh', difficulty='Easy',
            duration=2, price=2500, total_slots=25, available_slots=22,
            assigned_staff_id=staff_ravi.id, status='Completed',
            start_date=today - timedelta(days=15), end_date=today - timedelta(days=13),
            description='A short and popular weekend trek near McLeod Ganj.',
        )

        db.session.add_all([
            trek_kedar, trek_valley, trek_everest, trek_hampta, trek_sandakphu, trek_completed,
        ])
        db.session.commit()

        # bookings
        bookings = [
            Booking(user_id=user_aditi.id, trek_id=trek_kedar.id, status='Booked',
                    booking_date=datetime.utcnow() - timedelta(days=5)),
            Booking(user_id=user_rohan.id, trek_id=trek_kedar.id, status='Booked',
                    booking_date=datetime.utcnow() - timedelta(days=4)),
            Booking(user_id=user_sneha.id, trek_id=trek_kedar.id, status='Booked',
                    booking_date=datetime.utcnow() - timedelta(days=2)),
            Booking(user_id=user_aditi.id, trek_id=trek_completed.id, status='Completed',
                    booking_date=datetime.utcnow() - timedelta(days=20)),
            Booking(user_id=user_rohan.id, trek_id=trek_completed.id, status='Completed',
                    booking_date=datetime.utcnow() - timedelta(days=19)),
            Booking(user_id=user_sneha.id, trek_id=trek_completed.id, status='Cancelled',
                    booking_date=datetime.utcnow() - timedelta(days=18)),
        ]
        db.session.add_all(bookings)
        db.session.flush()

        # payments: one per booking, refunded where the booking was cancelled
        prices = {trek_kedar.id: trek_kedar.price, trek_completed.id: trek_completed.price}
        for b in bookings:
            cancelled = b.status == 'Cancelled'
            db.session.add(Payment(
                booking_id=b.id, amount=prices[b.trek_id],
                status='Refunded' if cancelled else 'Paid',
                paid_at=b.booking_date,
                refunded_at=b.booking_date + timedelta(days=1) if cancelled else None,
            ))

        # audit log
        now = datetime.utcnow()
        entries = [
            (admin, 'staff.approve', 'user', staff_ravi.id, 'Ravi Sharma (pending -> active)', 40),
            (admin, 'staff.approve', 'user', staff_meena.id, 'Meena Rawat (pending -> active)', 39),
            (admin, 'staff.blacklist', 'user', staff_blacklisted.id, 'Suresh Rana (active -> blacklisted)', 30),
            (admin, 'trek.create', 'trek', trek_kedar.id, 'Kedarkantha Trek', 28),
            (admin, 'trek.assign', 'trek', trek_kedar.id, 'Kedarkantha Trek -> Ravi Sharma', 28),
            (staff_ravi, 'trek.update', 'trek', trek_kedar.id, 'Kedarkantha Trek: status Approved -> Open', 27),
            (admin, 'user.blacklist', 'user', user_blacklisted.id, 'Vikram Singh (active -> blacklisted)', 10),
        ]
        for actor, action, target_type, target_id, detail, days_ago in entries:
            db.session.add(AuditLog(
                actor_id=actor.id, actor_name=actor.name, actor_role=actor.role,
                action=action, target_type=target_type, target_id=target_id,
                detail=detail, created_at=now - timedelta(days=days_ago),
            ))
        db.session.commit()

        print('trekking.db created and seeded successfully.')
        print()
        print('Demo login credentials')
        print('-----------------------')
        print('Admin    : admin@trek.com   / admin123')
        print('Staff    : ravi@trek.com    / staff123   (approved)')
        print('Staff    : meena@trek.com   / staff123   (approved)')
        print('Staff    : karan@trek.com   / staff123   (pending approval)')
        print('Staff    : suresh@trek.com  / staff123   (blacklisted)')
        print('Trekker  : aditi@example.com / user123')
        print('Trekker  : rohan@example.com / user123')
        print('Trekker  : sneha@example.com / user123')
        print('Trekker  : vikram@example.com / user123  (blacklisted)')


if __name__ == '__main__':
    seed()
