const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let onMessage;
const removed = [];
let tabs = [
  {id: 1, active: true, url: 'https://example.org'},
  {id: 2, active: false, url: 'https://example.org'},
  {id: 3, active: true, url: 'https://other.example.org'},
  {id: 4, active: true, url: 'https://example.org'},
];
const event = () => ({addListener() {}});
const chrome = {
  runtime: {onMessage: event(), connectNative: () => ({
    onMessage: {addListener(fn) { onMessage = fn; }}, onDisconnect: event(), postMessage() {}
  })},
  tabs: {onRemoved: event(), onActivated: event(), onUpdated: event(),
    query: async () => tabs, remove: id => removed.push(id)},
  windows: {getAll: async () => [], onCreated: event(), onRemoved: event(), onFocusChanged: event()}
};
vm.runInNewContext(fs.readFileSync('browser/background.js', 'utf8'), {
  chrome, crypto: {randomUUID: () => 'test-browser'}, URL, console,
  setInterval() {}, setTimeout() {}, clearTimeout() {}
});
(async () => {
  await onMessage({blocked_domains: ['example.org'], blocked_tab_ids: [1, 2, 3]});
  assert.deepEqual(removed, [1], 'only the active, visible, matching tab is closed');
  removed.length = 0;
  await onMessage({blocked_domains: ['example.org']});
  assert.deepEqual(removed, [], 'missing visible-tab confirmation never closes all tabs');
  await onMessage({blocked_domains: [], blocked_tab_ids: [1]});
  assert.deepEqual(removed, [], 'pause response closes nothing');
  console.log('Browser enforcement tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
