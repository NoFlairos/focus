const browserId = crypto.randomUUID();
const siteMetadata = new Map();
chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type !== "site_metadata" || !sender.tab || sender.frameId !== 0) return;
  let domain;
  try { domain = new URL(sender.url).hostname; } catch (_) { return; }
  if (domain !== message.domain) return;
  siteMetadata.set(sender.tab.id, {domain, name: String(message.name || "").slice(0, 120), identity: message.identity || {}});
  sendSnapshot();
});
chrome.tabs.onRemoved.addListener(id => siteMetadata.delete(id));
const HOST_NAME = "io.github.noflairos.focus_ratio";
let port = null;
let retryTimer = null;

function connect() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
    port.onMessage.addListener(handleResponse);
    port.onDisconnect.addListener(() => {
      const error = chrome.runtime.lastError;
      if (error) console.warn("Focus:", error.message);
      port = null;
      if (retryTimer) clearTimeout(retryTimer);
      retryTimer = setTimeout(connect, 3000);
    });
    sendSnapshot();
  } catch (_) {
    port = null;
    retryTimer = setTimeout(connect, 5000);
  }
}

function tabSite(tab) {
  try {
    const url = new URL(tab.url);
    if (!["http:", "https:"].includes(url.protocol)) return null;
    const saved = siteMetadata.get(tab.id);
    const metadata = saved?.domain === url.hostname ? saved : null;
    return {domain: url.hostname, site_name: metadata?.name || "", site_identity: metadata?.identity || null};
  } catch (_) { return null; }
}

async function sendSnapshot() {
  if (!port) return;
  try {
    const windows = await chrome.windows.getAll({ populate: true, windowTypes: ["normal"] });
    const visible = windows
      .filter(win => win.state !== "minimized")
      .map(win => {
        const tab = (win.tabs || []).find(candidate => candidate.active);
        const site = tab && tabSite(tab);
        if (!site) return null;
        return {
          id: win.id,
          tab_id: tab.id,
          state: win.state || "normal",
          title: tab.title || win.title || "",
          ...site,
        };
      })
      .filter(Boolean);
    const metadata = new Map();
    for (const win of windows) {
      for (const tab of win.tabs || []) {
        const site = tabSite(tab);
        if (site?.site_identity) metadata.set(site.domain, site);
      }
    }
    // Background tabs provide service identity only, never activity or close targets.
    port.postMessage({ windows: visible, browser_id: browserId, site_metadata: [...metadata.values()] });
  } catch (_) {
    // A browser shutdown or permissions change is recovered on the next tick.
  }
}

async function handleResponse(message) {
  const blocked = (message && message.blocked_domains) || [];
  const allowedTabs = new Set(message?.blocked_tab_ids || []);
  if (!blocked.length || !allowedTabs.size) return;
  try {
    const tabs = await chrome.tabs.query({});
    const blockedTabs = tabs.filter(tab => {
      if (!tab.id || !tab.url || !tab.active || !allowedTabs.has(tab.id)) return false;
      try {
        const host = new URL(tab.url).hostname.toLowerCase().replace(/^(www|m)\./, "");
        return blocked.some(domain => host === domain);
      } catch (_) { return false; }
    });
    for (const tab of blockedTabs) chrome.tabs.remove(tab.id);
  } catch (_) {}
}

chrome.windows.onCreated.addListener(sendSnapshot);
chrome.windows.onRemoved.addListener(sendSnapshot);
chrome.windows.onFocusChanged.addListener(sendSnapshot);
chrome.tabs.onActivated.addListener(sendSnapshot);
chrome.tabs.onUpdated.addListener((_, changeInfo) => {
  if (changeInfo.url || changeInfo.status === "complete") sendSnapshot();
});
setInterval(sendSnapshot, 1000);
connect();
