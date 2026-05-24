from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from models import db, User, Subject, StudySession, ReminderPreference, ReminderNote
from ai_engine import generate_study_plan
from scheduler import init_scheduler, send_reminder_email
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-fallback-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///timetable.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ─────────────────────────────────────────────────────────
#  Shared helpers
# ─────────────────────────────────────────────────────────

def _today_stats(user_id):
    today = datetime.now().date()
    sessions = (StudySession.query
                .filter_by(user_id=user_id, date=today)
                .order_by(StudySession.start_time)
                .all())
    total     = len(sessions)
    completed = sum(1 for s in sessions if s.completed)
    pending   = total - completed
    pct       = round((completed / total * 100) if total > 0 else 0, 1)
    return sessions, total, completed, pending, pct


def _priority_subjects(user_id):
    today    = datetime.now().date()
    subjects = Subject.query.filter_by(user_id=user_id).all()
    return sorted(
        [s for s in subjects if s.exam_date >= today],
        key=lambda x: x.priority_score,
        reverse=True
    )


# ─────────────────────────────────────────────────────────
#  Auth
# ─────────────────────────────────────────────────────────

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'danger')
            return render_template('register.html')
        if User.query.filter_by(username=username).first():
            flash('That username is already taken.', 'danger')
            return render_template('register.html')

        pw = bcrypt.generate_password_hash(password).decode('utf-8')
        db.session.add(User(username=username, email=email, password=pw))
        db.session.commit()
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user     = User.query.filter_by(email=email).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('onboarding') if not user.subjects else url_for('dashboard'))
        flash('Login unsuccessful. Please check email and password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))


# ─────────────────────────────────────────────────────────
#  Onboarding
# ─────────────────────────────────────────────────────────

@app.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    if request.method == 'POST':
        current_user.daily_study_hours = float(request.form.get('daily_hours', 0))

        names      = request.form.getlist('subject_name[]')
        exam_dates = request.form.getlist('exam_date[]')
        credits    = request.form.getlist('credit_hours[]')
        diffs      = request.form.getlist('difficulty[]')

        for i, name in enumerate(names):
            name = name.strip()
            if not name:
                continue
            try:
                d  = datetime.strptime(exam_dates[i], '%Y-%m-%d').date()
                cr = float(credits[i])
            except (ValueError, IndexError):
                flash(f'Invalid data for row {i+1}. Skipped.', 'danger')
                continue
            db.session.add(Subject(
                user_id=current_user.id, name=name,
                exam_date=d, credit_hours=cr, difficulty=diffs[i]
            ))

        db.session.commit()
        generate_study_plan(current_user)
        flash('Your AI timetable has been generated!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('onboarding.html')


# ─────────────────────────────────────────────────────────
#  Dashboard
# ─────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    today = datetime.now().date()
    sessions, total, completed, pending, pct = _today_stats(current_user.id)
    subjects    = Subject.query.filter_by(user_id=current_user.id).all()
    subject_map = {s.id: s for s in subjects}
    prio        = _priority_subjects(current_user.id)

    return render_template(
        'dashboard.html',
        sessions=sessions, subject_map=subject_map, today=today,
        total_today=total, completed_today=completed,
        pending_today=pending, progress_pct=pct,
        priority_subjects=prio,
    )


# ─────────────────────────────────────────────────────────
#  JSON API
# ─────────────────────────────────────────────────────────

@app.route('/api/dashboard_stats')
@login_required
def api_dashboard_stats():
    today = datetime.now().date()
    sessions, total, completed, pending, pct = _today_stats(current_user.id)
    subjects    = Subject.query.filter_by(user_id=current_user.id).all()
    subject_map = {s.id: s for s in subjects}

    session_data = [
        {
            'id':         s.id,
            'subject':    subject_map[s.subject_id].name if s.subject_id in subject_map else 'Unknown',
            'difficulty': subject_map[s.subject_id].difficulty if s.subject_id in subject_map else '',
            'start_time': s.start_time.strftime('%H:%M'),
            'end_time':   s.end_time.strftime('%H:%M'),
            'completed':  s.completed,
        }
        for s in sessions
    ]

    priority_data = [
        {
            'name':       sub.name,
            'score':      round(sub.priority_score, 3),
            'difficulty': sub.difficulty,
            'exam_date':  sub.exam_date.strftime('%Y-%m-%d'),
        }
        for sub in _priority_subjects(current_user.id)
    ]

    return jsonify({
        'total': total, 'completed': completed,
        'pending': pending, 'progress_pct': pct,
        'sessions': session_data,
        'priority_queue': priority_data,
    })


@app.route('/api/weekly_plan')
@login_required
def api_weekly_plan():
    from datetime import timedelta
    today    = datetime.now().date()
    end_date = today + timedelta(days=6)

    sessions = (StudySession.query
                .filter(StudySession.user_id == current_user.id,
                        StudySession.date >= today,
                        StudySession.date <= end_date)
                .order_by(StudySession.date, StudySession.start_time)
                .all())

    subjects    = Subject.query.filter_by(user_id=current_user.id).all()
    subject_map = {s.id: s for s in subjects}

    days = {}
    for s in sessions:
        key = s.date.strftime('%Y-%m-%d')
        if key not in days:
            days[key] = []
        sub = subject_map.get(s.subject_id)
        days[key].append({
            'id':         s.id,
            'subject':    sub.name if sub else 'Unknown',
            'difficulty': sub.difficulty if sub else '',
            'start_time': s.start_time.strftime('%H:%M'),
            'end_time':   s.end_time.strftime('%H:%M'),
            'completed':  s.completed,
        })

    return jsonify({'days': days})


# ─────────────────────────────────────────────────────────
#  Complete session
# ─────────────────────────────────────────────────────────

@app.route('/complete_session/<int:session_id>', methods=['POST'])
@login_required
def complete_session(session_id):
    session = db.get_or_404(StudySession, session_id)
    if session.user_id != current_user.id:
        return redirect(url_for('dashboard'))

    session.completed = True
    db.session.commit()
    generate_study_plan(current_user)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'status': 'ok'})
    return redirect(url_for('dashboard'))


# ─────────────────────────────────────────────────────────
#  Add subject
# ─────────────────────────────────────────────────────────

@app.route('/add_subject', methods=['GET', 'POST'])
@login_required
def add_subject():
    if request.method == 'POST':
        name        = request.form.get('subject_name', '').strip()
        exam_date_s = request.form.get('exam_date', '')
        credit_h    = request.form.get('credit_hours', '')
        difficulty  = request.form.get('difficulty', '')

        if not name:
            flash('Subject name is required.', 'danger')
            return render_template('add_subject.html')

        try:
            exam_date = datetime.strptime(exam_date_s, '%Y-%m-%d').date()
            credits   = float(credit_h)
        except (ValueError, TypeError):
            flash('Please enter a valid exam date and credit hours.', 'danger')
            return render_template('add_subject.html')

        db.session.add(Subject(
            user_id=current_user.id, name=name,
            exam_date=exam_date, credit_hours=credits, difficulty=difficulty
        ))
        db.session.commit()

        today           = datetime.now().date()
        todays_sessions = StudySession.query.filter_by(
            user_id=current_user.id, date=today
        ).all()

        already_done_hours = sum(
            (datetime.combine(today, s.end_time) -
             datetime.combine(today, s.start_time)).total_seconds() / 3600
            for s in todays_sessions if s.completed
        )

        daily_hours      = current_user.daily_study_hours or 0
        remaining_budget = max(daily_hours - already_done_hours, 0)
        budget_exhausted = (daily_hours > 0) and (remaining_budget <= 0)
        all_complete     = len(todays_sessions) > 0 and all(
            s.completed for s in todays_sessions
        )
        skip_today = all_complete or budget_exhausted

        generate_study_plan(current_user, skip_today=skip_today)
        flash(f'"{name}" added and timetable updated!', 'success')

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'ok', 'subject': name})
        return redirect(url_for('dashboard'))

    return render_template('add_subject.html')


# ─────────────────────────────────────────────────────────
#  Other routes
# ─────────────────────────────────────────────────────────

@app.route('/progress')
@login_required
def progress():
    subjects = Subject.query.filter_by(user_id=current_user.id).all()
    stats = []
    for sub in subjects:
        total     = StudySession.query.filter_by(subject_id=sub.id).count()
        completed = StudySession.query.filter_by(subject_id=sub.id, completed=True).count()
        rate      = (completed / total * 100) if total > 0 else 0
        stats.append({'name': sub.name, 'rate': round(rate, 1)})
    return render_template('progress.html', stats=stats)


@app.route('/regenerate_plan', methods=['POST'])
@login_required
def regenerate_plan():
    generate_study_plan(current_user)
    flash('Your study plan has been regenerated!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/delete_subject/<int:subject_id>', methods=['POST'])
@login_required
def delete_subject(subject_id):
    subject = db.get_or_404(Subject, subject_id)
    if subject.user_id == current_user.id:
        name = subject.name
        StudySession.query.filter_by(subject_id=subject.id).delete()
        db.session.delete(subject)
        db.session.commit()
        generate_study_plan(current_user)
        flash(f'"{name}" removed and timetable updated!', 'success')
    return redirect(url_for('dashboard'))


# ─────────────────────────────────────────────────────────
#  Reminder settings
# ─────────────────────────────────────────────────────────

@app.route('/settings/reminders', methods=['GET', 'POST'])
@login_required
def reminder_settings():
    pref = ReminderPreference.query.filter_by(user_id=current_user.id).first()
    if not pref:
        pref = ReminderPreference(user_id=current_user.id)
        db.session.add(pref)
        db.session.commit()

    if request.method == 'POST':
        pref.session_reminders_enabled = 'session_reminders_enabled' in request.form
        pref.session_lead_minutes      = int(request.form.get('session_lead_minutes', 30))
        pref.daily_digest_enabled      = 'daily_digest_enabled' in request.form
        pref.daily_digest_hour         = int(request.form.get('daily_digest_hour', 8))
        pref.exam_reminder_enabled     = 'exam_reminder_enabled' in request.form
        pref.exam_reminder_days_before = int(request.form.get('exam_reminder_days_before', 1))
        pref.email_enabled             = 'email_enabled' in request.form
        db.session.commit()
        flash('Reminder preferences saved!', 'success')
        return redirect(url_for('reminder_settings'))

    notes = ReminderNote.query.filter_by(user_id=current_user.id).order_by(ReminderNote.created_at.desc()).all()
    return render_template('reminder_settings.html', pref=pref, notes=notes)


@app.route('/api/reminders/test', methods=['POST'])
@login_required
def test_reminder():
    kind = (request.json or {}).get('kind', 'session')
    messages = {
        'session': (
            "Test Session Reminder",
            f"Hi {current_user.username},\n\nThis is a TEST session reminder.\n"
            "If you received this, email reminders are working!"
        ),
        'digest': (
            "Test Daily Digest",
            f"Hi {current_user.username},\n\nThis is a TEST daily digest.\n"
            "Your real digest will list today's sessions every morning."
        ),
        'exam': (
            "Test Exam Alert",
            f"Hi {current_user.username},\n\nThis is a TEST exam countdown alert.\n"
            "You'll receive one before each exam."
        ),
    }
    subj, body = messages.get(kind, messages['session'])
    send_reminder_email(current_user.email, subj, body)
    return jsonify({'status': 'ok', 'message': f'Test {kind} email logged for {current_user.email}'})


# ─────────────────────────────────────────────────────────
#  Reminder Notes (Notepad)
# ─────────────────────────────────────────────────────────

@app.route('/api/reminder_notes', methods=['POST'])
@login_required
def add_reminder_note():
    data       = request.json or {}
    heading    = (data.get('heading') or '').strip()
    body       = (data.get('body') or '').strip()
    remind_at_s = (data.get('remind_at') or '').strip()
    if not heading or not body:
        return jsonify({'status': 'error', 'message': 'Heading and body are required.'}), 400

    remind_at = None
    if remind_at_s:
        try:
            remind_at = datetime.strptime(remind_at_s, '%Y-%m-%dT%H:%M')
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Invalid remind_at format. Use YYYY-MM-DDTHH:MM.'}), 400

    note = ReminderNote(user_id=current_user.id, heading=heading, body=body, remind_at=remind_at)
    db.session.add(note)
    db.session.commit()
    return jsonify({
        'status': 'ok',
        'note': {
            'id':         note.id,
            'heading':    note.heading,
            'body':       note.body,
            'remind_at':  note.remind_at.strftime('%d %b %Y, %H:%M') if note.remind_at else None,
            'notified':   note.notified,
            'created_at': note.created_at.strftime('%d %b %Y, %H:%M'),
        }
    })


@app.route('/api/reminder_notes/<int:note_id>', methods=['PUT'])
@login_required
def update_reminder_note(note_id):
    note = db.get_or_404(ReminderNote, note_id)
    if note.user_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'Forbidden'}), 403
    data        = request.json or {}
    heading     = (data.get('heading') or '').strip()
    body        = (data.get('body') or '').strip()
    remind_at_s = (data.get('remind_at') or '').strip()
    if not heading or not body:
        return jsonify({'status': 'error', 'message': 'Heading and body are required.'}), 400

    remind_at = None
    if remind_at_s:
        try:
            remind_at = datetime.strptime(remind_at_s, '%Y-%m-%dT%H:%M')
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Invalid remind_at format. Use YYYY-MM-DDTHH:MM.'}), 400

    note.heading    = heading
    note.body       = body
    note.remind_at  = remind_at
    note.notified   = False   # reset so a new time triggers a fresh notification
    note.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'status': 'ok'})


@app.route('/api/reminder_notes/<int:note_id>', methods=['DELETE'])
@login_required
def delete_reminder_note(note_id):
    note = db.get_or_404(ReminderNote, note_id)
    if note.user_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'Forbidden'}), 403
    db.session.delete(note)
    db.session.commit()
    return jsonify({'status': 'ok'})


# ─────────────────────────────────────────────────────────
#  Startup  ← MUST be last
# ─────────────────────────────────────────────────────────

def create_db():
    with app.app_context():
        db.create_all()


if __name__ == '__main__':
    create_db()
    init_scheduler(app)
    app.run(debug=True, use_reloader=False)
