// Read service identity only; document titles can contain private page details.
function reportSiteIdentity() {
  const application = document.querySelector('meta[name="application-name"]');
  const applicationName = (application?.content || "").replace(/\s+/g, " ").trim().slice(0, 120);
  const metadata = application
    || document.querySelector('meta[property="og:site_name"]');
  const name = (metadata?.content || "").replace(/\s+/g, " ").trim().slice(0, 120);
  let manifest = "";
  const link = document.querySelector('link[rel~="manifest"]');
  try {
    const url = new URL(link?.href || "", location.href);
    if (link && ["http:", "https:"].includes(url.protocol)
        && !url.username && !url.password
        && (url.hostname === location.hostname || location.hostname.endsWith("." + url.hostname))) {
      url.search = "";
      url.hash = "";
      manifest = url.href;
    }
  } catch (_) {}
  const identity = {
    application_name: applicationName,
    manifest,
  };
  chrome.runtime.sendMessage({type: "site_metadata", domain: location.hostname, name, identity})
    .catch(() => {});
}
reportSiteIdentity();
let metadataTimer;
if (document.head) new MutationObserver(() => {
  clearTimeout(metadataTimer);
  metadataTimer = setTimeout(reportSiteIdentity, 300);
}).observe(document.head, {subtree: true, childList: true, attributes: true,
  attributeFilter: ["content", "name", "property", "href", "rel"]});
