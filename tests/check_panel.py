# Instantiate the real panel with lightweight shell fixtures; requires QtTest.
from pathlib import Path
import shutil, tempfile, subprocess, os
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
module('Quickshell',{'Quickshell':(True,'import QtQuick\nQtObject { function execDetached(args) {} }')})
module('qs.Commons',{
'Style':(True,'''import QtQuick
QtObject { property int cornerRadius: 6; property var spacing: ({hairline: 1}); property var font: ({family: "Sans", body: 14, bodySmall: 12, caption: 10, title: 18, heading: 20}); function space(n) {return n;} }'''),
'Color':(True,'''import QtQuick
QtObject { property var popups: ({text: Qt.rgba(0.9,0.9,0.9,1), background: Qt.rgba(0.12,0.12,0.12,1)}) }''')})
module('qs.Ui',{
'TextField':(False,'''import QtQuick
import QtQuick.Controls as Controls
Controls.TextField { property color foreground; }'''),
'SearchableDropdown':(False,'''import QtQuick
Item { property string label; property string value; property var options: []; property bool showLabel; property color foreground; property color background; property string placeholderText; property string emptyText; property string triggerLabel; property bool popupOpen: false; signal changed(string value); implicitHeight: 32; function open(){popupOpen=true;} function close(){popupOpen=false;} }'''),
'Button':(False,'''import QtQuick
Item { property string text; property string tooltipText; signal clicked(); implicitHeight: 32; property color foreground; property color background; property bool bordered; property bool focusable; property bool leftAlign; property bool selected; property real fontSize; property real horizontalPadding; }'''),
'Panel':(False,'''import QtQuick
Item { property string moduleName; property bool manageIpc; property bool opened: true; property var bar: null; function close() {opened=false;} }'''),
'KeyboardPanel':(False,'''import QtQuick
Item { property var anchorItem; property var owner; property var bar; property bool open; property var focusTarget; property real contentWidth; property real contentHeight; width:contentWidth; height:contentHeight; function fittedContentWidth(n){return n;} function fittedContentHeight(n){return n;} }'''),
'PanelKeyCatcher':(False,'''import QtQuick
Item { signal closeRequested(); signal tabRequested(int direction); }''')})
shutil.copyfile('Panel.qml',root/'FocusPanel.qml')
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
 TestCase {
 name: "ManagePanel"; when:windowShown
 function test_sections_and_groups() {
 compare(focusPanel.manageSection, "")
 focusPanel.manageSection="apps"; wait(30)
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
''')

environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="", QT_QUICK_CONTROLS_STYLE="Basic")
result = subprocess.run(["/usr/lib/qt6/bin/qmltestrunner", "-import", str(modules), "-input", str(root)], env=environment)
temporary.cleanup()
raise SystemExit(result.returncode)
