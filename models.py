from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    daily_study_hours = db.Column(db.Float, default=0.0)
    subjects = db.relationship('Subject', backref='user', lazy=True)
    study_sessions = db.relationship('StudySession', backref='user', lazy=True)

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    exam_date = db.Column(db.Date, nullable=False)
    credit_hours = db.Column(db.Float, nullable=False)
    difficulty = db.Column(db.String(50), nullable=False)
    priority_score = db.Column(db.Float, default=0.0)

class StudySession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    completed = db.Column(db.Boolean, default=False)
    notified = db.Column(db.Boolean, default=False)


class ReminderPreference(db.Model):
    """Per-user reminder configuration."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)

    # Session reminders
    session_reminders_enabled = db.Column(db.Boolean, default=True)
    session_lead_minutes = db.Column(db.Integer, default=30)   # how many mins before session

    # Daily digest — sent once a day at a chosen hour
    daily_digest_enabled = db.Column(db.Boolean, default=True)
    daily_digest_hour = db.Column(db.Integer, default=8)        # 0-23

    # Exam countdown — alert N days before exam
    exam_reminder_enabled = db.Column(db.Boolean, default=True)
    exam_reminder_days_before = db.Column(db.Integer, default=1)  # 1 = day before

    # Channels
    email_enabled = db.Column(db.Boolean, default=True)

    # Track digest notification so we don't double-send on the same day
    last_digest_date = db.Column(db.Date, nullable=True)

    user = db.relationship('User', backref=db.backref('reminder_pref', uselist=False))


class ReminderNote(db.Model):
    """A notepad entry linked to a user's reminder settings."""
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    heading    = db.Column(db.String(200), nullable=False)
    body       = db.Column(db.Text, nullable=False)
    remind_at  = db.Column(db.DateTime, nullable=True)   # when to fire the notification
    notified   = db.Column(db.Boolean, default=False)    # prevent duplicate sends
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('reminder_notes', lazy=True))
