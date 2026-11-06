from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """Single table for all three roles: admin / staff / trekker."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin | staff | trekker
    phone = db.Column(db.String(20))
    # active (can use app) | pending (staff awaiting admin approval) | blacklisted
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    treks_assigned = db.relationship('Trek', backref='staff', lazy=True)
    bookings = db.relationship('Booking', backref='trekker', lazy=True)
    staff_profile = db.relationship('StaffProfile', backref='user', uselist=False, lazy=True)


class StaffProfile(db.Model):
    """Extra details for staff accounts, one row per staff user."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    experience_years = db.Column(db.Integer, nullable=False, default=0)
    certifications = db.Column(db.String(255))
    emergency_contact = db.Column(db.String(20))
    bio = db.Column(db.Text)


class Trek(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(120), nullable=False)
    difficulty = db.Column(db.String(20), nullable=False)  # Easy | Moderate | Hard
    duration = db.Column(db.Integer, nullable=False)  # days
    price = db.Column(db.Integer, nullable=False, default=0)  # rupees per person
    total_slots = db.Column(db.Integer, nullable=False)
    available_slots = db.Column(db.Integer, nullable=False)
    assigned_staff_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    # Pending | Approved | Open | Closed | Completed
    status = db.Column(db.String(20), nullable=False, default='Pending')
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    bookings = db.relationship('Booking', backref='trek', lazy=True)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    trek_id = db.Column(db.Integer, db.ForeignKey('trek.id'), nullable=False)
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), nullable=False, default='Booked')  # Booked | Cancelled | Completed

    payment = db.relationship('Payment', backref='booking', uselist=False, lazy=True)


class Payment(db.Model):
    """Simulated payment record, one per booking. No payment gateway is involved."""
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), unique=True, nullable=False)
    amount = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default='Paid')  # Paid | Refunded
    paid_at = db.Column(db.DateTime, default=datetime.utcnow)
    refunded_at = db.Column(db.DateTime)


class AuditLog(db.Model):
    """Who did what: privileged actions by admin and staff."""
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    # name and role are copied so the entry still reads correctly if the account is deleted
    actor_name = db.Column(db.String(100), nullable=False)
    actor_role = db.Column(db.String(20), nullable=False)
    action = db.Column(db.String(40), nullable=False)  # e.g. trek.create, staff.approve
    target_type = db.Column(db.String(20))  # trek | user
    target_id = db.Column(db.Integer)
    detail = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
