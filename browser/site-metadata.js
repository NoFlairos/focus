// Read service identity only; document titles can contain private page details.
function reportSiteName() {
  const metadata = document.querySelector('meta[name="application-name"]')
    || document.querySelector('meta[property="og:site_name"]');
  const name = (metadata?.content || "").replace(/\s+/g, " ").trim().slice(0, 120);
  chrome.runtime.sendMessage({type: "site_metadata", domain: location.hostname, name})
    .catch(() => {});
}
reportSiteName();
let metadataTimer;
if (document.head) new MutationObserver(() => {
  clearTimeout(metadataTimer);
  metadataTimer = setTimeout(reportSiteName, 300);
}).observe(document.head, {subtree: true, childList: true, attributes: true,
  attributeFilter: ["content", "name", "property"]});
