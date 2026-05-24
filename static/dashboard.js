/**
 * dashboard.js — Dynamic timetable & stats refresh
 *
 * Place this file at: static/dashboard.js
 * Include in dashboard.html:
 *   <script src="{{ url_for('static', filename='dashboard.js') }}"></script>
 *
 * What it does:
 *  1. Polls /api/dashboard_stats every 30s to keep progress bar & session
 *     list current without a page reload.
 *  2. Intercepts the "complete session" button to mark via AJAX and
 *     immediately refresh stats + session list.
 *  3. Intercepts the "add subject" form submission (on add_subject page) to
 *     submit via AJAX and then refresh the dashboard in place so the new
 *     session appears instantly — no redirect needed.
 *  4. Renders the 7-day weekly timetable from /api/weekly_plan.
 */

/*  Helpers  */
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function difficultyBadgeClass(diff) {
  const map = { Hard: 'badge-hard', Medium: 'badge-medium', Weak: 'badge-weak', Easy: 'badge-weak' };
  return map[diff] || 'badge-orange';
}

function formatDate(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

function isToday(dateStr) {
  return dateStr === new Date().toISOString().split('T')[0];
}

/*  Render today's session list  */
function renderSessions(sessions) {
  const container = $('#session-list');
  if (!container) return;

  if (sessions.length === 0) {
    container.innerHTML = `
      <div class="text-center py-4 text-muted">
        <div style="font-size:2rem"></div>
        <p class="mt-2 mb-0 fw-600">All done for today!</p>
      </div>`;
    return;
  }

  container.innerHTML = sessions.map(s => {
    const diffClass = difficultyBadgeClass(s.difficulty);
    return `<div style="display:grid; grid-template-columns:110px 1fr auto auto; align-items:center; gap:1rem; padding:0.9rem 1rem; border-radius:8px; border:1.5px solid ${s.completed ? '#B7EFC5' : 'var(--border-light)'}; background:${s.completed ? 'var(--success-bg)' : 'var(--white)'}; margin-bottom:0.65rem;" class="animate-in" data-id="${s.id}">
      <span style="font-family:var(--font-mono); font-size:0.75rem; color:var(--orange); background:var(--orange-pale); padding:0.25rem 0.5rem; border-radius:5px; text-align:center; white-space:nowrap;">${s.start_time} - ${s.end_time}</span>
      <span style="font-weight:600; font-size:0.9rem; ${s.completed ? 'text-decoration:line-through; color:var(--text-muted);' : ''}">${s.subject}</span>
      <span class="${diffClass}" style="white-space:nowrap; font-size:0.75rem; padding:0.3em 0.6em; border-radius:6px; font-weight:600;">${s.difficulty}</span>
      ${!s.completed ? `<button class="btn btn-success btn-sm complete-btn" data-id="${s.id}" style="font-size:0.78rem; padding:0.25rem 0.75rem; white-space:nowrap;">Done</button>` : `<span style="font-size:0.78rem; background:var(--success-bg); color:var(--success); padding:0.25rem 0.65rem; border-radius:6px; font-weight:600; white-space:nowrap;">Done</span>`}
    </div>`;
  }).join('');
}

/*  Render progress stats  */
function renderStats(data) {
  const setValue = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

  setValue('stat-total',     data.total);
  setValue('stat-completed', data.completed);
  setValue('stat-pending',   data.pending);
  setValue('stat-pct',       data.progress_pct + '%');

  const bar = $('#progress-bar');
  if (bar) {
    bar.style.width = data.progress_pct + '%';
    bar.setAttribute('aria-valuenow', data.progress_pct);
  }

  const pctLabel = $('#progress-label');
  if (pctLabel) pctLabel.textContent = data.progress_pct + '%';
}

/*  Render priority queue  */
function renderPriorityQueue(items) {
  const container = $('#priority-queue');
  if (!container) return;

  if (items.length === 0) {
    container.innerHTML = `<p class="text-muted small text-center py-3">No upcoming subjects.</p>`;
    return;
  }

  container.innerHTML = items.slice(0, 8).map((item, i) => `
    <div class="priority-item animate-in">
      <span style="font-size:1rem">${['','','','','','','',''][i] || ''}</span>
      <div class="flex-fill">
        <div class="fw-600 small">${item.name}</div>
        <div class="text-muted" style="font-size:0.75rem">Exam: ${item.exam_date}</div>
      </div>
      <span class="badge ${difficultyBadgeClass(item.difficulty)}">${item.difficulty}</span>
      <span class="priority-score">${item.score}</span>
    </div>
  `).join('');
}

/*  Fetch and refresh dashboard  */
async function refreshDashboard() {
  try {
    const res  = await fetch('/api/dashboard_stats', { credentials: 'same-origin' });
    if (!res.ok) return;
    const data = await res.json();
    renderStats(data);
    renderSessions(data.sessions);
    renderPriorityQueue(data.priority_queue);
  } catch (e) {
    console.warn('Dashboard refresh failed:', e);
  }
}

/*  Fetch and render 7-day weekly plan  */
async function refreshWeeklyPlan() {
  const container = $('#weekly-plan');
  if (!container) return;

  try {
    const res  = await fetch('/api/weekly_plan', { credentials: 'same-origin' });
    if (!res.ok) return;
    const data = await res.json();
    renderWeeklyPlan(data.days, container);
  } catch (e) {
    console.warn('Weekly plan refresh failed:', e);
  }
}

function renderWeeklyPlan(days, container) {
  const entries = Object.entries(days).sort(([a], [b]) => a.localeCompare(b));

  if (entries.length === 0) {
    container.innerHTML = `<p class="text-muted text-center py-4">No sessions scheduled yet.</p>`;
    return;
  }

  container.innerHTML = entries.map(([dateStr, sessions]) => {
    const today = isToday(dateStr);
    // FIX 3: Show ONLY one date label — "Today" or the formatted date, never both
    const dayLabel = today ? 'Today' : formatDate(dateStr);

    const sessionsHtml = sessions.map(s => `
      <div style="
        display:grid;
        grid-template-columns: 110px 1fr auto auto;
        align-items:center;
        gap:1rem;
        padding:0.85rem 1rem;
        border-radius:8px;
        border:1.5px solid ${s.completed ? '#B7EFC5' : 'var(--border-light)'};
        background:${s.completed ? 'var(--success-bg)' : 'var(--white)'};
        margin:0.5rem 0.75rem;
      ">
        <span style="font-family:var(--font-mono); font-size:0.75rem; color:var(--orange); background:var(--orange-pale); padding:0.25rem 0.5rem; border-radius:5px; text-align:center; white-space:nowrap;">
          ${s.start_time} – ${s.end_time}
        </span>
        <span style="font-weight:600; font-size:0.9rem; ${s.completed ? 'text-decoration:line-through; color:var(--text-muted);' : ''}">
          ${s.subject}
        </span>
        <span class="${difficultyBadgeClass(s.difficulty)}" style="white-space:nowrap; font-size:0.75rem; padding:0.3em 0.6em; border-radius:6px; font-weight:600;">
          ${s.difficulty}
        </span>
        ${s.completed
          ? `<span style="font-size:0.78rem; background:var(--success-bg); color:var(--success); padding:0.25rem 0.65rem; border-radius:6px; font-weight:600; white-space:nowrap;">Done</span>`
          : `<span></span>`}
      </div>
    `).join('');

    return `
      <div class="day-card animate-in" style="margin-bottom:0.75rem;">
        <div class="day-header ${today ? 'today-header' : ''}">
          <span style="font-weight:700;">${dayLabel}</span>
        </div>
        <div style="padding:0.4rem 0 0.5rem;">${sessionsHtml}</div>
      </div>`;
  }).join('');
}

/*  Complete session (AJAX)  */
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('.complete-btn');
  if (!btn) return;

  const sessionId = btn.dataset.id;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';

  try {
    const res = await fetch(`/complete_session/${sessionId}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });
    if (res.ok) {
      await refreshDashboard();
      await refreshWeeklyPlan();
    }
  } catch (e) {
    console.error('Complete session failed:', e);
    btn.disabled = false;
    btn.innerHTML = ' Done';
  }
});

/*  Add Subject form (AJAX on add_subject page)  */
(function initAddSubjectForm() {
  const form = document.getElementById('add-subject-form');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const submitBtn = form.querySelector('[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner" style="vertical-align:middle"></span> Adding…';

    const body = new FormData(form);

    try {
      const res = await fetch(form.action || '/add_subject', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body,
      });

      if (res.ok) {
        const data = await res.json();
        if (data.status === 'ok') {
          // Redirect to dashboard and it will auto-show updated plan
          window.location.href = '/dashboard';
        } else {
          window.location.href = '/dashboard';
        }
      } else {
        // Server error — fall back to normal form submit
        form.submit();
      }
    } catch (err) {
      console.error('Add subject AJAX failed, falling back:', err);
      form.submit();
    }
  });
})();

/*  Auto-poll every 30 seconds  */
document.addEventListener('DOMContentLoaded', () => {
  // Initial render from server-side HTML is already there; just start polling.
  // Also do an immediate refresh to catch any changes since page load.
  if (document.getElementById('session-list')) {
    refreshDashboard();
    refreshWeeklyPlan();
    setInterval(() => {
      refreshDashboard();
      refreshWeeklyPlan();
    }, 30_000);
  }
});
