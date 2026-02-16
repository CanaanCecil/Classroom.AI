const joinCodeEl = document.getElementById('joinCode');
const gradeLevelEl = document.getElementById('gradeLevel');
const toneEl = document.getElementById('tone');
const topicLimitEl = document.getElementById('topicLimit');
const aiEnabledEl = document.getElementById('aiEnabled');
const saveBtn = document.getElementById('saveSettings');
const feedEl = document.getElementById('feed');
const analyticsEl = document.getElementById('analytics');
const exportLink = document.getElementById('exportLink');

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function saveSettings() {
  const payload = {
    joinCode: joinCodeEl.value.trim().toUpperCase(),
    aiEnabled: aiEnabledEl.checked,
    gradeLevel: gradeLevelEl.value.trim(),
    tone: toneEl.value,
    topicLimit: topicLimitEl.value.trim(),
  };

  const res = await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || 'Unable to save settings');
    return;
  }
  await refreshAll();
}

async function moderate(interactionId, action) {
  const res = await fetch('/api/moderate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ interactionId, action }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || 'Moderation action failed');
    return;
  }
  await refreshAll();
}

function renderFeed(interactions) {
  if (!interactions.length) {
    feedEl.innerHTML = '<small>No interactions yet.</small>';
    return;
  }

  feedEl.innerHTML = interactions.map((i) => {
    const status = i.moderation_status === 'hidden'
      ? '<span class="badge warn">hidden</span>'
      : '<span class="badge ok">visible</span>';
    const flagged = i.is_flagged ? '<span class="badge warn">flagged</span>' : '';
    const blocked = i.is_blocked ? '<span class="badge warn">safety-blocked</span>' : '';

    return `
      <div class="item">
        <small>${new Date(i.created_at).toLocaleString()} • ${i.is_anonymous ? 'Anonymous' : escapeHtml(i.student_name || 'Student')}</small>
        <div>${status}${flagged}${blocked}</div>
        <p><strong>Q:</strong> ${escapeHtml(i.question)}</p>
        <p><strong>A:</strong> ${escapeHtml(i.ai_response)}</p>
        <div class="actions">
          <button onclick="window.__moderate(${i.id}, 'approve')">Approve</button>
          <button onclick="window.__moderate(${i.id}, 'hide')">Hide</button>
          <button onclick="window.__moderate(${i.id}, 'flag')">Flag inaccurate</button>
          <button onclick="window.__moderate(${i.id}, 'broadcast')">Broadcast</button>
        </div>
      </div>
    `;
  }).join('');
}

function renderAnalytics(data) {
  const topConcepts = data.topConcepts || [];
  const support = data.supportSignals || [];

  analyticsEl.innerHTML = `
    <div class="kpi"><strong>Total Questions:</strong> ${data.totalQuestions || 0}</div>
    <h4>Most Asked Concepts</h4>
    <ul>${topConcepts.map(([word, count]) => `<li>${escapeHtml(word)} (${count})</li>`).join('') || '<li>None</li>'}</ul>
    <h4>Students Who May Need Support</h4>
    <ul>${support.map((s) => `<li>${escapeHtml(s.student)} (${s.questionCount} questions)</li>`).join('') || '<li>None</li>'}</ul>
  `;
}

async function refreshAll() {
  const joinCode = joinCodeEl.value.trim().toUpperCase();
  if (!joinCode) return;

  exportLink.href = `/api/export?joinCode=${encodeURIComponent(joinCode)}`;

  const [interactionsRes, analyticsRes] = await Promise.all([
    fetch(`/api/interactions?joinCode=${encodeURIComponent(joinCode)}`),
    fetch(`/api/analytics?joinCode=${encodeURIComponent(joinCode)}`),
  ]);

  const interactionsData = await interactionsRes.json();
  if (interactionsRes.ok) {
    const classroom = interactionsData.classroom || {};
    aiEnabledEl.checked = !!classroom.ai_enabled;
    gradeLevelEl.value = classroom.grade_level || '';
    toneEl.value = classroom.tone || 'simple';
    topicLimitEl.value = classroom.topic_limit || '';
    renderFeed(interactionsData.interactions || []);
  } else {
    feedEl.innerHTML = `<small>${escapeHtml(interactionsData.error || 'Failed to load interactions')}</small>`;
  }

  const analyticsData = await analyticsRes.json();
  if (analyticsRes.ok) {
    renderAnalytics(analyticsData);
  } else {
    analyticsEl.innerHTML = `<small>${escapeHtml(analyticsData.error || 'Failed to load analytics')}</small>`;
  }
}

window.__moderate = moderate;
saveBtn.addEventListener('click', saveSettings);
setInterval(refreshAll, 4000);
refreshAll();
