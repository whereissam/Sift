// Platform detection shared by popup.js and content.js (loaded before each).
// The URL is parsed and its hostname matched exactly or as a subdomain before
// any path pattern is applied, so platform look-alikes in the query, fragment,
// userinfo, or a suffix domain (e.g. https://evil.example/?x=x.com/i/spaces/1,
// https://x.com@evil.example/, https://x.com.evil.example/) are rejected.

// eslint-disable-next-line no-unused-vars
var SiftPlatforms = (function () {
  var X_HOSTS = ['x.com', 'twitter.com'];

  // Order matters: more specific patterns (X Spaces) before generic ones.
  var PATTERNS = [
    { hosts: X_HOSTS, path: /^\/i\/spaces\//i, type: 'x_spaces', name: 'X Space' },
    { hosts: X_HOSTS, path: /^\/\w+\/status\//i, type: 'x_video', name: 'X Video' },
    { hosts: ['youtube.com'], path: /^\/watch(?:[/?]|$)/i, type: 'youtube', name: 'YouTube Video' },
    { hosts: ['youtu.be'], path: /^\/[\w-]+/i, type: 'youtube', name: 'YouTube Video' },
    { hosts: ['podcasts.apple.com'], path: /^\/.*\/podcast\//i, type: 'apple_podcasts', name: 'Apple Podcast' },
    { hosts: ['open.spotify.com'], path: /^\/(?:intl-[\w-]+\/)?episode\//i, type: 'spotify', name: 'Spotify Episode' },
    { hosts: ['xiaoyuzhoufm.com'], path: /^\/episode\//i, type: 'xiaoyuzhou', name: '小宇宙 Episode' },
  ];

  function hostMatches(hostname, domain) {
    var h = hostname.toLowerCase();
    return h === domain || h.slice(-(domain.length + 1)) === '.' + domain;
  }

  function detect(url) {
    var parsed;
    try {
      parsed = new URL(url);
    } catch (e) {
      return null;
    }
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;

    var target = parsed.pathname + parsed.search;
    for (var i = 0; i < PATTERNS.length; i++) {
      var p = PATTERNS[i];
      var hostOk = p.hosts.some(function (d) {
        return hostMatches(parsed.hostname, d);
      });
      if (hostOk && p.path.test(target)) {
        return { type: p.type, name: p.name };
      }
    }
    return null;
  }

  return { detect: detect, hostMatches: hostMatches };
})();
