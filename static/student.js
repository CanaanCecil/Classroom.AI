const joinCodeEl = document.getElementById('joinCode');
const studentNameEl = document.getElementById('studentName');
const anonymousEl = document.getElementById('anonymous');
const questionEl = document.getElementById('question');
const askBtn = document.getElementById('askBtn');
const responseBox = document.getElementById('responseBox');
const broadcastsEl = document.getElementById('broadcasts');
const filterWarningEl = document.getElementById('filterWarning');

let blockedWords = [];
let filterIntervalId = null;

function normalizeWord(value) {
  return String(value || '').trim().toLowerCase();
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function findBlockedWord(text) {
  const lowered = String(text || '').toLowerCase();
  for (const word of blockedWords) {
    if (word && lowered.includes(word)) {
      return word;
    }
  }
  return '';
}

function sanitizeQuestionText() {
  const current = questionEl.value;
  let sanitized = current;

  for (const word of blockedWords) {
    if (!word) {
      continue;
    }
    const pattern = new RegExp(escapeRegExp(word), 'gi');
    sanitized = sanitized.replace(pattern, '*'.repeat(word.length));
  }

  if (sanitized !== current) {
    questionEl.value = sanitized;
    filterWarningEl.textContent = 'Inappropriate words were removed from your message.';
  }

  const hasBlocked = !!findBlockedWord(questionEl.value);
  askBtn.disabled = hasBlocked;
  if (hasBlocked) {
    filterWarningEl.textContent = 'Please remove inappropriate words before sending.';
  } else if (filterWarningEl.textContent === 'Please remove inappropriate words before sending.') {
    filterWarningEl.textContent = '';
  }
}

async function loadFilterWords() {
  const joinCode = joinCodeEl.value.trim().toUpperCase();
  if (!joinCode) {
    blockedWords = [];
    return;
  }

  try {
    const res = await fetch(`/api/filter-words?joinCode=${encodeURIComponent(joinCode)}`);
    const data = await res.json();
    if (!res.ok) {
      blockedWords = [];
      return;
    }
    blockedWords = Array.isArray(data.words)
      ? data.words.map(normalizeWord).filter(Boolean)
      : [];
    sanitizeQuestionText();
  } catch {
    blockedWords = [];
  }
}

function startFilterRefresh() {
  if (filterIntervalId) {
    clearInterval(filterIntervalId);
  }
  filterIntervalId = setInterval(loadFilterWords, 5000);
}

async function askQuestion() {
  const payload = {
    joinCode: joinCodeEl.value.trim().toUpperCase(),
    studentName: studentNameEl.value.trim(),
    anonymous: anonymousEl.checked,
    question: questionEl.value.trim(),
  };

  if (!payload.joinCode || !payload.question) {
    responseBox.textContent = 'Please enter a join code and a question.';
    return;
  }

  const matchedWord = findBlockedWord(payload.question);
  if (matchedWord) {
    filterWarningEl.textContent = `That message includes blocked language (${matchedWord}). Please rephrase.`;
    askBtn.disabled = false;
    return;
  }

  askBtn.disabled = true;
  responseBox.textContent = 'Thinking...';

  try {
    const res = await fetch('/api/question', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      responseBox.textContent = data.error || 'Unable to get AI response.';
      return;
    }
    responseBox.textContent = data.response;
  } catch (err) {
    responseBox.textContent = 'Network error while sending question.';
  } finally {
    askBtn.disabled = false;
  }
}

function renderBroadcasts(list) {
  if (!list.length) {
    broadcastsEl.innerHTML = '<small>No teacher broadcasts yet.</small>';
    return;
  }

  broadcastsEl.innerHTML = list.map((b) => `
    <div class="item">
      <small>${new Date(b.created_at).toLocaleString()}</small>
      <p><strong>Q:</strong> ${b.question}</p>
      <p><strong>A:</strong> ${b.ai_response}</p>
    </div>
  `).join('');
}

async function refreshBroadcasts() {
  const joinCode = joinCodeEl.value.trim().toUpperCase();
  if (!joinCode) return;
  try {
    const res = await fetch(`/api/broadcasts?joinCode=${encodeURIComponent(joinCode)}`);
    const data = await res.json();
    if (res.ok) renderBroadcasts(data.broadcasts || []);
  } catch (err) {
    // no-op
  }
}

askBtn.addEventListener('click', askQuestion);
questionEl.addEventListener('input', sanitizeQuestionText);
joinCodeEl.addEventListener('change', async () => {
  await loadFilterWords();
  await refreshBroadcasts();
});
setInterval(refreshBroadcasts, 5000);
startFilterRefresh();
loadFilterWords();
refreshBroadcasts();
