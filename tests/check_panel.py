# Instantiate the real panel with lightweight shell fixtures; requires QtTest.
from pathlib import Path
import shutil, tempfile, subprocess, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
requests = []
class ImageProbe(BaseHTTPRequestHandler):
 def do_GET(self):
  requests.append(self.path)
  self.send_response(204); self.end_headers()
 def log_message(self, *args): pass
server = ThreadingHTTPServer(("127.0.0.1", 0), ImageProbe)
threading.Thread(target=server.serve_forever, daemon=True).start()
temporary = tempfile.TemporaryDirectory(prefix='focus-panel-test-')
root=Path(temporary.name)
modules=root/'modules'
def module(name, files):
 d=modules.joinpath(*name.split('.'));d.mkdir(parents=True,exist_ok=True)
 lines=['module '+name]
 for typ,(singleton,body) in files.items():
  lines.append(('singleton ' if singleton else '')+typ+' 1.0 '+typ+'.qml')
  (d/(typ+'.qml')).write_text(('pragma Singleton\n' if singleton else '')+body)
 (d/'qmldir').write_text('\n'.join(lines))
module('Quickshell',{'Quickshell':(True,'import QtQuick\nQtObject { function execDetached(args) {} function env(name) {return "";} }')})
module('Quickshell.Io',{'FileView':(False,'''import QtQuick
QtObject {property string path; property bool watchChanges; property bool printErrors; signal loaded(); signal fileChanged(); function reload() {} function text() {return "{}";} }'''),
'Process':(False,'''import QtQuick
QtObject {property var command: []; property bool running: false; property bool stdinEnabled: false; property string written: ""; signal started(); signal exited(int exitCode); onRunningChanged: if (running) started(); function write(data) {written += data;} }''')})
module('qs.Commons',{
'Style':(True,'''import QtQuick
QtObject { property var bar: ({iconFont: 13, iconSlot: 27}); property int cornerRadius: 6; property var spacing: ({hairline: 1}); property var font: ({family: "Sans", body: 14, bodySmall: 12, caption: 10, title: 18, heading: 20}); function controlFill(f,h,fg,a) {return "transparent";} function controlBorder(f,h,fg,a) {return "gray";} function space(n) {return n;} function spaceReal(n) {return n;} }'''),
'Color':(True,'''import QtQuick
QtObject { property color accent: "#7aa2f7"; property var popups: ({text: Qt.rgba(0.9,0.9,0.9,1), background: Qt.rgba(0.12,0.12,0.12,1)}) }''')})
module('qs.Ui',{
'BarWidget':(False,'''import QtQuick
Item {property string moduleName; property var bar: null;}'''),
'WidgetButton':(False,'''import QtQuick
Item {property var bar; property string text; property bool labelVisible; property bool hasVisualContent; property real fontSize; property real fixedWidth; property color foreground: "white"; property color activeColor: "#a55555"; property string fontFamily: "Sans"; property string tooltipText; signal pressed(int buttonCode); width:fixedWidth; height:30; implicitWidth:fixedWidth; implicitHeight:30;}'''),
'Toggle':(False,'''import QtQuick
Item {property string label; property string description; property bool checked; property color foreground; property real titleSize; signal clicked(); width: 100; height: 30}'''),
'TextField':(False,'''import QtQuick
import QtQuick.Controls as Controls
Controls.TextField { property color foreground; }'''),
'Dropdown':(False,'''import QtQuick
Item { property string label; property string value; property var options: []; property bool showLabel; property color foreground; property color background; property bool popupOpen: false; signal changed(string value); implicitHeight: 32; function currentLabel(){return value;} function open(){popupOpen=true;} function close(){popupOpen=false;} }'''),
'Button':(False,'''import QtQuick
Item { property string text; property string tooltipText; signal clicked(); implicitHeight: 32; property color foreground; property color background; property bool bordered; property bool focusable; property bool leftAlign; property bool selected; property real fontSize; property real horizontalPadding; }'''),
'Panel':(False,'''import QtQuick
Item { property string moduleName; property bool manageIpc; property bool opened: true; property var bar: null; function open() {opened=true;} function close() {opened=false;} }'''),
'KeyboardPanel':(False,'''import QtQuick
Item { property var anchorItem; property var owner; property var bar; property bool open; property var focusTarget; property real contentWidth; property real contentHeight; width:contentWidth; height:contentHeight; function fittedContentWidth(n){return n;} function fittedContentHeight(n){return n;} }'''),
'PanelToolTip':(False,'''import QtQuick
import QtQuick.Controls
ToolTip { id: tip; contentItem: Text { textFormat: Text.PlainText; text: tip.text } }'''),
'PanelKeyCatcher':(False,'''import QtQuick
Item { property bool blocked: false; signal closeRequested(); signal tabRequested(int direction); }''')})
# Qt's attached ToolTip renders markup; app and site names must only reach PlainText tooltips.
for source in ('Panel.qml','BarWidget.qml'):
 assert 'ToolTip.' not in Path(source).read_text(), source+' uses an attached ToolTip'
# Text defaults to AutoText, which renders markup: every Text must state PlainText.
import re
for source in ('Panel.qml','BarWidget.qml','FocusMark.qml'):
 lines=Path(source).read_text().split('\n')
 for i,line in enumerate(lines):
  if not re.search(r'(^|[\s:])Text \{',line): continue
  depth=0; plain=False
  for j in range(i,len(lines)):
   if (depth==1 or j==i) and 'textFormat: Text.PlainText' in lines[j]: plain=True
   depth+=lines[j].count('{')-lines[j].count('}')
   if depth<=0: break
  assert plain, '%s:%d Text without textFormat: Text.PlainText' % (source,i+1)
shutil.copyfile('Panel.qml',root/'FocusPanel.qml')
shutil.copyfile('Panel.qml',root/'Panel.qml')
shutil.copyfile('BarWidget.qml',root/'FocusBar.qml')
shutil.copyfile('FocusMark.qml',root/'FocusMark.qml')
(root/'tst_panel.qml').write_text('''import QtQuick
import QtTest
Item {
 width: 448; height: 560
 QtObject {
 id: widget
 property var snapshot: ({updated_at: new Date().toISOString(), diagnostics: {browser_connected:true}, tracked: [
 {id:"site:one.example",name:"One",category:"consumption",quota_seconds:600,configured:true,members:["site:one.example","app:linked-member"]},
 {id:"app:two",name:"Two",category:"productive",quota_seconds:600,configured:true,members:["app:two"]}], history:[],today:{}, warn_before_limit:true,
 weekly:{current:{screen_seconds:600,recorded_days:1,productive:5,neutral:2,consumption:3},previous:{screen_seconds:500,recorded_days:1},screen_delta:100},
 suggestions:[{source:"site:one.example",destination:"app:two",name:"Same name",reason:"Matching names"}]})
 property string agentPath: "unused"
 property string stateHome: "/home/u/.local/state"
 property bool serviceConnected: true
 property string connectionLabel: "Connected"
 function appLabel(row) {return row.name;}
 }
 FocusPanel {id: focusPanel; anchors.fill:parent; widget:widget; page:"manage"}
 FocusBar {id: focusBar; width:340; height:30}
 TestCase {
 function test_connection_indicator() {
 var now = Date.now()
 focusBar.statusNow = now
 var online = {updated_at:new Date(now).toISOString(), working:true, diagnostics:{browser_status:"connected"},tracked:[]}
 focusBar.snapshot = online
 var indicator = findChild(focusBar, "connectionIndicator")
 verify(indicator !== null)
 compare(focusBar.connectionIssue, "")
 verify(!indicator.visible)
 focusBar.snapshot = Object.assign({}, online, {diagnostics:{browser_status:"browser_offline"}})
 compare(focusBar.connectionIssue, "Browser offline")
 verify(indicator.visible)
 focusBar.snapshot = Object.assign({}, online, {diagnostics:{browser_status:"browser_closed"}})
 compare(focusBar.connectionIssue, "")
 verify(!indicator.visible)
 focusBar.snapshot = Object.assign({}, online, {diagnostics:{browser_status:"connecting"}})
 compare(focusBar.connectionIssue, "")
 verify(!indicator.visible)
 focusBar.showDiagnostics()
 compare(focusBar.panelItem.page, "manage")
 compare(focusBar.panelItem.manageSection, "diagnostics")
 focusBar.snapshot = Object.assign({}, online, {diagnostics:{browser_status:"reload_extension"}})
 compare(focusBar.connectionIssue, "Reload extension")
 focusBar.snapshot = Object.assign({}, online, {updated_at:new Date(now - 25000).toISOString()})
 compare(focusBar.connectionIssue, "Service offline")
 focusBar.snapshot = online
 compare(focusBar.connectionIssue, "")
 verify(!indicator.visible)
 }
 function test_bar_logo_states() {
 var now = Date.now()
 focusBar.statusNow = now
 focusBar.snapshot = {updated_at:new Date(now).toISOString(), working:true, paused:false, tracked:[]}
 var logo = findChild(focusBar, "focusLogo")
 verify(logo !== null && logo.visible && logo.active && !logo.session)
 focusBar.snapshot = {updated_at:new Date(now).toISOString(), working:true, paused:true, tracked:[]}
 verify(!logo.active)
 compare(logo.opacity, 0.55)
 focusBar.snapshot = {updated_at:new Date(now).toISOString(), working:true, focus_until:now/1000 + 600, tracked:[]}
 verify(logo.session && logo.active)
 focusBar.snapshot = {working:true, tracked:[{id:"app:x",name:"X",visible_windows:1,category:"neutral"}]}
 verify(!logo.visible)
 focusBar.snapshot = {tracked:[]}
 }
 function test_untrusted_labels_stay_literal() {
 var markup = '<img src="http://127.0.0.1:PROBE_PORT/label.png"><b>Untrusted site</b>'
 focusBar.snapshot = {working:true, tracked:[{id:"site:untrusted.example",name:markup,visible_windows:1,category:"neutral"}]}
 focusPanel.page="manage"; focusPanel.manageSection="apps"
 widget.snapshot = Object.assign({}, widget.snapshot, {suggestions:[{source:"site:one.example",destination:"app:two",name:markup,reason:"Matching names"}]})
 wait(200)
 var barLabel = findChild(focusBar, "barTargetLabel")
 verify(barLabel !== null)
 compare(barLabel.text, markup)
 compare(barLabel.textFormat, Text.PlainText)
 var suggestion = findChild(focusPanel, "suggestionLabel")
 verify(suggestion !== null)
 compare(suggestion.text, markup)
 compare(suggestion.textFormat, Text.PlainText)
 wait(300)
 focusBar.snapshot = {tracked:[]}
 widget.snapshot = Object.assign({}, widget.snapshot, {suggestions:[]})
 focusPanel.manageSection=""
 }
 name: "ManagePanel"; when:windowShown
 function test_excluded_privacy() {
 var previous = widget.snapshot
 widget.snapshot = Object.assign({}, previous, {ignored_targets:["site:private.example", "app:private"]})
 focusPanel.manageSection="apps"
 wait(30)
 var toggle = findChild(focusPanel, "excludedToggle")
 verify(toggle !== null)
 verify(toggle.visible)
 compare(toggle.text, "Excluded · 2")
 compare(findChild(focusPanel, "excludedEntry"), null)
 toggle.clicked()
 wait(30)
 verify(findChild(focusPanel, "excludedEntry") !== null)
 focusPanel.appSearch = "private.example"
 compare(focusPanel.filteredIgnored.length, 1)
 focusPanel.appSearch = ""
 focusPanel.opened=false
 verify(!focusPanel.excludedOpen)
 focusPanel.opened=true
 widget.snapshot = previous
 focusPanel.manageSection=""
 }
 function test_single_subdomain_control_and_scroll_to_top() {
 var previous = widget.snapshot
 var group = {id:"site:mail.example",name:"Mail",category:"productive",configured:true,members:["site:mail.example","site:inbox.other.example","app:mail"],grouping_scope:"mail.example",grouping_scopes:["mail.example","other.example"]}
 compare(focusPanel.siteScopes(group).length, 1)
 compare(focusPanel.siteScopes(group)[0], "mail.example")
 widget.snapshot = Object.assign({}, previous, {tracked:[group]})
 focusPanel.manageSection="apps"
 wait(30)
 var scroll=findChild(focusPanel,"activityScroll")
 var top=findChild(focusPanel,"scrollToTopButton")
 verify(scroll!==null && top!==null)
 scroll.contentY=100
 verify(top.visible)
 top.clicked()
 tryCompare(scroll,"contentY",0,600)
 verify(!top.visible)
 var bottom=findChild(focusPanel,"scrollToBottomButton")
 verify(bottom!==null)
 var many=[]
 for(var i=0;i<25;i++) many.push(Object.assign({},group,{id:"app:test"+i,name:"App "+i,members:["app:test"+i],grouping_scope:"",grouping_scopes:[]}))
 widget.snapshot=Object.assign({},previous,{tracked:many})
 wait(30)
 verify(scroll.contentHeight>scroll.height)
 verify(bottom.visible)
 bottom.clicked()
 tryCompare(scroll,"contentY",Math.max(0,scroll.contentHeight-scroll.height),600)
 verify(!bottom.visible)
 verify(top.visible)
 top.clicked()
 tryCompare(scroll,"contentY",0,600)
 widget.snapshot=Object.assign({},previous,{tracked:[group]})
 // Pending entries are offered as a source; only saved entries can supply settings.
 var pending = {id:"site:other.host.example",name:"New site",category:"unclassified",configured:false,members:["site:other.host.example"]}
 widget.snapshot=Object.assign({}, widget.snapshot,{tracked:[group,pending]})
 pending.review = true
 widget.snapshot=Object.assign({}, widget.snapshot,{tracked:[group,pending]})
 focusPanel.page="review"; focusPanel.expandedCardId=pending.id; wait(30)
 compare(focusPanel.reviewCount,1)
 var picker=findChild(focusPanel,"mergePicker")
 verify(picker!==null)
 compare(picker.options.length,1)
 compare(picker.options[0].value,group.id)
 focusPanel.expandedCardId=""; focusPanel.page="manage"
 widget.snapshot=previous
 focusPanel.commandQueue=[]
 focusPanel.manageSection=""
 }
 function test_smooth_wheel_and_deferred_refresh() {
 var previous = widget.snapshot
 var many=[]
 for(var i=0;i<60;i++) many.push({id:"app:wheel"+i,name:"Wheel "+i,category:"neutral",configured:true,members:["app:wheel"+i]})
 widget.snapshot=Object.assign({},previous,{tracked:many})
 focusPanel.page="manage"; focusPanel.manageSection="apps"; wait(50)
 var scroll=findChild(focusPanel,"activityScroll")
 scroll.contentY=0
 mouseWheel(scroll, 100, 100, 0, -120)
 verify(focusPanel.scrollBusy)
 wait(30)
 verify(scroll.contentY > 0 && scroll.contentY < 120)
 tryVerify(function() { return scroll.contentY >= 119 }, 600)
 var glide=findChild(focusPanel,"touchpadGlide")
 scroll.contentY=0
 glide.begin(-2000)
 tryVerify(function() { return !glide.running }, 3000)
 // Chromium's curve from 2000 px/s travels about 420 px in 0.7 s.
 verify(scroll.contentY > 400 && scroll.contentY < 620, "glide distance " + scroll.contentY)
 focusPanel.scrollActivity()
 widget.snapshot=Object.assign({},previous,{tracked:many.slice(0, 3)})
 verify(focusPanel.syncDeferred)
 tryVerify(function() { return !focusPanel.scrollBusy && !focusPanel.syncDeferred }, 1500)
 widget.snapshot=previous
 focusPanel.manageSection=""
 }
 function test_limit_prompt_snooze() {
 var previous = widget.snapshot
 focusPanel.page="now"
 widget.snapshot = Object.assign({}, previous, {limit_prompts:[{id:"site:one.example",name:"One"}]})
 wait(30)
 var block = findChild(focusPanel, "limitPrompts")
 verify(block.visible)
 findChild(focusPanel, "promptSnoozeButton").clicked()
 compare(focusPanel.commandQueue[0][0], "snooze")
 compare(focusPanel.commandQueue[0][1], "site:one.example")
 verify(!block.visible)
 widget.snapshot = previous
 verify(!block.visible)
 focusPanel.commandQueue=[]; focusPanel.snoozedPrompts=[]
 focusPanel.page="manage"
 }
 function test_history_details_and_limit_suggestions() {
 var previous = widget.snapshot
 var day = Qt.formatDateTime(new Date(), "yyyy-MM-dd")
 widget.snapshot = Object.assign({}, previous, {history:[{day:day, productive:10, screen_seconds:900}],
   day_details:(function(){ var d = {}; d[day] = [{id:"app:two",name:"Two",category:"productive",seconds:600}]; return d })(),
   limit_suggestions:[{id:"app:two",name:"Two",week_seconds:14400,daily_minutes:30}], day_start_hour:4})
 focusPanel.page="history"; wait(50)
 compare(findChild(focusPanel, "dayDetail"), null)
 focusPanel.expandedDay = day; wait(30)
 verify(findChild(focusPanel, "dayDetail") !== null)
 var apply = findChild(focusPanel, "applyLimitSuggestion")
 compare(apply.text, "30m a day")
 apply.clicked()
 compare(focusPanel.commandQueue[0][0], "limit-suggestion")
 compare(focusPanel.commandQueue[0][2], "apply")
 verify(!findChild(focusPanel, "limitSuggestions").visible)
 focusPanel.commandQueue=[]
 focusPanel.page="manage"; focusPanel.manageSection="schedule"; wait(30)
 var dayStart = findChild(focusPanel, "dayStartStepper")
 compare(dayStart.valueText, "04:00")
 dayStart.step(1)
 compare(focusPanel.commandQueue[0][0], "day-start")
 compare(focusPanel.commandQueue[0][1], "5")
 focusPanel.commandQueue=[]; focusPanel.expandedDay=""; focusPanel.handledSuggestions=[]
 focusPanel.manageSection=""
 widget.snapshot = previous
 }
 function test_no_clipboard_reading_fields() {
 focusPanel.page="manage"; focusPanel.manageSection="schedule"; wait(30)
 var start=findChild(focusPanel, "scheduleStart")
 verify(start !== null)
 verify(start.label === "Tracking start time")
 focusPanel.scheduleStartDraft="08:00"
 start.step(1); compare(focusPanel.scheduleStartDraft, "08:15")
 focusPanel.scheduleStartDraft="09:10"
 start.step(-1); compare(focusPanel.scheduleStartDraft, "09:00")
 focusPanel.scheduleStartDraft="00:00"
 start.step(-1); compare(focusPanel.scheduleStartDraft, "23:45")
 focusPanel.scheduleStartDraft="08:00"; focusPanel.scheduleTimeEdited=false
 focusPanel.manageSection="apps"; wait(30)
 var search=findChild(focusPanel, "appSearch")
 search.forceActiveFocus()
 keyClick("h"); keyClick("j"); keyClick("x")
 compare(focusPanel.appSearch, "hjx")
 keyClick(Qt.Key_Backspace); compare(focusPanel.appSearch, "hj")
 keyClick(Qt.Key_Escape)
 verify(!search.activeFocus)
 verify(focusPanel.opened)
 focusPanel.appSearch=""; focusPanel.manageSection=""
 }
 function test_export_folder_is_focus_only() {
 var previous = widget.snapshot
 widget.snapshot = Object.assign({}, previous, {data_action:{path:"/home/u/.local/state/focus-ratio/exports/export_history-1.csv"}})
 compare(focusPanel.exportFolder, "/home/u/.local/state/focus-ratio/exports")
 widget.snapshot = Object.assign({}, previous, {data_action:{path:"/etc/passwd"}})
 compare(focusPanel.exportFolder, "")
 widget.snapshot = Object.assign({}, previous, {data_action:{path:"--help/focus-ratio/exports/a.csv"}})
 compare(focusPanel.exportFolder, "")
 widget.snapshot = Object.assign({}, previous, {data_action:{path:"/x/../focus-ratio/exports/a.csv"}})
 compare(focusPanel.exportFolder, "")
 widget.snapshot = Object.assign({}, previous, {data_action:{path:"/tmp/other/focus-ratio/exports/a.csv"}})
 compare(focusPanel.exportFolder, "", "only the real export folder")
 widget.snapshot = previous
 }
 function test_bar_and_panel_stay_bounded() {
 var many = []
 for (var i = 0; i < 400; i++) many.push({id:"app:flood"+i, name:"Flood "+i, category:"neutral", configured:true, visible_windows:1, members:["app:flood"+i]})
 var previous = focusBar.snapshot
 focusBar.snapshot = Object.assign({}, previous, {updated_at:new Date().toISOString(), tracked:many})
 compare(focusBar.chipTargets.length, 8)
 var lines = findChild(focusBar, "focusButton").tooltipText.split("\n")
 compare(lines.length, 6)
 compare(lines[5], "+ 395 more")
 focusBar.snapshot = previous
 var panelPrevious = widget.snapshot
 widget.snapshot = Object.assign({}, panelPrevious, {tracked:many}); wait(30)
 compare(findChild(focusPanel, "trackedModel").count, 300)
 widget.snapshot = panelPrevious; wait(30)
 }
 function test_closed_panel_skips_updates() {
 var previous = widget.snapshot
 focusPanel.close()
 widget.snapshot = Object.assign({}, previous, {working:false})
 compare(focusPanel.snapshot, previous)
 focusPanel.open()
 compare(focusPanel.snapshot.working, false)
 widget.snapshot = previous
 compare(focusPanel.snapshot, previous)
 }
 function test_commands_pass_ids_on_stdin() {
 focusPanel.commandQueue=[]
 focusPanel.runAgent(["classify", "site:private.example", "neutral"]); wait(30)
 var process = findChild(focusPanel, "commandProcess")
 compare(process.command, ["python3", "unused", "--stdin"])
 compare(process.written, '["classify","site:private.example","neutral"]\n')
 process.running = false; process.written = ""; process.exited(0)
 }
 function test_sections_and_groups() {
 compare(focusPanel.manageSection, "")
 focusPanel.manageSection="apps"; wait(30)
 compare(findChild(focusPanel, "subdomainModeButton:group"), null)
 focusPanel.expandedCardId="site:one.example"; wait(30)
 var subdomains = findChild(focusPanel, "subdomainModeButton:group")
 verify(subdomains !== null)
 verify(subdomains.visible)
 verify(!subdomains.selected)
 subdomains.clicked()
 compare(focusPanel.commandQueue[0][0], "subdomains")
 compare(focusPanel.commandQueue[0][1], "one.example")
 compare(focusPanel.commandQueue[0][2], "group")
 verify(subdomains.selected)
 widget.snapshot = Object.assign({}, widget.snapshot, {subdomain_rules:{"one.example":"group"}})
 compare(Object.keys(focusPanel.pendingSubdomainRules).length, 0)
 verify(subdomains.selected)
 focusPanel.commandQueue=[]
 var exclude = findChild(focusPanel, "excludeTargetButton")
 verify(exclude !== null)
 verify(exclude.visible)
 exclude.clicked()
 compare(focusPanel.commandQueue[0][0], "exclude")
 verify(focusPanel.ignoredTargets.length > 0)
 focusPanel.commandQueue=[]
 focusPanel.pendingExcluded=[]
 var warning = findChild(focusPanel, "warningToggle")
 verify(warning.checked)
 warning.clicked()
 compare(focusPanel.commandQueue[0][0], "warning")
 compare(focusPanel.commandQueue[0][1], "off")
 verify(!warning.checked)
 focusPanel.commandQueue=[]
 widget.snapshot = Object.assign({}, widget.snapshot, {warn_before_limit:false})
 verify(!warning.checked)
 warning.clicked()
 compare(focusPanel.commandQueue[0][1], "on")
 verify(warning.checked)
 widget.snapshot = Object.assign({}, widget.snapshot, {warn_before_limit:true})
 compare(focusPanel.warningEnabled, true)
 focusPanel.commandQueue=[]
 var budget = findChild(focusPanel, "budgetStepper")
 compare(budget.valueText, "Off")
 budget.step(1)
 compare(focusPanel.commandQueue[0][0], "budget")
 compare(focusPanel.commandQueue[0][1], "15")
 compare(budget.valueText, "15m")
 focusPanel.commandQueue=[]
 var period = findChild(focusPanel, "limitPeriodButton:day")
 verify(period !== null)
 period.clicked()
 compare(focusPanel.commandQueue[0][0], "limit-period")
 compare(focusPanel.commandQueue[0][2], "day")
 focusPanel.commandQueue=[]
 var picker = findChild(focusPanel, "mergePicker")
 verify(picker !== null)
 compare(picker.options.length, 1)
 compare(picker.options[0].label, "Two")
 compare(picker.currentLabel(), "Merge into…")
 picker.value = "app:two"
 compare(picker.currentIndex, 0)
 compare(picker.currentLabel(), "Two")
 focusPanel.expandedCardId=""
 focusPanel.pendingExcluded=[]

 focusPanel.manageSection="diagnostics"; wait(30)
 focusPanel.confirmClearHistory=true; wait(30)
 focusPanel.confirmClearHistory=false
 focusPanel.headerPicker="focus"; wait(30)
 var choice = findChild(focusPanel, "focusChoice")
 verify(choice !== null)
 choice.clicked()
 compare(focusPanel.commandQueue[0][0], "focus")
 compare(focusPanel.commandQueue[0][1], "25")
 verify(focusPanel.focusActive)
 compare(focusPanel.headerPicker, "")
 widget.snapshot = Object.assign({}, widget.snapshot, {focus_until: Date.now() / 1000 + 1500})
 verify(focusPanel.focusActive)
 widget.snapshot = Object.assign({}, widget.snapshot, {focus_until: null})
 focusPanel.commandQueue=[]
 focusPanel.page="history"; wait(30)
 var weekly = findChild(focusPanel, "weeklyToggle")
 verify(weekly.checked)
 weekly.clicked()
 compare(focusPanel.commandQueue[0][1], "off")
 focusPanel.commandQueue=[]
 focusPanel.page="manage"
 focusPanel.manageSection="apps"; wait(30)
 compare(focusPanel.matchingAppCount, 2)
 focusPanel.appSearch = "linked-member"
 compare(focusPanel.matchingAppCount, 1)
 focusPanel.appFilter = "productive"
 compare(focusPanel.matchingAppCount, 0)
 focusPanel.appSearch = ""
 compare(focusPanel.matchingAppCount, 1)
 focusPanel.appFilter = "all"
 compare(focusPanel.matchingAppCount, 2)
 }
 }
}
'''.replace('PROBE_PORT', str(server.server_port)))

environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="", QT_QUICK_CONTROLS_STYLE="Basic")
result = subprocess.run(["/usr/lib/qt6/bin/qmltestrunner", "-import", str(modules), "-input", str(root)], env=environment)
server.shutdown()
server.server_close()
temporary.cleanup()
if requests:
 raise AssertionError(f"Untrusted labels triggered network requests: {requests}")
raise SystemExit(result.returncode)
