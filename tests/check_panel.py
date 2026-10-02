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
QtObject {property string path; property bool watchChanges; property bool printErrors; signal loaded(); signal fileChanged(); function reload() {} function text() {return "{}";} }''')})
module('qs.Commons',{
'Style':(True,'''import QtQuick
QtObject { property int cornerRadius: 6; property var spacing: ({hairline: 1}); property var font: ({family: "Sans", body: 14, bodySmall: 12, caption: 10, title: 18, heading: 20}); function space(n) {return n;} function spaceReal(n) {return n;} }'''),
'Color':(True,'''import QtQuick
QtObject { property var popups: ({text: Qt.rgba(0.9,0.9,0.9,1), background: Qt.rgba(0.12,0.12,0.12,1)}) }''')})
module('qs.Ui',{
'BarWidget':(False,'''import QtQuick
Item {property string moduleName; property var bar: null;}'''),
'WidgetButton':(False,'''import QtQuick
Item {property var bar; property string text; property bool labelVisible; property bool hasVisualContent; property real fontSize; property real fixedWidth; property color foreground: "white"; property color activeColor: "#a55555"; property string fontFamily: "Sans"; property string tooltipText; signal pressed(int buttonCode); width:fixedWidth; height:30; implicitWidth:fixedWidth; implicitHeight:30;}'''),
'TextField':(False,'''import QtQuick
import QtQuick.Controls as Controls
Controls.TextField { property color foreground; }'''),
'SearchableDropdown':(False,'''import QtQuick
Item { property string label; property string value; property var options: []; property bool showLabel; property color foreground; property color background; property string placeholderText; property string emptyText; property string triggerLabel; property bool popupOpen: false; signal changed(string value); implicitHeight: 32; function open(){popupOpen=true;} function close(){popupOpen=false;} }'''),
'Button':(False,'''import QtQuick
Item { property string text; property string tooltipText; signal clicked(); implicitHeight: 32; property color foreground; property color background; property bool bordered; property bool focusable; property bool leftAlign; property bool selected; property real fontSize; property real horizontalPadding; }'''),
'Panel':(False,'''import QtQuick
Item { property string moduleName; property bool manageIpc; property bool opened: true; property var bar: null; function open() {opened=true;} function close() {opened=false;} }'''),
'KeyboardPanel':(False,'''import QtQuick
Item { property var anchorItem; property var owner; property var bar; property bool open; property var focusTarget; property real contentWidth; property real contentHeight; width:contentWidth; height:contentHeight; function fittedContentWidth(n){return n;} function fittedContentHeight(n){return n;} }'''),
'PanelKeyCatcher':(False,'''import QtQuick
Item { signal closeRequested(); signal tabRequested(int direction); }''')})
shutil.copyfile('Panel.qml',root/'FocusPanel.qml')
shutil.copyfile('Panel.qml',root/'Panel.qml')
shutil.copyfile('BarWidget.qml',root/'FocusBar.qml')
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
 function appLabel(row) {return row.name;}
 }
 FocusPanel {id: focusPanel; anchors.fill:parent; widget:widget; page:"manage"}
 FocusBar {id: focusBar; width:340; height:30}
 TestCase {
 function test_connection_indicator() {
 var now = Date.now()
 focusBar.statusNow = now
 var online = {updated_at:new Date(now).toISOString(), working:true, diagnostics:{browser_running:true,browser_connected:true,browser_can_close_tabs:true},tracked:[]}
 focusBar.snapshot = online
 var indicator = findChild(focusBar, "connectionIndicator")
 verify(indicator !== null)
 compare(focusBar.connectionIssue, "")
 verify(!indicator.visible)
 focusBar.snapshot = Object.assign({}, online, {diagnostics:{browser_connected:false,browser_connection_expected:true}})
 compare(focusBar.connectionIssue, "Browser offline")
 verify(indicator.visible)
 focusBar.snapshot = Object.assign({}, online, {diagnostics:{browser_connected:false,browser_running:false,browser_connection_expected:false}})
 compare(focusBar.connectionIssue, "")
 verify(!indicator.visible)
 focusBar.snapshot = Object.assign({}, online, {diagnostics:{browser_connected:false,browser_running:true,browser_connection_expected:false}})
 compare(focusBar.connectionIssue, "")
 verify(!indicator.visible)
 focusBar.showDiagnostics()
 compare(focusBar.panelItem.page, "manage")
 compare(focusBar.panelItem.manageSection, "diagnostics")
 focusBar.snapshot = Object.assign({}, online, {diagnostics:{browser_running:true,browser_connected:true,browser_can_close_tabs:false}})
 compare(focusBar.connectionIssue, "Reload extension")
 focusBar.snapshot = Object.assign({}, online, {updated_at:new Date(now - 6000).toISOString()})
 compare(focusBar.connectionIssue, "Service offline")
 focusBar.snapshot = online
 compare(focusBar.connectionIssue, "")
 verify(!indicator.visible)
 }
 function test_untrusted_labels_stay_literal() {
 var markup = '<img src="http://127.0.0.1:PROBE_PORT/label.png"><b>Untrusted site</b>'
 focusBar.snapshot = {working:true, tracked:[{id:"site:untrusted.example",name:markup,visible_windows:1,category:"neutral"}]}
 focusPanel.page="manage"; focusPanel.manageSection="groups"
 widget.snapshot = Object.assign({}, widget.snapshot, {suggestions:[{source:"site:one.example",destination:"app:two",name:markup,reason:"Matching names"}]})
 wait(200)
 var barLabel = findChild(focusBar, "barTargetLabel")
 verify(barLabel !== null)
 compare(barLabel.text, markup)
 compare(barLabel.textFormat, Text.PlainText)
 var suggestion = findChild(focusPanel, "suggestionLabel")
 verify(suggestion !== null)
 compare(suggestion.text, markup + " · Matching names")
 compare(suggestion.textFormat, Text.PlainText)
 wait(300)
 focusBar.snapshot = {tracked:[]}
 widget.snapshot = Object.assign({}, widget.snapshot, {suggestions:[]})
 focusPanel.manageSection=""
 }
 name: "ManagePanel"; when:windowShown
 function test_excluded_privacy() {
 var previous = widget.snapshot
 widget.snapshot = Object.assign({}, previous, {ignored_targets:["site:private.example", "app:private"], hide_excluded:true})
 focusPanel.manageSection="apps"
 wait(30)
 var toggle = findChild(focusPanel, "excludedVisibilityButton")
 verify(toggle !== null)
 verify(toggle.visible)
 compare(toggle.text, "Show")
 compare(focusPanel.filteredIgnored.length, 0)
 compare(findChild(focusPanel, "excludedEntry"), null)
 toggle.clicked()
 compare(focusPanel.commandQueue[0][0], "excluded-visibility")
 compare(focusPanel.commandQueue[0][1], "show")
 wait(30)
 compare(toggle.text, "Hide")
 compare(focusPanel.filteredIgnored.length, 2)
 verify(findChild(focusPanel, "excludedEntry") !== null)
 widget.snapshot = Object.assign({}, widget.snapshot, {hide_excluded:false})
 compare(focusPanel.pendingHideExcluded, null)
 focusPanel.commandQueue=[]
 toggle.clicked()
 compare(focusPanel.commandQueue[0][1], "hide")
 wait(30)
 compare(focusPanel.filteredIgnored.length, 0)
 compare(findChild(focusPanel, "excludedEntry"), null)
 widget.snapshot = Object.assign({}, widget.snapshot, {hide_excluded:true})
 compare(focusPanel.pendingHideExcluded, null)
 widget.snapshot = previous
 focusPanel.commandQueue=[]
 focusPanel.manageSection=""
 }
 function test_individual_excluded_privacy() {
 var previous = widget.snapshot
 widget.snapshot = Object.assign({}, previous, {ignored_targets:["site:private.example", "app:private"], hide_excluded:false, hidden_excluded_targets:[]})
 focusPanel.manageSection="apps"
 wait(30)
 compare(focusPanel.filteredIgnored.length, 2)
 var hide = findChild(focusPanel, "hideExcludedEntryButton")
 verify(hide !== null)
 compare(hide.text, "Hide")
 hide.clicked()
 compare(focusPanel.commandQueue[0][0], "excluded-entry-visibility")
 compare(focusPanel.commandQueue[0][1], "site:private.example")
 compare(focusPanel.commandQueue[0][2], "hide")
 wait(30)
 compare(focusPanel.filteredIgnored.length, 1)
 compare(focusPanel.filteredIgnored[0], "app:private")
 widget.snapshot = Object.assign({}, widget.snapshot, {hidden_excluded_targets:["site:private.example"]})
 compare(Object.keys(focusPanel.pendingHiddenEntries).length, 0)
 focusPanel.commandQueue=[]
 var reveal = findChild(focusPanel, "revealHiddenExcludedButton")
 verify(reveal.visible)
 reveal.clicked()
 wait(30)
 compare(focusPanel.filteredIgnored.length, 2)
 var unhide = findChild(focusPanel, "hideExcludedEntryButton")
 compare(unhide.text, "Unhide")
 unhide.clicked()
 compare(focusPanel.commandQueue[0][2], "show")
 widget.snapshot = Object.assign({}, widget.snapshot, {hidden_excluded_targets:[]})
 compare(Object.keys(focusPanel.pendingHiddenEntries).length, 0)
 focusPanel.opened=false
 verify(!focusPanel.revealHiddenExcluded)
 focusPanel.opened=true
 widget.snapshot=previous
 focusPanel.commandQueue=[]
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
 focusPanel.refreshMergeChoices()
 compare(focusPanel.mergeChoices.length,2)
 compare(focusPanel.mergeDestinations.length,1)
 compare(focusPanel.mergeDestinations[0].id,group.id)
 widget.snapshot=previous
 focusPanel.commandQueue=[]
 focusPanel.manageSection=""
 }
 function test_sections_and_groups() {
 compare(focusPanel.manageSection, "")
 focusPanel.manageSection="apps"; wait(30)
 var subdomains = findChild(focusPanel, "subdomainGroupButton")
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
 var warning = findChild(focusPanel, "warningButton")
 verify(warning.selected)
 warning.clicked()
 compare(focusPanel.commandQueue[0][0], "warning")
 compare(focusPanel.commandQueue[0][1], "off")
 verify(!warning.selected)
 compare(warning.text, "Warn before limit · Off")
 focusPanel.commandQueue=[]
 widget.snapshot = Object.assign({}, widget.snapshot, {warn_before_limit:false})
 verify(!warning.selected)
 warning.clicked()
 compare(focusPanel.commandQueue[0][1], "on")
 verify(warning.selected)
 widget.snapshot = Object.assign({}, widget.snapshot, {warn_before_limit:true})
 compare(focusPanel.pendingWarning, null)
 focusPanel.commandQueue=[]
 focusPanel.manageSection="groups"; focusPanel.expandedGroupId="site:one.example"; focusPanel.refreshMergeChoices(); wait(30)
 compare(focusPanel.mergeChoices.length, 2)
 verify(focusPanel.serviceConnected)
 var source = findChild(focusPanel, "mergeSource")
 compare(source.options.length, 2)
 compare(source.options[0].label, "One")
 compare(source.options[0].description, "one.example")
 source.value = "app:two"
 compare(source.currentIndex, 1)
 focusPanel.refreshMergeChoices()
 compare(source.value, "")
 compare(source.currentIndex, -1)

 focusPanel.manageSection="diagnostics"; wait(30)
 focusPanel.manageSection="data"; focusPanel.confirmClearHistory=true; wait(30)
 focusPanel.confirmClearHistory=false
 focusPanel.pausePickerOpen=true; wait(30)
 focusPanel.pausePickerOpen=false
 focusPanel.page="history"; wait(30)
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
