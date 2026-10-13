import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.noflairos.focus-ratio"

  readonly property var panelItem: panelLoader.item
  readonly property bool opened: panelItem ? panelItem.opened === true : false
  readonly property bool popoutSwitchClosing: panelItem ? panelItem.popoutSwitchClosing === true : false
  readonly property string dataHome: Quickshell.env("XDG_DATA_HOME") || (Quickshell.env("HOME") + "/.local/share")
  readonly property string stateHome: Quickshell.env("XDG_STATE_HOME") || (Quickshell.env("HOME") + "/.local/state")
  readonly property string agentPath: dataHome + "/focus-ratio/focus_ratio_agent.py"
  readonly property string statePath: stateHome + "/focus-ratio/state.json"
  property var snapshot: ({ tracked: [], today: ({}), history: [] })
  property string snapshotText: ""
  property double statusNow: Date.now()
  // The agent rewrites state on change and at least every 10 s.
  readonly property bool serviceConnected: {
    var updated = Date.parse(String(snapshot.updated_at || ""))
    return isFinite(updated) && Math.abs(statusNow - updated) < 20000
  }
  // Status comes from the agent; only "service offline" is inferred here, from staleness.
  readonly property string connectionStatus: !serviceConnected ? "service_offline"
    : String((snapshot.diagnostics || {}).browser_status || "browser_closed")
  readonly property var connectionLabels: ({
    service_offline: "Service offline", reload_extension: "Reload extension", browser_offline: "Browser offline",
    connected: "Connected", connecting: "Connecting", browser_closed: "Browser closed" })
  readonly property string connectionLabel: connectionLabels[connectionStatus] || ""
  readonly property string connectionIssue: ["service_offline", "reload_extension", "browser_offline"]
    .indexOf(connectionStatus) >= 0 ? connectionLabel : ""
  readonly property double focusUntil: Number(snapshot.focus_until || 0) * 1000
  readonly property bool trackingPaused: snapshot.paused === true || snapshot.working === false
  readonly property var visibleTargets: (snapshot.tracked || []).filter(function(target) {
    return Number(target.visible_windows || 0) > 0
  })

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function injectPanel() {
    if (!panelItem) return
    if ("bar" in panelItem) panelItem.bar = root.bar
    if ("anchorItem" in panelItem) panelItem.anchorItem = button
    if ("widget" in panelItem) panelItem.widget = root
  }

  function open() { if (panelItem) panelItem.open() }
  function close() { if (panelItem) panelItem.close() }
  function toggle() { if (panelItem) panelItem.toggle() }
  function closeForPopoutSwitch() {
    if (panelItem) panelItem.closeForPopoutSwitch()
  }

  function loadSnapshot(raw) {
    raw = String(raw || "{}")
    if (raw === snapshotText) return
    try {
      var next = JSON.parse(raw)
      if (next && typeof next === "object") {
        snapshot = next
        snapshotText = raw
      }
    } catch (error) {
      // Keep the last good state during a transient file reload.
    }
  }

  function showDiagnostics() {
    if (!panelItem) return
    panelItem.page = "manage"
    panelItem.manageSection = "diagnostics"
    root.open()
  }

  function appLabel(target) {
    return String(target.name || target.id || "") || "FOCUS"
  }

  function remainingLabel(seconds) {
    var value = Math.max(0, Math.floor(Number(seconds || 0)))
    if (value >= 3600) return Math.floor(value / 3600) + "h" + String(Math.floor(value % 3600 / 60)).padStart(2, "0")
    return Math.floor(value / 60) + ":" + String(value % 60).padStart(2, "0")
  }

  onBarChanged: injectPanel()
  FileView {
    id: stateFile
    path: root.statePath
    watchChanges: true
    printErrors: false
    onLoaded: root.loadSnapshot(text())
    onFileChanged: reload()
  }

  Timer {
    interval: 2000
    running: true
    repeat: true
    onTriggered: {
      root.statusNow = Date.now()
      stateFile.reload()
    }
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: " "
    labelVisible: false
    hasVisualContent: true
    fontSize: Style.font.bodySmall
    fixedWidth: root.visibleTargets.length === 0
      ? Style.bar.iconSlot + (connectionIndicator.visible ? connectionIndicator.width + Style.space(5) + Style.spaceReal(7) : 0)
      : Math.min(Style.space(340), chips.implicitWidth + Style.spaceReal(14)
        + (connectionIndicator.visible ? connectionIndicator.width + Style.space(5) : 0))
    Behavior on fixedWidth {
      NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
    }
    tooltipText: root.connectionIssue ? "Focus · " + root.connectionIssue
      + (root.connectionIssue === "Browser offline" ? "\nWebsite tracking and tab limits unavailable."
        : root.connectionIssue === "Reload extension" ? "\nTab closing unavailable. Reload Focus in chrome://extensions."
        : "\nTracking and limits unavailable.")
      : root.focusUntil > root.statusNow ? "Focus session · until " + Qt.formatTime(new Date(root.focusUntil), "HH:mm")
      : root.trackingPaused ? "Focus · tracking paused"
      + (root.snapshot.idle && !root.snapshot.paused ? " while idle" : "")
      : root.visibleTargets.length ? root.visibleTargets.map(function(target) {
      return root.appLabel(target) + (target.category === "consumption"
        ? " · " + root.remainingLabel(target.remaining_seconds) + " left" : "")
    }).join("\n") : "Focus · no visible tracked app"
    onPressed: function(buttonCode) {
      if (buttonCode !== Qt.LeftButton) return
      if (root.connectionIssue && !root.opened) root.showDiagnostics()
      else root.toggle()
    }

    Rectangle {
      id: connectionIndicator
      objectName: "connectionIndicator"
      visible: root.connectionIssue !== ""
      anchors.left: parent.left
      anchors.leftMargin: Style.spaceReal(7)
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(16)
      height: width
      radius: width / 2
      color: "transparent"
      border.width: Style.spacing.hairline
      border.color: button.activeColor

      Text {
        anchors.centerIn: parent
        text: "!"
        color: button.activeColor
        font.family: button.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
      }
    }

    // Shown instead of app chips: centred in a standard icon slot so the bar's
    // active indicator lines up with it, like Omarchy's own icons.
    // Bar icons are font glyphs on the text baseline, not geometrically centred.
    // An invisible reference glyph, laid out like BarIconButton's, gives their
    // painted centre so the mark lines up with neighbouring icons in any font.
    Text {
      id: iconReference
      visible: false
      anchors.centerIn: parent
      text: String.fromCodePoint(0xF0765)  // nf-md-circle: symmetric, so its centre is the icon centre
      font.family: button.fontFamily
      font.pixelSize: Style.bar.iconFont
      renderType: Text.NativeRendering
    }
    TextMetrics {
      id: iconReferenceMetrics
      font: iconReference.font
      text: iconReference.text
    }

    FocusMark {
      id: logo
      objectName: "focusLogo"
      readonly property real iconCenterY: iconReference.y + iconReference.baselineOffset
        + iconReferenceMetrics.tightBoundingRect.y + iconReferenceMetrics.tightBoundingRect.height / 2
      visible: root.visibleTargets.length === 0
      x: connectionIndicator.visible
        ? connectionIndicator.x + connectionIndicator.width + Style.space(5)
        : (button.width - width) / 2
      y: iconCenterY - height / 2
      size: Style.bar.iconFont
      color: button.foreground
      accent: Color.accent
      session: root.focusUntil > root.statusNow
      active: session || (root.snapshot.working === true && root.snapshot.paused !== true)
      opacity: active ? 1 : 0.55
    }

    Flickable {
      visible: root.visibleTargets.length > 0
      anchors.left: parent.left
      anchors.leftMargin: Style.spaceReal(7)
        + (connectionIndicator.visible ? connectionIndicator.width + Style.space(5) : 0)
      anchors.verticalCenter: parent.verticalCenter
      width: Math.min(chips.implicitWidth, button.width - Style.spaceReal(14)
        - (connectionIndicator.visible ? connectionIndicator.width + Style.space(5) : 0))
      height: button.height
      contentWidth: chips.implicitWidth
      contentHeight: height
      clip: true
      boundsBehavior: Flickable.StopAtBounds

      Row {
        id: chips
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(5)

        Repeater {
          // Count model keeps chips alive across refreshes; data follows by index.
          model: root.visibleTargets.length
          delegate: Rectangle {
            required property int index
            readonly property var modelData: root.visibleTargets[index] || ({})
            readonly property bool focused: modelData.id === root.snapshot.focused_id
            implicitWidth: targetRow.implicitWidth + Style.space(10)
            height: Style.space(25)
            radius: Style.cornerRadius
            color: focused ? Qt.rgba(button.foreground.r, button.foreground.g,
              button.foreground.b, 0.12) : "transparent"

            Row {
              id: targetRow
              anchors.centerIn: parent
              spacing: Style.space(4)
              Rectangle {
                width: Style.space(6)
                height: width
                radius: width / 2
                anchors.verticalCenter: parent.verticalCenter
                color: modelData.category === "productive" ? "#2ecc71"
                  : modelData.category === "consumption" ? "#e67e22" : button.foreground
                opacity: root.snapshot.working ? 1 : 0.45
              }
              Text {
                width: Math.min(implicitWidth, Style.space(76))
                anchors.verticalCenter: parent.verticalCenter
                objectName: "barTargetLabel"
                textFormat: Text.PlainText
                text: root.appLabel(modelData)
                color: button.foreground
                font.family: button.fontFamily
                font.pixelSize: button.fontSize
                font.bold: true
                elide: Text.ElideRight
              }
              Text {
                visible: modelData.category === "consumption"
                anchors.verticalCenter: parent.verticalCenter
                text: visible ? "· " + root.remainingLabel(modelData.remaining_seconds) : ""
                color: button.foreground
                font.family: "monospace"
                font.pixelSize: button.fontSize
                font.bold: true
              }
            }
          }
        }

      }
    }
  }
}
