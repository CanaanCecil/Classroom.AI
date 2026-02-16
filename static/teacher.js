const joinCodeEl = document.getElementById('joinCode');
const gradeLevelEl = document.getElementById('gradeLevel');
const toneEl = document.getElementById('tone');
const topicLimitEl = document.getElementById('topicLimit');
const aiEnabledEl = document.getElementById('aiEnabled');
const customBadWordInputEl = document.getElementById('customBadWordInput');
const customBadWordsListEl = document.getElementById('customBadWordsList');
const saveBtn = document.getElementById('saveSettings');
const feedEl = document.getElementById('feed');
const analyticsEl = document.getElementById('analytics');
const exportLink = document.getElementById('exportLink');
const logoutBtn = document.getElementById('logoutBtn');
const blockedWordInputEl = document.getElementById('blockedWordInput');
const addBlockedWordBtn = document.getElementById('addBlockedWordBtn');
const blockedWordsListEl = document.getElementById('blockedWordsList');

let customBadWords = [];
let customBadWordsDirty = false;

async function logout() {
  await fetch('/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  window.location.href = '/teacher/login';
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function normalizeWord(value) {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function renderCustomBadWords() {
  if (!customBadWords.length) {
    customBadWordsListEl.innerHTML = '<small>No custom blocked words yet.</small>';
    return;
  }

  customBadWordsListEl.innerHTML = customBadWords.map((word) => `
    <span class="chip">
      ${escapeHtml(word)}
      <button type="button" class="chip-remove" aria-label="Remove ${escapeHtml(word)}" data-word="${escapeHtml(word)}">×</button>
    </span>
  `).join('');
}

function addCustomBadWord(value) {
  const normalized = normalizeWord(value);
  if (!normalized || customBadWords.includes(normalized)) {
    return;
  }
  customBadWords.push(normalized);
  customBadWords.sort((a, b) => a.localeCompare(b));
  customBadWordsDirty = true;
  renderCustomBadWords();
}

function removeCustomBadWord(word) {
  customBadWords = customBadWords.filter((current) => current !== word);
  customBadWordsDirty = true;
  renderCustomBadWords();
}

async function saveSettings() {
  const payload = {
    joinCode: joinCodeEl.value.trim().toUpperCase(),
    aiEnabled: aiEnabledEl.checked,
    gradeLevel: gradeLevelEl.value.trim(),
    tone: toneEl.value,
    topicLimit: topicLimitEl.value.trim(),
    customBadWords,
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
  customBadWordsDirty = false;
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


function renderBlockedWords(words) {
  if (!words.length) {
    blockedWordsListEl.innerHTML = '<small>No custom blocked words yet.</small>';
    return;
  }

  blockedWordsListEl.innerHTML = words.map((word) => `
    <div class="chip">
      <span>${escapeHtml(word)}</span>
      <button type="button" onclick="window.__removeBlockedWord('${escapeHtml(word)}')" aria-label="Remove ${escapeHtml(word)}">×</button>
    </div>
  `).join('');
}

async function refreshBlockedWords() {
  const joinCode = joinCodeEl.value.trim().toUpperCase();
  if (!joinCode) return;

  const res = await fetch(`/api/blocked-words?joinCode=${encodeURIComponent(joinCode)}`);
  if (res.status === 401) {
    window.location.href = '/teacher/login';
    return;
  }
  const data = await res.json();
  if (!res.ok) {
    blockedWordsListEl.innerHTML = `<small>${escapeHtml(data.error || 'Failed to load blocked words')}</small>`;
    return;
  }
  renderBlockedWords(data.blockedWords || []);
}

async function addBlockedWord() {
  const joinCode = joinCodeEl.value.trim().toUpperCase();
  const word = blockedWordInputEl.value.trim().toLowerCase();
  if (!joinCode || !word) return;

  const res = await fetch('/api/blocked-words/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ joinCode, word }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || 'Unable to add blocked word');
    return;
  }
  blockedWordInputEl.value = '';
  await refreshBlockedWords();
}

async function removeBlockedWord(word) {
  const joinCode = joinCodeEl.value.trim().toUpperCase();
  const res = await fetch('/api/blocked-words/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ joinCode, word }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || 'Unable to remove blocked word');
    return;
  }
  await refreshBlockedWords();
}

async function refreshAll() {
  const joinCode = joinCodeEl.value.trim().toUpperCase();
  if (!joinCode) return;

  exportLink.href = `/api/export?joinCode=${encodeURIComponent(joinCode)}`;

  const [interactionsRes, analyticsRes] = await Promise.all([
    fetch(`/api/interactions?joinCode=${encodeURIComponent(joinCode)}`),
    fetch(`/api/analytics?joinCode=${encodeURIComponent(joinCode)}`),
  ]);

  if (interactionsRes.status === 401 || analyticsRes.status === 401) {
    window.location.href = '/teacher/login';
    return;
  }

  const interactionsData = await interactionsRes.json();
  if (interactionsRes.ok) {
    const classroom = interactionsData.classroom || {};
    aiEnabledEl.checked = !!classroom.ai_enabled;
    gradeLevelEl.value = classroom.grade_level || '';
    toneEl.value = classroom.tone || 'simple';
    topicLimitEl.value = classroom.topic_limit || '';
    if (!customBadWordsDirty) {
      try {
        const parsedWords = JSON.parse(classroom.custom_bad_words || '[]');
        customBadWords = Array.isArray(parsedWords)
          ? parsedWords.map(normalizeWord).filter(Boolean)
          : [];
      } catch {
        customBadWords = [];
      }
      renderCustomBadWords();
    }
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

  await refreshBlockedWords();
}

window.__moderate = moderate;
window.__removeBlockedWord = removeBlockedWord;
saveBtn.addEventListener('click', saveSettings);
logoutBtn.addEventListener('click', logout);
addBlockedWordBtn.addEventListener('click', addBlockedWord);
blockedWordInputEl.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    addBlockedWord();
  }
customBadWordInputEl.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter') {
    return;
  }
  event.preventDefault();
  addCustomBadWord(customBadWordInputEl.value);
  customBadWordInputEl.value = '';
});
customBadWordsListEl.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  if (!target.classList.contains('chip-remove')) {
    return;
  }
  removeCustomBadWord(normalizeWord(target.dataset.word));
});
setInterval(refreshAll, 4000);
refreshAll();
