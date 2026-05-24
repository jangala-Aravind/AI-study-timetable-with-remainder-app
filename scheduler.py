from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, date
import os


# ─────────────────────────────────────────────────────────
#  Email sending
# ─────────────────────────────────────────────────────────

def send_reminder_email(to_email, subject, body, html_body=None):
    sender_email    = os.environ.get("SENDER_EMAIL", "test@example.com")
    sender_password = os.environ.get("SENDER_PASSWORD", "password")

    if html_body:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
    else:
        msg = MIMEText(body)

    msg['Subject'] = subject
    msg['From']    = sender_email
    msg['To']      = to_email

    # Console preview (always)
    print(f"\n{'─'*50}")
    print(f"📧 EMAIL REMINDER")
    print(f"   To      : {to_email}")
    print(f"   Subject : {subject}")
    print(f"   Body    : {body[:200]}{'...' if len(body) > 200 else ''}")
    print(f"{'─'*50}\n")

    # Uncomment to send real emails via Gmail:
    # try:
    #     with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
    #         server.login(sender_email, sender_password)
    #         server.sendmail(sender_email, [to_email], msg.as_string())
    # except Exception as e:
    #     print(f"Failed to send email: {e}")


# ─────────────────────────────────────────────────────────
#  Helper: get or create reminder preference for a user
# ─────────────────────────────────────────────────────────

def _get_or_create_pref(db, ReminderPreference, user_id):
    pref = ReminderPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = ReminderPreference(user_id=user_id)
        db.session.add(pref)
        db.session.flush()
    return pref


# ─────────────────────────────────────────────────────────
#  Job 1 – Upcoming session reminders (every 10 min)
# ─────────────────────────────────────────────────────────

def check_upcoming_sessions(app):
    """
    Sends a reminder email N minutes before each unstarted study session,
    where N comes from the user's ReminderPreference.session_lead_minutes.
    Falls back to 30 minutes if no preference exists.
    """
    from models import db, StudySession, User, Subject, ReminderPreference

    with app.app_context():
        now          = datetime.now()
        current_date = now.date()
        current_time = now.time()

        # Load all today's un-notified, incomplete sessions
        sessions = StudySession.query.filter(
            StudySession.date == current_date,
            StudySession.start_time > current_time,
            StudySession.notified  == False,
            StudySession.completed == False
        ).all()

        for session in sessions:
            user    = db.session.get(User, session.user_id)
            subject = db.session.get(Subject, session.subject_id)

            if not user or not subject:
                continue

            pref = _get_or_create_pref(db, ReminderPreference, user.id)

            if not pref.session_reminders_enabled or not pref.email_enabled:
                continue

            lead_minutes  = pref.session_lead_minutes or 30
            upcoming_time = (datetime.combine(current_date, session.start_time)
                             - timedelta(minutes=lead_minutes))

            # Only notify if we're within the window: [upcoming_time, session start)
            if not (upcoming_time <= now < datetime.combine(current_date, session.start_time)):
                continue

            duration_mins = int(
                (datetime.combine(current_date, session.end_time) -
                 datetime.combine(current_date, session.start_time)).total_seconds() / 60
            )

            email_subject = f"⏰ Study Reminder: {subject.name} in {lead_minutes} min"
            plain_body = (
                f"Hi {user.username},\n\n"
                f"Your study session for {subject.name} starts at "
                f"{session.start_time.strftime('%H:%M')} "
                f"({duration_mins} minutes).\n"
                f"Difficulty: {subject.difficulty}\n\n"
                f"Good luck! 📚"
            )
            html_body = f"""
<html><body style="font-family:sans-serif;max-width:500px;margin:auto">
  <div style="background:#4f46e5;color:white;padding:20px;border-radius:8px 8px 0 0">
    <h2 style="margin:0">⏰ Study Reminder</h2>
  </div>
  <div style="border:1px solid #e5e7eb;padding:20px;border-radius:0 0 8px 8px">
    <p>Hi <strong>{user.username}</strong>,</p>
    <p>Your session for <strong>{subject.name}</strong> starts at
       <strong>{session.start_time.strftime('%H:%M')}</strong>
       in <strong>{lead_minutes} minutes</strong>.</p>
    <table style="border-collapse:collapse;width:100%">
      <tr><td style="padding:4px 8px;color:#6b7280">Duration</td>
          <td style="padding:4px 8px"><strong>{duration_mins} min</strong></td></tr>
      <tr><td style="padding:4px 8px;color:#6b7280">Difficulty</td>
          <td style="padding:4px 8px"><strong>{subject.difficulty}</strong></td></tr>
    </table>
    <p style="margin-top:20px">Good luck! 📚</p>
  </div>
</body></html>"""

            send_reminder_email(user.email, email_subject, plain_body, html_body)
            session.notified = True

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Session commit failed: {e}")


# ─────────────────────────────────────────────────────────
#  Job 2 – Daily digest (every hour, fires once per day)
# ─────────────────────────────────────────────────────────

def send_daily_digest(app):
    """
    Sends a morning digest listing today's planned sessions.
    Fires once per day at the hour set in the user's preferences.
    """
    from models import db, StudySession, User, Subject, ReminderPreference

    with app.app_context():
        now   = datetime.now()
        today = now.date()
        hour  = now.hour

        users = User.query.all()
        for user in users:
            pref = _get_or_create_pref(db, ReminderPreference, user.id)

            if not pref.daily_digest_enabled or not pref.email_enabled:
                continue
            if pref.daily_digest_hour != hour:
                continue
            if pref.last_digest_date == today:
                continue   # already sent today

            sessions = (StudySession.query
                        .filter_by(user_id=user.id, date=today)
                        .order_by(StudySession.start_time)
                        .all())

            if not sessions:
                continue

            subjects = {s.id: s for s in Subject.query.filter_by(user_id=user.id).all()}

            rows_plain = ""
            rows_html  = ""
            total_mins = 0
            for s in sessions:
                sub  = subjects.get(s.subject_id)
                name = sub.name if sub else "Unknown"
                mins = int(
                    (datetime.combine(today, s.end_time) -
                     datetime.combine(today, s.start_time)).total_seconds() / 60
                )
                total_mins += mins
                status = "✅" if s.completed else "📖"
                rows_plain += f"  {status} {s.start_time.strftime('%H:%M')} – {name} ({mins} min)\n"
                color  = "#d1fae5" if s.completed else "#eff6ff"
                rows_html += (
                    f"<tr style='background:{color}'>"
                    f"<td style='padding:6px 10px'>{s.start_time.strftime('%H:%M')}</td>"
                    f"<td style='padding:6px 10px'><strong>{name}</strong></td>"
                    f"<td style='padding:6px 10px'>{mins} min</td>"
                    f"<td style='padding:6px 10px'>{status}</td></tr>"
                )

            hours_str = f"{total_mins // 60}h {total_mins % 60}m" if total_mins >= 60 else f"{total_mins}m"
            plain_body = (
                f"Good morning {user.username}! Here's your study plan for today:\n\n"
                f"{rows_plain}\n"
                f"Total: {hours_str}\n\nHave a productive day! 🚀"
            )
            html_body = f"""
<html><body style="font-family:sans-serif;max-width:560px;margin:auto">
  <div style="background:#4f46e5;color:white;padding:20px;border-radius:8px 8px 0 0">
    <h2 style="margin:0">📅 Daily Study Digest</h2>
    <p style="margin:4px 0 0;opacity:.85">{today.strftime('%A, %d %B %Y')}</p>
  </div>
  <div style="border:1px solid #e5e7eb;padding:20px;border-radius:0 0 8px 8px">
    <p>Good morning <strong>{user.username}</strong>! Here's your plan:</p>
    <table style="border-collapse:collapse;width:100%;border:1px solid #e5e7eb;border-radius:6px;overflow:hidden">
      <thead><tr style="background:#f3f4f6">
        <th style="padding:8px 10px;text-align:left">Time</th>
        <th style="padding:8px 10px;text-align:left">Subject</th>
        <th style="padding:8px 10px;text-align:left">Duration</th>
        <th style="padding:8px 10px;text-align:left">Status</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    <p style="margin-top:16px;color:#6b7280">Total study time today: <strong>{hours_str}</strong></p>
    <p>Have a productive day! 🚀</p>
  </div>
</body></html>"""

            send_reminder_email(
                user.email,
                f"📅 Your Study Plan for {today.strftime('%A')}",
                plain_body,
                html_body
            )
            pref.last_digest_date = today

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Digest commit failed: {e}")


# ─────────────────────────────────────────────────────────
#  Job 3 – Exam countdown reminders (daily at midnight)
# ─────────────────────────────────────────────────────────

def check_exam_countdowns(app):
    """
    Alerts users when an exam is N days away (default: 1 day before).
    Runs once per day.
    """
    from models import db, User, Subject, ReminderPreference

    with app.app_context():
        today = date.today()
        users = User.query.all()

        for user in users:
            pref = _get_or_create_pref(db, ReminderPreference, user.id)

            if not pref.exam_reminder_enabled or not pref.email_enabled:
                continue

            days_before = pref.exam_reminder_days_before or 1
            target_date = today + timedelta(days=days_before)

            exams_due = Subject.query.filter_by(user_id=user.id, exam_date=target_date).all()

            for sub in exams_due:
                plain_body = (
                    f"Hi {user.username},\n\n"
                    f"⚠️  Your exam for {sub.name} is in {days_before} day(s)!\n\n"
                    f"Exam date : {sub.exam_date.strftime('%A, %d %B %Y')}\n"
                    f"Difficulty: {sub.difficulty}\n"
                    f"Credit hrs: {sub.credit_hours}\n\n"
                    f"Make sure you've reviewed everything. You've got this! 💪"
                )
                html_body = f"""
<html><body style="font-family:sans-serif;max-width:500px;margin:auto">
  <div style="background:#dc2626;color:white;padding:20px;border-radius:8px 8px 0 0">
    <h2 style="margin:0">⚠️ Exam Alert</h2>
    <p style="margin:4px 0 0;opacity:.85">{days_before} day{'s' if days_before != 1 else ''} to go!</p>
  </div>
  <div style="border:1px solid #e5e7eb;padding:20px;border-radius:0 0 8px 8px">
    <p>Hi <strong>{user.username}</strong>,</p>
    <p>Your exam for <strong>{sub.name}</strong> is coming up!</p>
    <table style="border-collapse:collapse;width:100%">
      <tr><td style="padding:4px 8px;color:#6b7280">Exam date</td>
          <td style="padding:4px 8px"><strong>{sub.exam_date.strftime('%A, %d %B %Y')}</strong></td></tr>
      <tr><td style="padding:4px 8px;color:#6b7280">Difficulty</td>
          <td style="padding:4px 8px"><strong>{sub.difficulty}</strong></td></tr>
      <tr><td style="padding:4px 8px;color:#6b7280">Credit hours</td>
          <td style="padding:4px 8px"><strong>{sub.credit_hours}</strong></td></tr>
    </table>
    <p style="margin-top:20px">You've got this! 💪</p>
  </div>
</body></html>"""

                send_reminder_email(
                    user.email,
                    f"⚠️ Exam Alert: {sub.name} is {days_before} day{'s' if days_before != 1 else ''} away!",
                    plain_body,
                    html_body
                )


# ─────────────────────────────────────────────────────────
#  Job 4 – Reminder Note alerts (every 5 min)
# ─────────────────────────────────────────────────────────

def check_reminder_notes(app):
    """
    Sends an email when a ReminderNote's remind_at time has arrived.
    Fires every 5 minutes; marks the note as notified so it is only
    sent once even if the job runs again before the minute ticks over.
    """
    from models import db, ReminderNote, User, ReminderPreference

    with app.app_context():
        now = datetime.now()

        # Find all un-notified notes whose remind_at is in the past (or right now)
        due_notes = ReminderNote.query.filter(
            ReminderNote.remind_at <= now,
            ReminderNote.notified  == False
        ).all()

        for note in due_notes:
            user = db.session.get(User, note.user_id)
            if not user:
                continue

            pref = _get_or_create_pref(db, ReminderPreference, user.id)
            if not pref.email_enabled:
                continue

            email_subject = f"🗒️ Note Reminder: {note.heading}"
            plain_body = (
                f"Hi {user.username},\n\n"
                f"This is your scheduled reminder for:\n\n"
                f"  {note.heading}\n\n"
                f"{note.body}\n\n"
                f"Reminder was set for: {note.remind_at.strftime('%d %b %Y at %H:%M')}"
            )
            html_body = f"""
<html><body style="font-family:sans-serif;max-width:500px;margin:auto">
  <div style="background:#4f46e5;color:white;padding:20px;border-radius:8px 8px 0 0">
    <h2 style="margin:0">🗒️ Note Reminder</h2>
    <p style="margin:4px 0 0;opacity:.85">{note.remind_at.strftime('%d %b %Y at %H:%M')}</p>
  </div>
  <div style="border:1px solid #e5e7eb;padding:20px;border-radius:0 0 8px 8px">
    <p>Hi <strong>{user.username}</strong>,</p>
    <p>This is your scheduled reminder for:</p>
    <div style="background:#f9fafb;border-left:4px solid #4f46e5;padding:12px 16px;border-radius:4px;margin:12px 0">
      <strong style="font-size:1.05em">{note.heading}</strong>
      <p style="margin:8px 0 0;color:#374151;white-space:pre-wrap">{note.body}</p>
    </div>
  </div>
</body></html>"""

            send_reminder_email(user.email, email_subject, plain_body, html_body)
            note.notified = True

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Note reminder commit failed: {e}")




def init_scheduler(app):
    scheduler = BackgroundScheduler()

    # Job 1: Session reminders — every 10 minutes
    scheduler.add_job(
        func=check_upcoming_sessions,
        args=[app],
        trigger="interval",
        minutes=10,
        id="session_reminders"
    )

    # Job 2: Daily digest — every hour (fires at configured hour)
    scheduler.add_job(
        func=send_daily_digest,
        args=[app],
        trigger="interval",
        hours=1,
        id="daily_digest"
    )

    # Job 3: Exam countdown — every day at 07:00
    scheduler.add_job(
        func=check_exam_countdowns,
        args=[app],
        trigger="cron",
        hour=7,
        minute=0,
        id="exam_countdown"
    )

    # Job 4: Note reminders — every 5 minutes
    scheduler.add_job(
        func=check_reminder_notes,
        args=[app],
        trigger="interval",
        minutes=5,
        id="note_reminders"
    )

    scheduler.start()
    return scheduler
