// Platform detection lives in platforms.js (loaded first by popup.html).

// Default server URL
const DEFAULT_SERVER = 'http://localhost:8000';

// DOM elements
const statusEl = document.getElementById('status');
const statusTextEl = document.getElementById('status-text');
const urlDisplayEl = document.getElementById('url-display');
const transcribeBtn = document.getElementById('transcribe-btn');
const downloadBtn = document.getElementById('download-btn');
const messageEl = document.getElementById('message');
const serverUrlInput = document.getElementById('server-url');
const saveBtn = document.getElementById('save-btn');
const openUiLink = document.getElementById('open-ui');

let currentUrl = '';
let currentType = null;
let serverUrl = DEFAULT_SERVER;

// Initialize
async function init() {
  // Load saved server URL
  const stored = await chrome.storage.sync.get(['serverUrl']);
  serverUrl = stored.serverUrl || DEFAULT_SERVER;
  serverUrlInput.value = serverUrl;
  openUiLink.href = serverUrl;

  // Get current tab URL
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentUrl = tab?.url || '';

  // Check if URL is supported
  const match = checkSupported(currentUrl);

  if (match) {
    currentType = match.type;
    statusEl.className = 'status supported';
    statusTextEl.textContent = `Supported: ${match.name}`;
    urlDisplayEl.textContent = currentUrl;
    urlDisplayEl.style.display = 'block';
    transcribeBtn.disabled = false;
    downloadBtn.disabled = false;
  } else {
    statusEl.className = 'status unsupported';
    statusTextEl.textContent = 'Not a supported page';
    transcribeBtn.disabled = true;
    downloadBtn.disabled = true;
  }
}

function checkSupported(url) {
  return SiftPlatforms.detect(url);
}

function showMessage(text, isError = false) {
  messageEl.textContent = text;
  messageEl.className = `message ${isError ? 'error' : 'success'}`;
  messageEl.style.display = 'block';
  setTimeout(() => {
    messageEl.style.display = 'none';
  }, 5000);
}

async function sendToServer(action) {
  if (!currentUrl) return;

  const params = new URLSearchParams({
    url: currentUrl,
    action: action,
  });

  try {
    const response = await fetch(`${serverUrl}/api/add?${params}`);

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `Server error: ${response.status}`);
    }

    const data = await response.json();
    showMessage(`Added to queue! Job ID: ${data.job_id}`);

    // Open the web UI to show progress
    chrome.tabs.create({ url: serverUrl });
  } catch (error) {
    if (error.message.includes('Failed to fetch')) {
      showMessage(`Cannot connect to ${serverUrl}. Is Sift running?`, true);
    } else {
      showMessage(error.message, true);
    }
  }
}

// Event listeners
transcribeBtn.addEventListener('click', () => sendToServer('transcribe'));
downloadBtn.addEventListener('click', () => sendToServer('download'));

saveBtn.addEventListener('click', async () => {
  serverUrl = serverUrlInput.value.replace(/\/$/, ''); // Remove trailing slash
  await chrome.storage.sync.set({ serverUrl });
  openUiLink.href = serverUrl;
  showMessage('Server URL saved!');
});

openUiLink.addEventListener('click', (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: serverUrl });
});

// Initialize on load
init();
