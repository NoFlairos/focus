import {spawn,execFileSync} from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import assert from 'node:assert/strict';
const browser=spawn('/usr/bin/chromium',['--headless=new','--no-sandbox','--disable-gpu','--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync','--host-resolver-rules=MAP focus.test 127.0.0.1, MAP *.focus.test 127.0.0.1','--remote-debugging-port=9222','--user-data-dir=/test/config/chromium','--load-extension=/test/data/focus-ratio/browser','--disable-extensions-except=/test/data/focus-ratio/browser','--window-size=640,400','about:blank'],{stdio:['ignore',fs.openSync('/test/chromium.log','w'),fs.openSync('/test/chromium-errors.log','w')]});
const delay=ms=>new Promise(r=>setTimeout(r,ms));
let ws;
const server = http.createServer((req, res) => {
 res.writeHead(200, {'Content-Type': 'text/html'});
 res.end('<title>Focus limit test</title><meta name="application-name" content="Focus isolated app">Isolated test');
});
await new Promise(resolve => server.listen(8080, '127.0.0.1', resolve));
const timeout=setTimeout(()=>{browser.kill('SIGKILL');console.error('Browser test timed out');process.exit(1)},90000);
try {
 let targets=[];
 for(let i=0;i<80;i++) {await delay(250);try{targets=await(await fetch('http://127.0.0.1:9222/json/list')).json();}catch{} if(targets.some(t=>t.type==='service_worker'))break;}
 fs.writeFileSync('/test/targets.json',JSON.stringify(targets,null,2));
 const worker=targets.find(t=>t.type==='service_worker'&&t.url.startsWith('chrome-extension://'));
 if(!worker)throw new Error('Extension service worker not loaded');
 const id=new URL(worker.url).hostname;
 execFileSync('bash',['/project/scripts/install-browser-host.sh',id],{stdio:'inherit'});
 const page=targets.find(t=>t.type==='page');
 ws=new WebSocket(page.webSocketDebuggerUrl);
 await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
 let seq=0;const pending=new Map();
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&pending.has(m.id)){const {r,j}=pending.get(m.id);pending.delete(m.id);m.error?j(new Error(JSON.stringify(m.error))):r(m.result);}};
 const call=(method,params={})=>new Promise((r,j)=>{const id=++seq;pending.set(id,{r,j});ws.send(JSON.stringify({id,method,params}));});
 await call('Page.enable');
 await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'dark'}]});
 await call('Emulation.setDeviceMetricsOverride',{width:640,height:400,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:`chrome-extension://${id}/status.html`});
 let status='';
 for(let i=0;i<40;i++){await delay(250);const v=await call('Runtime.evaluate',{expression:'document.getElementById("status")?.textContent',returnByValue:true});status=v.result.value||'';if(status.startsWith('Connected'))break;}
 if(!status.startsWith('Connected')){const error=await call('Runtime.evaluate',{expression:'chrome.runtime.sendNativeMessage("io.github.noflairos.focus_ratio",{op:"status"}).catch(e=>String(e))',awaitPromise:true,returnByValue:true});throw new Error('Native bridge: '+JSON.stringify(error));}
 await call('Page.captureScreenshot',{format:'png'}).then(r=>fs.writeFileSync('/test/extension-connected.png',Buffer.from(r.data,'base64')));
 execFileSync('python3',['/test/data/focus-ratio/focus_ratio_agent.py','warning','off']);
 await delay(1500);
 const state=JSON.parse(fs.readFileSync('/test/state/focus-ratio/state.json'));
 if(state.warn_before_limit!==false)throw new Error('Warning toggle did not persist');
 if(state.tracked.length)throw new Error('Unexpected real desktop activity in sandbox');
 fs.writeFileSync('/test/browser-result.json',JSON.stringify({extensionLoaded:true,nativeHostConnected:true,warningDisabled:true,trackedEntries:state.tracked.length,screenshot:'640x400',updatedAt:state.updated_at},null,2));
 // Chromium and the native bridge are real; only compositor visibility is simulated.
 execFileSync('python3', ['/test/data/focus-ratio/focus_ratio_agent.py', 'schedule', '0,1,2,3,4,5,6', '00:00', '00:00']);
 execFileSync('python3', ['/test/data/focus-ratio/focus_ratio_agent.py', 'classify', 'site:127.0.0.1', 'consumption']);
 execFileSync('python3', ['/test/data/focus-ratio/focus_ratio_agent.py', 'quota', 'site:127.0.0.1', '1']);
 fs.writeFileSync('/test/visible-browser.json', JSON.stringify([{
   class: 'chromium', title: 'Focus limit test - Chromium', address: '0x123',
   workspace: {id: 1}, size: [640, 400], mapped: true, hidden: false
 }]));
 const evaluate = async expression => (await call('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true})).result.value;
 const statusTab = await evaluate('chrome.tabs.getCurrent()');
 const activeTab = await evaluate('chrome.tabs.create({url:"http://127.0.0.1:8080",active:true})');
 const backgroundTab = await evaluate('chrome.tabs.create({url:"http://127.0.0.1:8080",active:false})');
 for(let i=0;i<40;i++) {
   await delay(250);
   const state = JSON.parse(fs.readFileSync('/test/state/focus-ratio/state.json'));
   if(state.tracked.some(row => row.id === 'site:127.0.0.1' && row.visible_windows === 1)) break;
   if(i === 39) throw new Error('Active test site was not matched');
 }
 execFileSync('python3', ['-c', `import sys,datetime
sys.path.insert(0,'/test/data/focus-ratio')
import focus_ratio_agent as a
now=datetime.datetime.now().astimezone()
s=a.Store();s.add_times({'site:127.0.0.1':'consumption'},61,a.current_hour_bucket(now),now.date().isoformat());s.db.close()`]);
 let tabIds = [];
 for(let i=0;i<40;i++) {
   await delay(250);
   tabIds = await evaluate('chrome.tabs.query({}).then(tabs=>tabs.map(tab=>tab.id))');
   if(!tabIds.includes(activeTab.id)) break;
 }
 assert(!tabIds.includes(activeTab.id), 'Active tab must close after its hourly quota');
 assert(tabIds.includes(backgroundTab.id), 'Background tab must stay open');
 execFileSync('python3', ['/test/data/focus-ratio/focus_ratio_agent.py', 'classify', 'site:focus.test', 'productive']);
 await evaluate(`chrome.tabs.update(${statusTab.id}, {active:true})`);
 const parentTab = await evaluate('chrome.tabs.create({url:"http://focus.test:8080",active:false})');
 for(let i=0;i<40;i++) {
   await delay(250);
   const config = JSON.parse(fs.readFileSync('/test/config/focus-ratio/config.json'));
   if(config.site_identity?.['focus.test']?.application_name === 'Focus isolated app') break;
   if(i === 39) throw new Error('Declared application identity was not received from the real page');
 }
 const smartTab = await evaluate('chrome.tabs.create({url:"http://app.focus.test:8080",active:false})');
 for(let i=0;i<40;i++) {
   await delay(250);
   const config = JSON.parse(fs.readFileSync('/test/config/focus-ratio/config.json'));
   if(config.service_links['site:app.focus.test'] === 'site:focus.test') break;
   if(i === 39) throw new Error('Real subdomain was not grouped by matching application identity');
 }
 await evaluate(`chrome.tabs.update(${statusTab.id}, {active:true})`);
 await evaluate(`chrome.tabs.remove([${smartTab.id}, ${parentTab.id}])`);
 console.log('Real background-page metadata grouped a subdomain in Smart mode.');
 fs.unlinkSync('/test/visible-browser.json');
 await evaluate(`chrome.tabs.update(${statusTab.id}, {active:true})`);
 await evaluate(`chrome.tabs.remove(${backgroundTab.id})`);
 const resultPath = '/test/browser-result.json';
 const result = JSON.parse(fs.readFileSync(resultPath));
 Object.assign(result, {activeTabClosedAtQuota:true, backgroundTabPreserved:true, smartSubdomainGrouped:true, compositorVisibility:'simulated'});
 fs.writeFileSync(resultPath, JSON.stringify(result, null, 2));
 console.log('Real active tab closed at quota; background tab kept open.');
 process.kill(Number(fs.readFileSync('/test/helper.pid','utf8')));
 await delay(500);
 await call('Runtime.evaluate',{expression:'check()',awaitPromise:true});
 const offline=await call('Runtime.evaluate',{expression:'document.getElementById("status").textContent',returnByValue:true});
 if(!offline.result.value.startsWith('Not connected'))throw new Error('Offline state not detected');
 // Collapse setup through its real click handler, as a user can; no UI text is replaced.
 await call('Runtime.evaluate',{expression:'document.querySelector("#setup summary").click()'});
 await call('Page.captureScreenshot',{format:'png'}).then(r=>fs.writeFileSync('/test/extension-offline.png',Buffer.from(r.data,'base64')));
 console.log('Real Chromium extension and native helper connected; screenshot captured.');
} finally {clearTimeout(timeout);server.close();ws?.close();browser.kill();await delay(500);if(browser.exitCode===null)browser.kill('SIGKILL');}
