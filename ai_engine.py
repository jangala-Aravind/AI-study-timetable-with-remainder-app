from models import db, Subject, StudySession
from datetime import datetime, timedelta, date
import math


def calculate_priority(subject):
    difficulty_map = {'Hard': 1.0, 'Medium': 0.6, 'Weak': 0.3}
    diff_val = difficulty_map.get(subject.difficulty, 0.3)
    days_until_exam = (subject.exam_date - date.today()).days
    if days_until_exam < 0:
        days_until_exam = 0
    urgency = 1.0 / math.log(max(days_until_exam, 1) + 1)
    priority = diff_val * urgency * subject.credit_hours
    subject.priority_score = priority
    return priority


def generate_study_plan(user, skip_today=False):
    """
    Regenerates the study plan for the next 7 days.

    Key rules:
    - Completed sessions are NEVER deleted or touched.
    - Subjects already completed today are excluded from new slots today,
      so the same task is never duplicated.
    - skip_today=True → today is skipped entirely. Used when a new subject
      is added after today's work is fully done, so progress never drops.
    - Today's remaining budget = daily_hours - already_completed_hours.
      If that is 0 or negative, today is skipped automatically.
    """

    # ── 1. Wipe only UNCOMPLETED sessions (completed = permanent record) ──
    StudySession.query.filter(
        StudySession.user_id == user.id,
        StudySession.date > date.today(),
        StudySession.completed == False
    ).delete(synchronize_session=False)

    StudySession.query.filter(
        StudySession.user_id == user.id,
        StudySession.date == date.today(),
        StudySession.completed == False
    ).delete(synchronize_session=False)

    db.session.flush()

    # ── 2. Recalculate priority scores ────────────────────────────────────
    subjects = Subject.query.filter_by(user_id=user.id).all()
    for sub in subjects:
        calculate_priority(sub)
    db.session.commit()

    subjects = [sub for sub in subjects if sub.exam_date >= date.today()]
    subjects = sorted(subjects, key=lambda x: x.priority_score, reverse=True)

    if not subjects or user.daily_study_hours <= 0:
        return

    # ── 3. Schedule day by day ────────────────────────────────────────────
    for day_offset in range(7):
        current_date = date.today() + timedelta(days=day_offset)

        # Permanent completed sessions for this day
        completed_this_day = StudySession.query.filter_by(
            user_id=user.id,
            date=current_date,
            completed=True
        ).all()

        # Subject IDs already done today → never re-schedule them today
        completed_subject_ids = {s.subject_id for s in completed_this_day}

        if day_offset == 0:
            # FIX A: caller requested we skip today entirely
            if skip_today:
                continue

            already_done_hours = sum(
                (datetime.combine(current_date, s.end_time) -
                 datetime.combine(current_date, s.start_time)).total_seconds() / 3600
                for s in completed_this_day
            )
            remaining_hours = max(user.daily_study_hours - already_done_hours, 0)

            # FIX B: no time left today → skip rather than create 0-length sessions
            if remaining_hours <= 0:
                continue
        else:
            remaining_hours = user.daily_study_hours

        # Start time: right after last completed session, or default 17:00
        if day_offset == 0 and completed_this_day:
            last_end = max(s.end_time for s in completed_this_day)
            current_time = datetime.combine(current_date, last_end)
        else:
            current_time = datetime.combine(
                current_date, datetime.strptime("17:00", "%H:%M").time()
            )

        # Only schedule subjects not yet done today whose exam hasn't passed
        eligible = [
            sub for sub in subjects
            if sub.exam_date >= current_date
            and sub.id not in completed_subject_ids
        ]

        if not eligible:
            continue

        day_priority_total = sum(sub.priority_score for sub in eligible)
        if day_priority_total == 0:
            continue

        day_budget = remaining_hours

        for sub in eligible:
            if remaining_hours <= 0:
                break

            allocated = (sub.priority_score / day_priority_total) * day_budget
            allocated = min(allocated, remaining_hours)

            if allocated < 0.17:   # < ~10 minutes → skip
                continue

            session = StudySession(
                user_id=user.id,
                subject_id=sub.id,
                date=current_date,
                start_time=current_time.time(),
                end_time=(current_time + timedelta(hours=allocated)).time(),
            )
            db.session.add(session)
            current_time  += timedelta(hours=allocated)
            remaining_hours -= allocated

    db.session.commit()
