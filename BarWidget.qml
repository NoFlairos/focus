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
  property double statusNow: Date.now()
  readonly property bool serviceConnected: {
    var updated = Date.parse(String(snapshot.updated_at || ""))
    return isFinite(updated) && Math.abs(statusNow - updated) < 5000
  }
  readonly property string connectionIssue: !serviceConnected ? "Service offline"
    : snapshot.diagnostics && snapshot.diagnostics.browser_running === true
      && snapshot.diagnostics.browser_can_close_tabs === false ? "Reload extension"
    : snapshot.diagnostics && snapshot.diagnostics.browser_connection_expected === true
      && snapshot.diagnostics.browser_connected === false ? "Browser offline" : ""
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
    try {
      var next = JSON.parse(String(raw || "{}"))
      if (next && typeof next === "object") snapshot = next
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
    var name = String(target.name || target.id || "").trim()
    if (String(target.id || "").startsWith("site:")) return name
    var appId = String(target.id || "").replace(/^app:/, "")
    if (name.toLowerCase() === appId.toLowerCase()) {
      var browserApp = name.match(/^chrome-([^_]+)(?:__.*)?$/i)
      if (browserApp) {
        var domain = browserApp[1].replace(/^www\./i, "").toLowerCase()
        name = domain
      }
      else {
        var parts = name.split(".").filter(function(part) {
          return part && ["org", "com", "io", "net", "app", "desktop"].indexOf(part.toLowerCase()) === -1
        })
        if (parts.length) name = parts.map(function(part) {
          return part.charAt(0).toUpperCase() + part.slice(1)
        }).join(" ")
      }
    }
    return name ? name.charAt(0).toUpperCase() + name.slice(1) : "FOCUS"
  }

  function remainingLabel(seconds) {
    var value = Math.max(0, Math.floor(Number(seconds || 0)))
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
    fixedWidth: Math.max(Style.space(42),
      Math.min(Style.space(340), chips.implicitWidth + Style.spaceReal(14)
        + (connectionIndicator.visible ? connectionIndicator.width + Style.space(5) : 0)))
    Behavior on fixedWidth {
      NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
    }
    tooltipText: root.connectionIssue ? "Focus · " + root.connectionIssue
      + (root.connectionIssue === "Browser offline" ? "\nWebsite tracking and tab limits unavailable."
        : root.connectionIssue === "Reload extension" ? "\nTab closing unavailable. Reload Focus in chrome://extensions."
        : "\nTracking and limits unavailable.")
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

    Flickable {
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
          model: root.visibleTargets
          delegate: Rectangle {
            required property var modelData
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

        Text {
          visible: root.visibleTargets.length === 0
          text: "FOCUS"
          color: button.foreground
          font.family: button.fontFamily
          font.pixelSize: button.fontSize
          font.bold: true
        }
      }
    }
  }
}
