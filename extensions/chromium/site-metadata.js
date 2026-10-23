// Read service identity only; document titles can contain private page details.
const MIN_REPORT_MS = 2000;  // a page rewriting its metadata cannot flood the helper
let lastReport = "";
let lastReportAt = -Infinity;
let reportTimer;

function siteIdentity() {
  const application = document.querySelector('meta[name="application-name"]');
  const applicationName = (application?.content || "").replace(/\s+/g, " ").trim().slice(0, 120);
  const metadata = application
    || document.querySelector('meta[property="og:site_name"]');
  const name = (metadata?.content || "").replace(/\s+/g, " ").trim().slice(0, 120);
  let manifest = "";
  const link = document.querySelector('link[rel~="manifest"]');
  try {
    const url = new URL(link?.href || "", location.href);
    url.search = "";
    url.hash = "";
    if (link && ["http:", "https:"].includes(url.protocol)
        && !url.username && !url.password && url.href.length <= 2048
        && (url.hostname === location.hostname || location.hostname.endsWith("." + url.hostname))) {
      manifest = url.href;
    }
  } catch (_) {}
  // Sent even when empty: "no declaration" lets the helper group the page with its site.
  return {type: "site_metadata", domain: location.hostname, name,
    identity: {application_name: applicationName, manifest}};
}

function reportSiteIdentity() {
  clearTimeout(reportTimer);
  const report = siteIdentity();
  const text = JSON.stringify(report);
  if (text === lastReport) return;
  const wait = lastReportAt + MIN_REPORT_MS - Date.now();
  if (wait > 0) {
    reportTimer = setTimeout(reportSiteIdentity, wait);
    return;
  }
  lastReport = text;
  lastReportAt = Date.now();
  chrome.runtime.sendMessage(report).catch(() => {});
}
reportSiteIdentity();
let metadataTimer;
if (document.head) new MutationObserver(() => {
  clearTimeout(metadataTimer);
  metadataTimer = setTimeout(reportSiteIdentity, 300);
}).observe(document.head, {subtree: true, childList: true, attributes: true,
  attributeFilter: ["content", "name", "property", "href", "rel"]});
