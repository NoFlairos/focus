document.getElementById("extension").textContent = chrome.runtime.id;
async function check() {
  const status = document.getElementById("status");
  const retry = document.getElementById("retry");
  retry.disabled = true;
  status.textContent = "Checking connection…";
  try {
    const result = await chrome.runtime.sendNativeMessage("io.github.noflairos.focus_ratio", {op: "status"});
    status.textContent = result.ok ? "Connected · local tracking available" : "Local service unavailable";
    document.getElementById("setup").open = !result.ok;
  } catch (_) {
    status.textContent = "Not connected · check the local helper";
    document.getElementById("setup").open = true;
  } finally {
    retry.disabled = false;
  }
}
document.getElementById("retry").addEventListener("click", check);
check();
