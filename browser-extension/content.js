// Content script for Sift browser extension
// This script runs on supported pages to provide visual feedback

// Check if current page is a supported audio/video source
function checkPageSupport() {
  // SiftPlatforms comes from platforms.js, injected before this script.
  const match = SiftPlatforms.detect(window.location.href);
  return match ? match.type : null;
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
