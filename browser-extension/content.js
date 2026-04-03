// Content script for Sift browser extension
// This script runs on supported pages to provide visual feedback

// Check if current page is a supported audio/video source
function checkPageSupport() {
  const url = window.location.href;

  const patterns = [
    { pattern: /x\.com\/i\/spaces\//, type: 'x_spaces' },
    { pattern: /twitter\.com\/i\/spaces\//, type: 'x_spaces' },
    { pattern: /x\.com\/\w+\/status\//, type: 'x_video' },
    { pattern: /twitter\.com\/\w+\/status\//, type: 'x_video' },
    { pattern: /youtube\.com\/watch/, type: 'youtube' },
    { pattern: /podcasts\.apple\.com\/.*\/podcast\//, type: 'apple_podcasts' },
    { pattern: /open\.spotify\.com\/episode\//, type: 'spotify' },
    { pattern: /xiaoyuzhoufm\.com\/episode\//, type: 'xiaoyuzhou' },
  ];

  for (const p of patterns) {
    if (p.pattern.test(url)) {
      return p.type;
    }
  }
  return null;
}

// Send message to background script with page info
function notifyBackground() {
  const pageType = checkPageSupport();
  if (pageType) {
    chrome.runtime.sendMessage({
      type: 'PAGE_SUPPORTED',
      pageType: pageType,
      url: window.location.href,
    });
  }
}

// Run on page load
notifyBackground();

// Also run when URL changes (for SPAs like YouTube, X)
let lastUrl = window.location.href;
const observer = new MutationObserver(() => {
  if (window.location.href !== lastUrl) {
    lastUrl = window.location.href;
    notifyBackground();
  }
});

observer.observe(document.body, { childList: true, subtree: true });
