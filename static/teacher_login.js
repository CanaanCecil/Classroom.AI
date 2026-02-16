const userEl = document.getElementById('username');
const passEl = document.getElementById('password');
const loginBtn = document.getElementById('loginBtn');
const errorEl = document.getElementById('errorMsg');

async function login() {
  errorEl.textContent = '';
  loginBtn.disabled = true;
  try {
    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: userEl.value.trim(), password: passEl.value }),
    });
    const data = await res.json();
    if (!res.ok) {
      errorEl.textContent = data.error || 'Login failed';
      return;
    }
    window.location.href = '/teacher';
  } catch (err) {
    errorEl.textContent = 'Network error during login.';
  } finally {
    loginBtn.disabled = false;
  }
}

loginBtn.addEventListener('click', login);
passEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') login();
});
