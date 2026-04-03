// Background service worker for Sift browser extension

// Set badge when on supported pages
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'PAGE_SUPPORTED') {
    // Show badge on the extension icon
    chrome.action.setBadgeText({
      text: '!',
      tabId: sender.tab?.id,
    });
    chrome.action.setBadgeBackgroundColor({
      color: '#6366f1',
      tabId: sender.tab?.id,
    });
  }
});

// Clear badge when navigating away from supported pages
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'loading') {
    chrome.action.setBadgeText({
      text: '',
      tabId: tabId,
    });
  }
});

// Handle extension install/update
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    // Set default server URL
    chrome.storage.sync.set({ serverUrl: 'http://localhost:8000' });
  }
});
