const joinCodeEl = document.getElementById('joinCode');
const studentNameEl = document.getElementById('studentName');
const anonymousEl = document.getElementById('anonymous');
const questionEl = document.getElementById('question');
const askBtn = document.getElementById('askBtn');
const responseBox = document.getElementById('responseBox');
const broadcastsEl = document.getElementById('broadcasts');

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
    const res = await fetch(`/api/interactions?joinCode=${encodeURIComponent(joinCode)}`);
    const data = await res.json();
    if (res.ok) renderBroadcasts(data.broadcasts || []);
  } catch (err) {
    // no-op
  }
}

askBtn.addEventListener('click', askQuestion);
setInterval(refreshBroadcasts, 5000);
refreshBroadcasts();
