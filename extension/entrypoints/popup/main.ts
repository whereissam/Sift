import { browser, storage } from '#imports';
import { detectPlatform, type PlatformMatch } from '../../utils/platforms';
import {
  apiKeyDecision,
  buildAddUrl,
  DEFAULT_SERVER,
  isInsecureRemoteServer,
  normalizeServerUrl,
  originPattern,
  serverOrigin,
  type CaptureAction,
} from '../../utils/server';

// Origins the user explicitly allowed to receive the API key over plain http.
// Device-local on purpose: consent to cleartext should not roam via sync.
const INSECURE_ORIGINS_KEY = 'local:insecureKeyOrigins';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

const statusEl = $<HTMLDivElement>('status');
const statusTextEl = $<HTMLSpanElement>('status-text');
const urlDisplayEl = $<HTMLDivElement>('url-display');
const transcribeBtn = $<HTMLButtonElement>('transcribe-btn');
const downloadBtn = $<HTMLButtonElement>('download-btn');
const messageEl = $<HTMLDivElement>('message');
const serverUrlInput = $<HTMLInputElement>('server-url');
const apiKeyInput = $<HTMLInputElement>('api-key');
const saveBtn = $<HTMLButtonElement>('save-btn');
const openUiLink = $<HTMLAnchorElement>('open-ui');
const insecureWarningEl = $<HTMLDivElement>('insecure-key-warning');
const insecureConfirmInput = $<HTMLInputElement>('insecure-key-confirm');
const insecureOriginEl = $<HTMLSpanElement>('insecure-origin');

let currentUrl = '';
let currentMatch: PlatformMatch | null = null;
let serverUrl = DEFAULT_SERVER;
let apiKey = '';
let allowedInsecureOrigins: string[] = [];

/** Show the cleartext-key warning whenever a key is set for a remote http server. */
function renderKeyWarning() {
  const show = Boolean(apiKey) && isInsecureRemoteServer(serverUrl);
  insecureWarningEl.hidden = !show;
  if (!show) return;
  const origin = serverOrigin(serverUrl);
  insecureOriginEl.textContent = origin ?? serverUrl;
  insecureConfirmInput.disabled = !origin || origin === 'null';
  insecureConfirmInput.checked = apiKeyDecision(serverUrl, apiKey, allowedInsecureOrigins) === 'send';
}

async function init() {
  serverUrl = normalizeServerUrl((await storage.getItem<string>('sync:serverUrl')) || DEFAULT_SERVER);
  apiKey = (await storage.getItem<string>('sync:apiKey')) || '';
  allowedInsecureOrigins = (await storage.getItem<string[]>(INSECURE_ORIGINS_KEY)) || [];
  serverUrlInput.value = serverUrl;
  apiKeyInput.value = apiKey;
  openUiLink.href = serverUrl;
  renderKeyWarning();

  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  currentUrl = tab?.url || '';
  currentMatch = detectPlatform(currentUrl);

  if (currentMatch) {
    statusEl.className = 'status supported';
    statusTextEl.textContent = `Supported: ${currentMatch.name}`;
    urlDisplayEl.textContent = currentUrl;
    urlDisplayEl.hidden = false;
    transcribeBtn.disabled = false;
    downloadBtn.disabled = false;
  } else {
    statusEl.className = 'status unsupported';
    statusTextEl.textContent = 'Not a supported page';
    transcribeBtn.disabled = true;
    downloadBtn.disabled = true;
  }
}

function showMessage(text: string, isError = false) {
  messageEl.textContent = text;
  messageEl.className = `message ${isError ? 'error' : 'success'}`;
  messageEl.hidden = false;
  setTimeout(() => (messageEl.hidden = true), 5000);
}

/** Ensure we hold host permission for the (possibly remote) server origin. */
async function ensureServerPermission(): Promise<boolean> {
  const origins = [originPattern(serverUrl)];
  if (await browser.permissions.contains({ origins })) return true;
  try {
    return await browser.permissions.request({ origins });
  } catch {
    return false;
  }
}

async function sendToServer(action: CaptureAction) {
  if (!currentUrl || !currentMatch) return;

  const keyDecision = apiKeyDecision(serverUrl, apiKey, allowedInsecureOrigins);
  if (keyDecision === 'needs-confirmation') {
    renderKeyWarning();
    showMessage(
      'Not sent: your API key would travel unencrypted over http. Switch to https, or confirm below to send it anyway.',
      true,
    );
    return;
  }

  if (!(await ensureServerPermission())) {
    showMessage(`Permission to reach ${serverUrl} was denied.`, true);
    return;
  }

  try {
    const headers: Record<string, string> = {};
    if (keyDecision === 'send') headers['X-API-Key'] = apiKey;

    const response = await fetch(buildAddUrl(serverUrl, currentUrl, action), { headers });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Server error: ${response.status}`);
    }

    const data = await response.json();
    showMessage(`Added to queue! Job ${data.job_id}`);
    await browser.tabs.create({ url: serverUrl });
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    if (msg.includes('Failed to fetch')) {
      showMessage(`Cannot connect to ${serverUrl}. Is Sift running?`, true);
    } else {
      showMessage(msg, true);
    }
  }
}

transcribeBtn.addEventListener('click', () => sendToServer('transcribe'));
downloadBtn.addEventListener('click', () => sendToServer('download'));

saveBtn.addEventListener('click', async () => {
  serverUrl = normalizeServerUrl(serverUrlInput.value);
  apiKey = apiKeyInput.value.trim();
  await storage.setItems([
    { key: 'sync:serverUrl', value: serverUrl },
    { key: 'sync:apiKey', value: apiKey },
  ]);
  openUiLink.href = serverUrl;
  renderKeyWarning();
  await ensureServerPermission();
  showMessage('Settings saved!');
});

insecureConfirmInput.addEventListener('change', async () => {
  const origin = serverOrigin(serverUrl);
  if (!origin || origin === 'null') return;
  const others = allowedInsecureOrigins.filter((o) => o !== origin);
  allowedInsecureOrigins = insecureConfirmInput.checked ? [...others, origin] : others;
  await storage.setItem(INSECURE_ORIGINS_KEY, allowedInsecureOrigins);
});

openUiLink.addEventListener('click', (e) => {
  e.preventDefault();
  browser.tabs.create({ url: serverUrl });
});

init();
