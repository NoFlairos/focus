const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let onMessage;
let onSiteMessage;
const removed = [];
const snapshots = [];
let windows = [];
let tabs = [
  {id: 1, active: true, url: 'https://example.org'},
  {id: 2, active: false, url: 'https://example.org'},
  {id: 3, active: true, url: 'https://other.example.org'},
  {id: 4, active: true, url: 'https://example.org'},
];
const event = () => ({addListener() {}});
const chrome = {
  runtime: {onMessage: {addListener(fn) { onSiteMessage = fn; }}, connectNative: () => ({
    onMessage: {addListener(fn) { onMessage = fn; }}, onDisconnect: event(),
    postMessage(snapshot) { snapshots.push(JSON.parse(JSON.stringify(snapshot))); }
  })},
  tabs: {onRemoved: event(), onActivated: event(), onUpdated: event(),
    query: async () => tabs, remove: id => removed.push(id)},
  windows: {getAll: async () => windows, onCreated: event(), onRemoved: event(), onFocusChanged: event()}
};
vm.runInNewContext(fs.readFileSync('extensions/chromium/background.js', 'utf8'), {
  chrome, crypto: {randomUUID: () => 'test-browser'}, URL, console,
  setInterval() {}, setTimeout() {}, clearTimeout() {}
});
(async () => {
  const metadata = [];
  vm.runInNewContext(fs.readFileSync('extensions/chromium/site-metadata.js', 'utf8'), {
    document: {head: {}, querySelector(selector) {
      if (selector === 'meta[name="application-name"]') return {content: '  Workspace   App '};
      if (selector === 'link[rel~="manifest"]') return {href: 'https://example.org/app.json?token=private#state'};
      return null;
    }},
    location: {hostname: 'app.example.org', href: 'https://app.example.org/'}, URL,
    chrome: {runtime: {sendMessage(message) { metadata.push(JSON.parse(JSON.stringify(message))); return Promise.resolve(); }}},
    MutationObserver: class { observe() {} }, setTimeout() {}, clearTimeout() {},
  });
  assert.deepEqual(metadata[0].identity, {
    application_name: 'Workspace App', manifest: 'https://example.org/app.json'
  });
  windows = [{id: 1, state: 'normal', tabs: [{id: 1, active: true, title: 'Inbox', url: 'https://app.example.org/'}]}];
  onSiteMessage(metadata[0], {tab: {id: 1}, frameId: 0, url: 'https://app.example.org/'});
  await new Promise(setImmediate);
  assert.deepEqual(snapshots.at(-1).windows[0].site_identity, metadata[0].identity);
  windows[0].tabs.push({id: 5, active: false, url: 'https://example.org/', title: 'Background page'});
  onSiteMessage({...metadata[0], domain: 'example.org'}, {tab: {id: 5}, frameId: 0, url: 'https://example.org/'});
  await new Promise(setImmediate);
  assert.equal(snapshots.at(-1).windows.length, 1);
  assert.equal(snapshots.at(-1).windows[0].tab_id, 1, 'background tabs never become activity windows');
  assert.deepEqual(snapshots.at(-1).site_metadata.map(row => row.domain), ['app.example.org', 'example.org']);
  assert(!JSON.stringify(snapshots.at(-1).site_metadata).includes('Background page'), 'background metadata contains no page titles');
  windows[0].tabs[1].url = 'https://unrelated.example/';
  onSiteMessage(metadata[0], {tab: {id: 1}, frameId: 0, url: 'https://app.example.org/'});
  await new Promise(setImmediate);
  assert.deepEqual(snapshots.at(-1).site_metadata.map(row => row.domain), ['app.example.org'], 'navigation never sends a stale site identity');
  await onMessage({blocked_domains: ['example.org'], blocked_tab_ids: [1, 2, 3]});
  assert.deepEqual(removed, [1], 'only the active, visible, matching tab is closed');
  removed.length = 0;
  await onMessage({blocked_domains: ['example.org']});
  assert.deepEqual(removed, [], 'missing visible-tab confirmation never closes all tabs');
  await onMessage({blocked_domains: [], blocked_tab_ids: [1]});
  assert.deepEqual(removed, [], 'pause response closes nothing');
  console.log('Browser enforcement tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
