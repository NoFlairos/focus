import QtQuick
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Ui
import qs.Ui as Omarchy

Panel {
  id: root
  moduleName: "io.github.noflairos.focus-ratio"
  manageIpc: false

  property var widget: null
  property Item anchorItem: null
  property string page: "now"
  property string manageSection: ""
  property var pendingWarning: null
  readonly property bool savedWarning: !!(widget && widget.snapshot && widget.snapshot.warn_before_limit)
  readonly property bool warningEnabled: pendingWarning === null ? savedWarning : pendingWarning
  onSavedWarningChanged: {
    if (pendingWarning !== null && savedWarning === pendingWarning) {
      pendingWarning = null
      warningAckTimer.stop()
    }
  }
  function toggleWarning() {
    pendingWarning = !warningEnabled
    runAgent(["warning", pendingWarning ? "on" : "off"])
    warningAckTimer.restart()
  }
  Timer {
    id: warningAckTimer
    interval: 5000
    onTriggered: root.pendingWarning = null
  }
  property bool pausePickerOpen: false
  property bool confirmClearHistory: false
  property bool dataBusy: false
  property string dataFeedback: ""
  property string dataBeforeId: ""
  readonly property var dataAction: widget && widget.snapshot ? widget.snapshot.data_action || ({}) : ({})
  readonly property var weekly: widget && widget.snapshot ? widget.snapshot.weekly || ({}) : ({})
  readonly property var suggestions: widget && widget.snapshot ? widget.snapshot.suggestions || [] : []
  readonly property var subdomainRules: widget && widget.snapshot ? widget.snapshot.subdomain_rules || ({}) : ({})
  property var pendingSubdomainRules: ({})
  onSubdomainRulesChanged: {
    var pending = Object.assign({}, pendingSubdomainRules)
    Object.keys(pending).forEach(function(domain) {
      if (pending[domain] === root.subdomainRules[domain]) delete pending[domain]
    })
    pendingSubdomainRules = pending
  }
  Timer {
    id: subdomainAckTimer
    interval: 5000
    onTriggered: root.pendingSubdomainRules = ({})
  }
  function setSubdomainRule(domain, mode, family) {
    var pending = Object.assign({}, pendingSubdomainRules)
    pending[family || domain] = mode
    pendingSubdomainRules = pending
    runAgent(["subdomains", domain, mode])
    subdomainAckTimer.restart()
  }
  function siteScopes(row) {
    if (row.id.startsWith("site:")) return [row.id.slice(5)]
    var sites = (row.members || []).filter(function(id) { return id.startsWith("site:") }).sort()
    return sites.length ? [sites[0].slice(5)] : []
  }
  onDataActionChanged: {
    if (dataBusy && String(dataAction.id || "") !== dataBeforeId) {
      dataBusy = false
      dataFeedback = dataAction.message || "Done"
      dataAckTimer.stop()
    }
  }
  Timer {
    id: dataAckTimer
    interval: 6000
    onTriggered: { root.dataBusy = false; root.dataFeedback = "No confirmation. Check Diagnostics." }
  }
  function dataCommand(command) {
    dataBeforeId = String(dataAction.id || "")
    dataBusy = true
    dataFeedback = "Working…"
    runAgent(command)
    dataAckTimer.restart()
  }
  function startPause(duration) {
    pausePickerOpen = false
    pendingPaused = true
    pauseAckTimer.restart()
    runAgent(["pause", duration])
  }
  property string appSearch: ""
  property string appFilter: "all"
  property string expandedGroupId: ""
  property string detachingMember: ""
  property string detachFeedback: ""
  property var mergeChoices: []
  readonly property var mergeDestinations: mergeChoices.filter(function(row) { return row.configured })

  function matchesApp(id, name, category) {
    if (appFilter !== "all" && (pendingCategories[id] || category) !== appFilter) return false
    var row = tracked.find(function(entry) { return entry.id === id })
    var search = appSearch.trim().toLowerCase()
    return !search || [name, id].concat(row && row.members ? row.members : []).join(" ").toLowerCase().indexOf(search) >= 0
  }
  property var pendingHideExcluded: null
  readonly property bool savedHideExcluded: !widget || !widget.snapshot || widget.snapshot.hide_excluded !== false
  readonly property bool hideExcluded: pendingHideExcluded === null ? savedHideExcluded : pendingHideExcluded
  onSavedHideExcludedChanged: {
    if (pendingHideExcluded !== null && savedHideExcluded === pendingHideExcluded) {
      pendingHideExcluded = null
      excludedVisibilityTimer.stop()
    }
  }
  Timer {
    id: excludedVisibilityTimer
    interval: 5000
    onTriggered: root.pendingHideExcluded = null
  }
  function toggleExcludedVisibility() {
    pendingHideExcluded = !hideExcluded
    runAgent(["excluded-visibility", pendingHideExcluded ? "hide" : "show"])
    excludedVisibilityTimer.restart()
  }
  property bool revealHiddenExcluded: false
  property var pendingHiddenEntries: ({})
  readonly property var savedHiddenEntries: widget && widget.snapshot ? widget.snapshot.hidden_excluded_targets || [] : []
  readonly property var hiddenExcludedTargets: {
    var hidden = savedHiddenEntries.slice()
    Object.keys(pendingHiddenEntries).forEach(function(id) {
      var index = hidden.indexOf(id)
      if (pendingHiddenEntries[id] && index < 0) hidden.push(id)
      else if (!pendingHiddenEntries[id] && index >= 0) hidden.splice(index, 1)
    })
    return hidden
  }
  onSavedHiddenEntriesChanged: {
    var pending = Object.assign({}, pendingHiddenEntries)
    Object.keys(pending).forEach(function(id) {
      if ((root.savedHiddenEntries.indexOf(id) >= 0) === pending[id]) delete pending[id]
    })
    pendingHiddenEntries = pending
  }
  Timer {
    id: hiddenEntryAckTimer
    interval: 5000
    onTriggered: root.pendingHiddenEntries = ({})
  }
  onOpenedChanged: if (!opened) revealHiddenExcluded = false
  onHideExcludedChanged: if (hideExcluded) revealHiddenExcluded = false
  function setExcludedEntryHidden(id, hidden) {
    var pending = Object.assign({}, pendingHiddenEntries)
    pending[id] = hidden
    pendingHiddenEntries = pending
    runAgent(["excluded-entry-visibility", id, hidden ? "hide" : "show"])
    hiddenEntryAckTimer.restart()
  }
  readonly property var filteredIgnored: !hideExcluded && appFilter === "all" ? ignoredTargets.filter(function(id) {
    if (!root.revealHiddenExcluded && root.hiddenExcludedTargets.indexOf(id) >= 0) return false
    return !root.appSearch.trim() || (id + " " + root.displayName({id:id, name:id.split(":").slice(1).join(":")}))
      .toLowerCase().indexOf(root.appSearch.trim().toLowerCase()) >= 0
  }) : []
  readonly property int matchingAppCount: tracked.filter(function(row) {
    return row.configured && root.matchesApp(row.id, row.name, row.category)
  }).length
  Timer {
    id: detachAckTimer
    interval: 6000
    onTriggered: { root.detachingMember = ""; root.detachFeedback = "Could not confirm detach. Check Diagnostics." }
  }
  property string mergingSource: ""
  property string mergeFeedback: ""
  property double diagnosticNow: Date.now()
  readonly property var diagnostics: widget && widget.snapshot ? widget.snapshot.diagnostics || ({}) : ({})
  readonly property bool serviceConnected: widget && widget.snapshot && widget.snapshot.updated_at
    ? diagnosticNow - new Date(widget.snapshot.updated_at).getTime() < 10000 : false

  component ManageHeader: Omarchy.Button {
    property string label
    property string section
    property string statusText: ""
    visible: root.page === "manage"
    width: parent.width
    height: Style.space(40)
    text: label
    leftAlign: true
    foreground: root.textColor
    background: root.softSurface
    fontSize: Style.font.bodySmall
    focusable: true
    Text {
      anchors.right: parent.right
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      text: root.manageSection === parent.section ? "⌃" : "⌄"
      color: root.mutedText
      font.pixelSize: Style.font.body
    }
    Text {
      anchors.right: parent.right
      anchors.rightMargin: Style.space(34)
      anchors.verticalCenter: parent.verticalCenter
      text: parent.statusText
      color: root.mutedText
      font.pixelSize: Style.font.caption
    }
    onClicked: {
      root.finishScheduleEditing()
      root.manageSection = root.manageSection === section ? "" : section
      if (root.manageSection === "groups" && !root.mergingSource) root.refreshMergeChoices()
    }
  }

  component TargetPicker: Omarchy.SearchableDropdown {
    property var model: []
    readonly property int currentIndex: model.findIndex(function(entry) { return entry.id === value })
    showLabel: false
    foreground: root.textColor
    background: root.solidPopup
    placeholderText: "Search apps or sites…"
    emptyText: "No matching entry"
    triggerLabel: value ? "" : "Choose an entry"
    options: model.map(function(entry) {
      return { value: entry.id, label: entry.name, description: entry.identity }
    })
  }

  function refreshMergeChoices() {
    mergeChoices = tracked.filter(function(row) { return root.ignoredTargets.indexOf(row.id) < 0 }).map(function(row) {
      return { id: row.id, name: row.name, identity: row.id.split(":").slice(1).join(":"),
        category: row.category, quota: Math.round(Number(row.quota_seconds) / 60), configured: !!row.configured }
    })
    mergeSource.value = ""
    mergeDestination.value = ""
  }

  Timer {
    interval: 2000
    running: true
    repeat: true
    onTriggered: root.diagnosticNow = Date.now()
  }
  Timer {
    id: mergeAckTimer
    interval: 6000
    onTriggered: {
      root.mergingSource = ""
      root.mergeFeedback = "Could not confirm merge. Check the local service and try again."
    }
  }

  readonly property var tracked: widget && widget.snapshot && widget.snapshot.tracked ? widget.snapshot.tracked : []
  readonly property int activeCount: tracked.filter(function(row) {
    return Number(row.visible_windows || 0) > 0
  }).length
  readonly property var history: widget && widget.snapshot && widget.snapshot.history ? widget.snapshot.history : []
  readonly property var today: widget && widget.snapshot && widget.snapshot.today ? widget.snapshot.today : ({})
  readonly property real productiveToday: Math.max(0, Number(today.productive || 0))
  readonly property real neutralToday: Math.max(0, Number(today.neutral || 0))
  readonly property real consumedToday: Math.max(0, Number(today.consumption || 0))
  readonly property real classifiedToday: productiveToday + neutralToday + consumedToday
  readonly property real productiveActivityShare: classifiedToday > 0 ? productiveToday / classifiedToday : 0
  readonly property real neutralActivityShare: classifiedToday > 0 ? neutralToday / classifiedToday : 0
  readonly property var savedIgnoredTargets: widget && widget.snapshot && widget.snapshot.ignored_targets
    ? widget.snapshot.ignored_targets : []
  property var pendingExcluded: []
  property var pendingUnexcluded: []
  readonly property var ignoredTargets: savedIgnoredTargets.filter(function(id) {
    return pendingUnexcluded.indexOf(id) < 0
  }).concat(pendingExcluded.filter(function(id) {
    return savedIgnoredTargets.indexOf(id) < 0
  }))
  readonly property int reviewCount: tracked.filter(function(row) {
    return !row.configured && ignoredTargets.indexOf(row.id) < 0
  }).length
  readonly property var tabItems: reviewCount > 0
    ? [{ id: "now", label: "Now" }, { id: "review", label: "Review" },
       { id: "manage", label: "Manage" }, { id: "history", label: "History" }]
    : [{ id: "now", label: "Now" }, { id: "manage", label: "Manage" },
       { id: "history", label: "History" }]
  readonly property real maxTodaySeconds: Math.max(1, tracked.reduce(function(best, row) {
    return Math.max(best, Number(row.today_seconds || 0))
  }, 0))
  readonly property bool working: !!(widget && widget.snapshot && widget.snapshot.working)
  readonly property bool savedPaused: !!(widget && widget.snapshot && widget.snapshot.paused)
  property var pendingPaused: null
  readonly property bool paused: pendingPaused !== null ? pendingPaused : savedPaused
  readonly property var savedSchedule: widget && widget.snapshot && widget.snapshot.schedule
    ? widget.snapshot.schedule : ({ weekdays: [0, 1, 2, 3, 4], start: "08:00", end: "17:00" })
  property string scheduleStartDraft: "08:00"
  property string scheduleEndDraft: "17:00"
  property bool scheduleTimeEdited: false
  property var scheduleAllDayDraft: null
  readonly property bool scheduleAllDay: scheduleAllDayDraft !== null
    ? scheduleAllDayDraft : savedSchedule.start === savedSchedule.end
  property var scheduleDraft: null
  property var pendingSchedule: null
  property string scheduleFeedback: ""
  readonly property var schedule: scheduleDraft || savedSchedule
  readonly property bool scheduleHasChanges: JSON.stringify(schedule.weekdays) !== JSON.stringify(savedSchedule.weekdays)
    || scheduleAllDay !== (savedSchedule.start === savedSchedule.end)
    || (!scheduleAllDay && (scheduleStartDraft.trim() !== savedSchedule.start
      || scheduleEndDraft.trim() !== savedSchedule.end))
  readonly property color textColor: Color.popups.text
  readonly property color solidPopup: Qt.rgba(Color.popups.background.r,
    Color.popups.background.g, Color.popups.background.b, 1)
  readonly property color mutedText: Qt.rgba(textColor.r, textColor.g, textColor.b, 0.62)
  readonly property color softSurface: Qt.rgba(textColor.r, textColor.g, textColor.b, 0.055)
  readonly property color hoverSurface: Qt.rgba(textColor.r, textColor.g, textColor.b, 0.11)
  readonly property color outlineColor: Qt.rgba(textColor.r, textColor.g, textColor.b, 0.18)
  readonly property color productiveColor: "#2ecc71"
  readonly property color neutralColor: Qt.rgba(textColor.r, textColor.g, textColor.b, 0.52)
  readonly property color consumptionColor: "#e67e22"
  property var pendingCategories: ({})
  property var pendingQuotas: ({})
  property var pendingLimitActions: ({})
  property var commandQueue: []

  function modelRow(row) {
    var scopes = root.siteScopes(row)
    return {
      targetId: String(row.id || ""),
      targetName: String(row.name || ""),
      targetCategory: String(row.category || "neutral"),
      quotaSeconds: Number(row.quota_seconds || 600),
      limitAction: String(row.limit_action || "close"),
      usedSeconds: Number(row.used_seconds || 0),
      visibleWindows: Number(row.visible_windows || 0),
      todaySeconds: Number(row.today_seconds || 0),
      linked: !!row.linked,
      memberIds: JSON.stringify(row.members || []),
      siteScopeIds: JSON.stringify(scopes),
      domainFamily: String(row.grouping_scope || scopes[0] || ""),
      domainFamilies: JSON.stringify(row.grouping_scopes || scopes),
      configured: !!row.configured,
      focused: !!row.focused
    }
  }

  function syncTracked() {
    var incoming = root.tracked
    var wanted = {}
    for (var i = 0; i < incoming.length; i++) {
      var row = incoming[i]
      wanted[row.id] = true
      var flat = modelRow(row)
      var found = -1
      for (var j = 0; j < trackedModel.count; j++) {
        if (trackedModel.get(j).targetId === row.id) {
          found = j
          break
        }
      }
      if (found < 0) trackedModel.insert(i, flat)
      else {
        if (found !== i) trackedModel.move(found, i, 1)
        var current = trackedModel.get(i)
        for (var role in flat) {
          if (current[role] !== flat[role]) trackedModel.setProperty(i, role, flat[role])
        }
      }
      if (root.pendingCategories[row.id] === row.category) {
        var categories = Object.assign({}, root.pendingCategories)
        delete categories[row.id]
        root.pendingCategories = categories
      }
      if (root.pendingQuotas[row.id] === Math.round(Number(row.quota_seconds || 600) / 60)) {
        var quotas = Object.assign({}, root.pendingQuotas)
        delete quotas[row.id]
        root.pendingQuotas = quotas
      }
      if (root.pendingLimitActions[row.id] === (row.limit_action || "close")) {
        var actions = Object.assign({}, root.pendingLimitActions)
        delete actions[row.id]
        root.pendingLimitActions = actions
      }
    }
    for (var k = trackedModel.count - 1; k >= 0; k--) {
      if (!wanted[trackedModel.get(k).targetId]) trackedModel.remove(k)
    }
  }

  onTrackedChanged: {
    syncTracked()
    if (detachingMember && tracked.some(function(row) {
      return row.id === root.detachingMember && (!row.members || row.members.length === 1)
    })) {
      detachingMember = ""
      detachFeedback = "Member detached"
      detachAckTimer.stop()
      refreshMergeChoices()
    }
    if (mergingSource && !tracked.some(function(row) { return row.id === root.mergingSource })) {
      mergingSource = ""
      mergeFeedback = "Merged"
      mergeAckTimer.stop()
      refreshMergeChoices()
    }
  }
  onReviewCountChanged: if (reviewCount === 0 && page === "review") page = "now"
  onSavedIgnoredTargetsChanged: {
    pendingExcluded = pendingExcluded.filter(function(id) { return savedIgnoredTargets.indexOf(id) < 0 })
    pendingUnexcluded = pendingUnexcluded.filter(function(id) { return savedIgnoredTargets.indexOf(id) >= 0 })
  }
  onSavedScheduleChanged: {
    if (pendingSchedule && JSON.stringify(savedSchedule) === JSON.stringify(pendingSchedule)) {
      pendingSchedule = null
      scheduleDraft = null
      scheduleAllDayDraft = null
      scheduleFeedback = "Schedule saved"
      scheduleAckTimer.stop()
      scheduleTimeEdited = false
    }
    if (!scheduleTimeEdited) {
      scheduleStartDraft = savedSchedule.start
      scheduleEndDraft = savedSchedule.end
    }
  }
  onSavedPausedChanged: {
    if (pendingPaused !== null && savedPaused === pendingPaused) {
      pendingPaused = null
      pauseAckTimer.stop()
    }
  }
  Component.onCompleted: {
    syncTracked()
    scheduleStartDraft = savedSchedule.start
    scheduleEndDraft = savedSchedule.end
  }

  ListModel { id: trackedModel }

  Timer {
    id: pauseAckTimer
    interval: 5000
    onTriggered: root.pendingPaused = null
  }

  Timer {
    id: commandTimer
    interval: 50
    repeat: true
    onTriggered: {
      if (!root.commandQueue.length) {
        stop()
        return
      }
      var next = root.commandQueue[0]
      root.commandQueue = root.commandQueue.slice(1)
      Quickshell.execDetached(["python3", root.widget.agentPath].concat(next))
      if (!root.commandQueue.length) stop()
    }
  }

  function runAgent(args) {
    if (!widget) return
    commandQueue = commandQueue.concat([args])
    if (!commandTimer.running) commandTimer.start()
  }

  function setSchedule(next) {
    if (JSON.stringify(next) === JSON.stringify(schedule)) return
    scheduleDraft = next
    scheduleFeedback = ""
  }

  function toggleScheduleDay(day) {
    var days = schedule.weekdays.slice()
    var index = days.indexOf(day)
    if (index < 0) days.push(day)
    else days.splice(index, 1)
    days.sort(function(a, b) { return a - b })
    setSchedule({ weekdays: days, start: schedule.start, end: schedule.end })
  }

  function finishScheduleEditing() {
    scheduleStart.deselect()
    scheduleEnd.deselect()
    if (scheduleStart.activeFocus || scheduleEnd.activeFocus)
      keyCatcher.forceActiveFocus()
  }

  function saveSchedule() {
    var start = scheduleAllDay ? "00:00" : scheduleStart.text.trim()
    var end = scheduleAllDay ? "00:00" : scheduleEnd.text.trim()
    var validTime = /^([01][0-9]|2[0-3]):[0-5][0-9]$/
    if (!validTime.test(start) || !validTime.test(end)) {
      scheduleFeedback = "Use 24-hour time, for example 09:30"
      return
    }
    finishScheduleEditing()
    var next = { weekdays: schedule.weekdays.slice(), start: start, end: end }
    if (JSON.stringify(next) === JSON.stringify(savedSchedule)) {
      scheduleDraft = null
      scheduleTimeEdited = false
      scheduleFeedback = "No changes to save"
      return
    }
    scheduleDraft = next
    pendingSchedule = next
    scheduleFeedback = "Saving schedule…"
    runAgent(["schedule", next.weekdays.join(","), next.start, next.end])
    scheduleAckTimer.restart()
  }

  function excludeTarget(id) {
    pendingExcluded = pendingExcluded.concat([id])
    runAgent(["exclude", id])
  }

  function unexcludeTarget(id) {
    pendingUnexcluded = pendingUnexcluded.concat([id])
    runAgent(["unexclude", id])
  }

  Timer {
    id: scheduleAckTimer
    interval: 6000
    onTriggered: {
      root.pendingSchedule = null
      root.scheduleFeedback = "Could not confirm save · try again"
    }
  }

  function togglePause() {
    if (!widget) return
    var next = !paused
    pendingPaused = next
    pauseAckTimer.restart()
    runAgent(["pause", next ? "on" : "off"])
  }

  function formatTime(seconds) {
    seconds = Math.max(0, Number(seconds || 0))
    return Math.floor(seconds / 60) + ":" + String(Math.floor(seconds % 60)).padStart(2, "0")
  }

  function formatElapsed(seconds) {
    seconds = Math.max(0, Number(seconds || 0))
    if (seconds < 3600) return Math.floor(seconds / 60) + "m "
      + String(Math.floor(seconds % 60)).padStart(2, "0") + "s"
    return Math.floor(seconds / 3600) + "h "
      + String(Math.floor(seconds % 3600 / 60)).padStart(2, "0") + "m"
  }

  function minutes(value) {
    return Math.round(Number(value || 0)) + "m"
  }

  function displayName(target) {
    return root.widget ? root.widget.appLabel(target) : String(target.name || target.id || "")
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.widget || root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(448))
    contentHeight: panel.fittedContentHeight(Math.min(
      Style.space(560), content.implicitHeight + Style.space(28)))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      TapHandler {
        onTapped: function(eventPoint, button) {
          var fields = [scheduleStart, scheduleEnd]
          for (var i = 0; i < fields.length; i++) {
            var point = fields[i].mapFromItem(keyCatcher, eventPoint.position.x, eventPoint.position.y)
            if (fields[i].visible && fields[i].contains(point)) return
          }
          root.finishScheduleEditing()
        }
      }
      onCloseRequested: {
        if (mergeSource.popupOpen) mergeSource.close()
        else if (mergeDestination.popupOpen) mergeDestination.close()
        else root.close()
      }
      onTabRequested: function(direction) {
        if (mergeSource.popupOpen || mergeDestination.popupOpen) return
        if (root.bar) root.bar.switchPanelFrom(root.widget || root, direction)
      }

      Rectangle {
        anchors.fill: parent
        radius: Style.cornerRadius
        color: root.solidPopup
      }

      Flickable {
        id: flick
        objectName: "activityScroll"
        anchors.fill: parent
        anchors.margins: Style.space(12)
        contentWidth: content.width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        WheelHandler {
          target: null
          acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
          onWheel: function(event) {
            var delta = event.pixelDelta.y !== 0
              ? event.pixelDelta.y * 1.8 : event.angleDelta.y / 120 * Style.space(140)
            flick.contentY = Math.max(0, Math.min(flick.contentHeight - flick.height,
              flick.contentY - delta))
            event.accepted = true
          }
        }

        Column {
          id: content
          width: Math.max(1, flick.width - Style.space(8))
          spacing: Style.space(12)

          Column {
            id: header
            width: parent.width
            spacing: Style.space(8)

            Row {
              width: parent.width
              spacing: Style.space(8)
              Text {
                width: parent.width - screenTimeText.implicitWidth - pauseButton.width - parent.spacing * 2
                text: "Focus"
                textFormat: Text.PlainText
                color: root.textColor
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.heading
                anchors.verticalCenter: parent.verticalCenter
                font.bold: true
              }
              Text {
                id: screenTimeText
                anchors.verticalCenter: parent.verticalCenter
                text: "Today’s screen time " + (root.today.screen_seconds !== undefined
                  ? root.formatElapsed(root.today.screen_seconds) : "—")
                color: root.mutedText
                font.pixelSize: Style.font.caption
                HoverHandler { id: screenTimeHover }
                ToolTip.visible: screenTimeHover.hovered
                ToolTip.delay: 500
                ToolTip.text: "Visible apps counted once during tracking hours"
                  + (root.today.screen_started_at
                    ? " · recorded since " + Qt.formatDateTime(new Date(root.today.screen_started_at), "HH:mm") : "")
              }
              Rectangle {
                id: pauseButton
                width: pauseLabel.implicitWidth + Style.space(18)
                height: Style.space(28)
                radius: Style.cornerRadius
                color: root.hoverSurface
                Text {
                  id: pauseLabel
                  anchors.centerIn: parent
                  text: root.paused ? "RESUME" : "PAUSE"
                  color: root.textColor
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.paused ? root.togglePause() : root.pausePickerOpen = !root.pausePickerOpen
                }
              }
            }

            Row {
              visible: root.pausePickerOpen
              width: parent.width
              spacing: Style.space(4)
              Repeater {
                model: [{label:"15 min",value:"15"}, {label:"1 hour",value:"60"},
                  {label:"Tomorrow",value:"tomorrow"}, {label:"Until resumed",value:"on"}]
                delegate: Omarchy.Button {
                  required property var modelData
                  width: (parent.width - Style.space(12)) / 4
                  text: modelData.label
                  foreground: root.textColor
                  fontSize: Style.font.caption
                  horizontalPadding: Style.space(3)
                  focusable: true
                  bordered: true
                  onClicked: root.startPause(modelData.value)
                }
              }
            }
            Text {
              visible: root.paused && !!(root.widget && root.widget.snapshot && root.widget.snapshot.pause_until)
              text: visible ? "Resumes " + Qt.formatDateTime(new Date(root.widget.snapshot.pause_until * 1000), "ddd HH:mm") : ""
              color: root.mutedText
              font.pixelSize: Style.font.caption
            }

            Rectangle {
              width: parent.width
              height: Style.space(7)
              radius: height / 2
              color: root.hoverSurface
              clip: true

              Row {
                anchors.fill: parent
                spacing: 0
                Rectangle {
                  width: parent.width * root.productiveActivityShare
                  height: parent.height
                  color: root.productiveColor
                  Behavior on width { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                }
                Rectangle {
                  width: parent.width * root.neutralActivityShare
                  height: parent.height
                  color: root.neutralColor
                  Behavior on width { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                }
                Rectangle {
                  width: root.classifiedToday > 0
                    ? parent.width * root.consumedToday / root.classifiedToday : 0
                  height: parent.height
                  color: root.consumptionColor
                  Behavior on width { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                }
              }
            }

            Row {
              width: parent.width
              spacing: Style.space(6)

              Text {
                width: (parent.width - parent.spacing * 2) / 3
                text: "●  Productive  " + root.minutes(root.productiveToday)
                color: root.productiveColor
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }
              Text {
                width: (parent.width - parent.spacing * 2) / 3
                text: "●  Neutral  " + root.minutes(root.neutralToday)
                color: root.neutralColor
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
              }
              Text {
                width: (parent.width - parent.spacing * 2) / 3
                text: "●  Consumed  " + root.minutes(root.consumedToday)
                color: root.consumptionColor
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignRight
                elide: Text.ElideRight
              }
            }
          }

          Rectangle {
            width: parent.width
            height: Style.space(38)
            radius: Style.cornerRadius
            color: root.softSurface
            border.width: Style.spacing.hairline
            border.color: root.outlineColor

            Row {
              id: tabs
              anchors.fill: parent
              anchors.margins: Style.space(3)
              spacing: Style.space(3)

              Repeater {
                model: root.tabItems
                delegate: Rectangle {
                  required property var modelData
                  readonly property bool selected: root.page === modelData.id
                  width: (tabs.width - tabs.spacing * (root.tabItems.length - 1)) / root.tabItems.length
                  height: tabs.height
                  radius: Style.cornerRadius
                  color: selected ? root.textColor : "transparent"

                  Text {
                    anchors.centerIn: parent
                    text: modelData.label
                    textFormat: Text.PlainText
                    color: parent.selected ? Color.popups.background : root.textColor
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }
                  MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.page = modelData.id
                  }
                }
              }
            }
          }

          Column {
            visible: root.page === "now" || root.page === "review" || root.page === "manage"
            width: parent.width
            spacing: Style.space(10)

            ManageHeader { label: "Tracking schedule"; section: "schedule" }

            Rectangle {
              visible: root.page === "manage" && root.manageSection === "schedule"
              width: parent.width
              implicitHeight: scheduleContent.implicitHeight + Style.space(24)
              radius: Style.cornerRadius
              color: root.softSurface
              border.width: Style.spacing.hairline
              border.color: root.outlineColor

              Column {
                id: scheduleContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Style.space(12)
                spacing: Style.space(9)

                Row {
                  width: parent.width
                  height: Style.space(26)
                  Text {
                    width: parent.width - saveScheduleButton.width
                    height: parent.height
                    text: "Days & hours"
                    color: root.textColor
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                    verticalAlignment: Text.AlignVCenter
                  }
                  Omarchy.Button {
                    id: saveScheduleButton
                    readonly property bool hasChanges: root.scheduleHasChanges
                    width: Style.space(64)
                    height: parent.height
                    text: root.pendingSchedule ? "Saving…" : hasChanges ? "Save" : "Saved"
                    foreground: hasChanges ? root.textColor : root.mutedText
                    fontSize: Style.font.caption
                    horizontalPadding: Style.space(6)
                    bordered: hasChanges
                    focusable: true
                    enabled: !root.pendingSchedule && hasChanges
                    onClicked: root.saveSchedule()
                  }
                }

                Row {
                  id: scheduleDays
                  width: parent.width
                  height: Style.space(30)
                  spacing: Style.space(4)
                  Repeater {
                    model: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                    delegate: Omarchy.Button {
                      required property int index
                      required property string modelData
                      selected: root.schedule.weekdays.indexOf(index) >= 0
                      width: (scheduleDays.width - scheduleDays.spacing * 6) / 7
                      height: scheduleDays.height
                      text: modelData
                      foreground: root.textColor
                      fontSize: Style.font.caption
                      horizontalPadding: Style.space(4)
                      focusable: true
                      enabled: !root.pendingSchedule
                      onClicked: root.toggleScheduleDay(index)
                    }
                  }
                }

                Row {
                  id: scheduleMode
                  width: parent.width
                  height: Style.space(28)
                  spacing: Style.space(5)
                  Repeater {
                    model: ["All day", "Custom hours"]
                    delegate: Omarchy.Button {
                      required property int index
                      required property string modelData
                      selected: root.scheduleAllDay === (index === 0)
                      width: (scheduleMode.width - scheduleMode.spacing) / 2
                      height: scheduleMode.height
                      text: modelData
                      foreground: root.textColor
                      fontSize: Style.font.caption
                      horizontalPadding: Style.space(4)
                      focusable: true
                      enabled: !root.pendingSchedule
                      onClicked: {
                          root.finishScheduleEditing()
                          root.scheduleAllDayDraft = index === 0
                          root.scheduleTimeEdited = true
                          if (index === 1 && root.scheduleStartDraft === root.scheduleEndDraft) {
                            root.scheduleStartDraft = "08:00"
                            root.scheduleEndDraft = "17:00"
                          }
                          root.scheduleFeedback = ""
                        }
                    }
                  }
                }

                Rectangle {
                  visible: !root.scheduleAllDay
                  width: parent.width
                  height: Style.space(42)
                  radius: Style.cornerRadius
                  color: root.softSurface
                  Row {
                    anchors.fill: parent
                    TextField {
                      id: scheduleStart
                      width: (parent.width - timeSeparator.width) / 2
                      height: parent.height
                      enabled: !root.pendingSchedule
                      text: root.scheduleStartDraft
                      maximumLength: 5
                      horizontalAlignment: Text.AlignHCenter
                      verticalAlignment: Text.AlignVCenter
                      font.family: "monospace"
                      font.pixelSize: Style.font.body
                      color: root.textColor
                      selectByMouse: true
                      Accessible.name: "Tracking start time"
                      onAccepted: root.saveSchedule()
                      background: Rectangle {
                        radius: Style.cornerRadius
                        color: scheduleStart.activeFocus ? root.hoverSurface : "transparent"
                      }
                      onTextEdited: {
                        root.scheduleTimeEdited = true
                        root.scheduleStartDraft = text
                        root.scheduleFeedback = ""
                      }
                    }
                    Text {
                      id: timeSeparator
                      width: Style.space(24)
                      height: parent.height
                      text: "→"
                      horizontalAlignment: Text.AlignHCenter
                      verticalAlignment: Text.AlignVCenter
                      color: root.mutedText
                      font.pixelSize: Style.font.bodySmall
                    }
                    TextField {
                      id: scheduleEnd
                      width: (parent.width - timeSeparator.width) / 2
                      height: parent.height
                      enabled: !root.pendingSchedule
                      text: root.scheduleEndDraft
                      maximumLength: 5
                      horizontalAlignment: Text.AlignHCenter
                      verticalAlignment: Text.AlignVCenter
                      font.family: "monospace"
                      font.pixelSize: Style.font.body
                      color: root.textColor
                      selectByMouse: true
                      Accessible.name: "Tracking end time"
                      onAccepted: root.saveSchedule()
                      background: Rectangle {
                        radius: Style.cornerRadius
                        color: scheduleEnd.activeFocus ? root.hoverSurface : "transparent"
                      }
                      onTextEdited: {
                        root.scheduleTimeEdited = true
                        root.scheduleEndDraft = text
                        root.scheduleFeedback = ""
                      }
                    }
                  }
                }

                Text {
                  width: parent.width
                  text: root.scheduleFeedback && ["Schedule saved", "No changes to save", "Saving schedule…"].indexOf(root.scheduleFeedback) < 0
                    ? root.scheduleFeedback
                    : root.scheduleHasChanges && !root.pendingSchedule ? "Unsaved changes"
                    : root.schedule.weekdays.length === 0 ? "Select a day to enable tracking"
                    : root.scheduleAllDay ? "Full day · on selected days"
                    : scheduleStart.text === scheduleEnd.text ? "Local time · full day"
                    : scheduleStart.text > scheduleEnd.text ? "Local time · ends the following day"
                    : "Local time · 24-hour format"
                  color: root.mutedText
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.WordWrap
                }

              }
            }

            ManageHeader { label: "Groups"; section: "groups" }
            Column {
              visible: root.page === "manage" && root.manageSection === "groups"
              width: parent.width
              spacing: Style.space(9)
              Text { text: "Combine"; color: root.mutedText; font.pixelSize: Style.font.caption }
              TargetPicker {
                id: mergeSource
                objectName: "mergeSource"
                width: parent.width
                model: root.mergeChoices
                enabled: !root.mergingSource && !root.detachingMember
                onChanged: root.mergeFeedback = ""
              }
              Text { text: "With · keep these settings"; color: root.mutedText; font.pixelSize: Style.font.caption }
              TargetPicker {
                id: mergeDestination
                objectName: "mergeDestination"
                width: parent.width
                model: root.mergeDestinations
                enabled: !root.mergingSource && !root.detachingMember
                onChanged: root.mergeFeedback = ""
              }
              Text {
                width: parent.width
                text: {
                  var target = root.mergeDestinations[mergeDestination.currentIndex]
                  return target ? "Keeps " + target.category + (target.category === "consumption" ? " · " + target.quota + " min/hour" : "")
                    + ". Histories are combined permanently. Future use counts once, even when both are open."
                    : root.mergeChoices.length < 2 ? "Save one entry to start a group."
                    : "Choose the settings to keep."
                }
                color: root.mutedText
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
              Omarchy.Button {
                width: parent.width
                text: root.mergingSource ? "Merging…" : "Merge entries"
                enabled: root.serviceConnected && !root.mergingSource && !root.detachingMember && root.mergeChoices.length > 1
                  && mergeSource.currentIndex >= 0 && mergeDestination.currentIndex >= 0
                  && mergeSource.value !== mergeDestination.value
                foreground: root.textColor
                bordered: true
                focusable: true
                fontSize: Style.font.bodySmall
                opacity: enabled ? 1 : 0.4
                onClicked: {
                  var source = root.mergeChoices[mergeSource.currentIndex].id
                  var destination = root.mergeDestinations[mergeDestination.currentIndex].id
                  root.mergingSource = source
                  root.mergeFeedback = ""
                  root.runAgent(["merge", source, destination])
                  mergeAckTimer.restart()
                }
              }
              Text {
                width: parent.width
                visible: text.length > 0
                text: root.mergeFeedback
                color: root.mutedText
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
              Text {
                width: parent.width
                visible: root.detachFeedback.length > 0
                text: root.detachFeedback
                color: root.mutedText
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
              Repeater {
                model: root.suggestions
                delegate: Column {
                  required property var modelData
                  width: parent.width
                  spacing: Style.space(5)
                  Text {
                    width: parent.width
                    objectName: "suggestionLabel"
                    textFormat: Text.PlainText
                    text: modelData.name + " · " + (modelData.reason || "Possible group")
                    color: root.textColor
                    font.pixelSize: Style.font.bodySmall
                  }
                  Text {
                    width: parent.width
                    text: (modelData.source_domain || modelData.source.split(":").slice(1).join(":"))
                      + " → " + (modelData.destination_domain || modelData.destination.split(":").slice(1).join(":"))
                    textFormat: Text.PlainText
                    color: root.mutedText
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                  }
                  Row {
                    spacing: Style.space(6)
                    Omarchy.Button {
                      text: "Review"
                      foreground: root.textColor
                      fontSize: Style.font.caption
                      focusable: true
                      enabled: !root.mergingSource && !root.detachingMember
                      onClicked: {
                        root.refreshMergeChoices()
                        mergeSource.value = modelData.source
                        mergeDestination.value = modelData.destination
                      }
                    }
                    Omarchy.Button {
                      text: "Dismiss"
                      foreground: root.mutedText
                      fontSize: Style.font.caption
                      focusable: true
                      onClicked: root.runAgent(["dismiss-suggestion", modelData.source, modelData.destination])
                    }
                  }
                }
              }
              Repeater {
                model: trackedModel
                delegate: Column {
                  id: savedGroup
                  required property string targetId
                  required property string targetName
                  required property string memberIds
                  readonly property var members: JSON.parse(memberIds)
                  readonly property var modelData: ({id: targetId, name: targetName, members: members})
                  visible: members.length > 1
                  width: parent.width
                  spacing: Style.space(7)
                  Omarchy.Button {
                    width: parent.width
                    text: savedGroup.modelData.name + " · " + savedGroup.modelData.members.length + " members"
                    foreground: root.textColor
                    fontSize: Style.font.bodySmall
                    leftAlign: true
                    bordered: true
                    focusable: true
                    selected: root.expandedGroupId === savedGroup.modelData.id
                    onClicked: root.expandedGroupId = root.expandedGroupId === savedGroup.modelData.id ? "" : savedGroup.modelData.id
                  }
                  Column {
                    visible: root.expandedGroupId === savedGroup.modelData.id
                    width: parent.width
                    spacing: Style.space(7)
                    Repeater {
                      model: savedGroup.modelData.members
                      delegate: Row {
                        required property string modelData
                        width: parent.width
                        spacing: Style.space(8)
                        Text {
                          width: parent.width - detachButton.width - parent.spacing
                          height: detachButton.height
                          text: root.displayName({id: modelData, name: modelData.split(":").slice(1).join(":")})
                            + (modelData.startsWith("app:") ? " · app" : " · site")
                          textFormat: Text.PlainText
                          color: root.textColor
                          font.pixelSize: Style.font.bodySmall
                          verticalAlignment: Text.AlignVCenter
                          elide: Text.ElideMiddle
                        }
                        Omarchy.Button {
                          id: detachButton
                          text: root.detachingMember === modelData ? "Detaching…" : "Detach"
                          foreground: root.textColor
                          fontSize: Style.font.caption
                          focusable: true
                          bordered: true
                          enabled: root.serviceConnected && !root.detachingMember && !root.mergingSource
                          onClicked: {
                            root.detachingMember = modelData
                            root.detachFeedback = ""
                            root.runAgent(["unlink", modelData])
                            detachAckTimer.restart()
                          }
                        }
                      }
                    }
                  }
                }
              }
            }

            ManageHeader { label: "Apps & sites"; section: "apps" }
            Column {
              visible: root.page === "manage" && root.manageSection === "apps"
              width: parent.width
              spacing: Style.space(8)
              Omarchy.Button {
                width: parent.width
                objectName: "warningButton"
                text: "Warn before limit · " + (root.warningEnabled ? "On" : "Off")
                tooltipText: "Up to 2 minutes before the limit; half the quota for shorter limits."
                selected: root.warningEnabled
                foreground: root.textColor
                fontSize: Style.font.bodySmall
                focusable: true
                onClicked: root.toggleWarning()
              }
              Omarchy.TextField {
                objectName: "appSearch"
                width: parent.width
                foreground: root.textColor
                placeholderText: "Search apps, sites or group members…"
                text: root.appSearch
                onTextEdited: root.appSearch = text
              }
              Row {
                width: parent.width
                spacing: Style.space(4)
                Repeater {
                  model: [{id:"all",label:"All"}, {id:"productive",label:"Productive"},
                    {id:"neutral",label:"Neutral"}, {id:"consumption",label:"Consumption"}]
                  delegate: Omarchy.Button {
                    required property var modelData
                    width: (parent.width - Style.space(12)) / 4
                    text: modelData.label
                    selected: root.appFilter === modelData.id
                    foreground: root.textColor
                    fontSize: Style.font.caption
                    horizontalPadding: Style.space(3)
                    focusable: true
                    onClicked: root.appFilter = modelData.id
                  }
                }
              }
              Text {
                width: parent.width
                text: root.matchingAppCount === 0 && root.filteredIgnored.length === 0 ? "No matching entries"
                  : root.matchingAppCount + " saved entries" + (root.filteredIgnored.length ? " · " + root.filteredIgnored.length + " excluded" : "")
                color: root.mutedText
                font.pixelSize: Style.font.caption
              }
            }


            Text {
              width: parent.width
              visible: root.page !== "manage"
              text: root.page === "review" ? "TO CLASSIFY"
                : root.paused ? "TRACKING PAUSED" : root.pendingPaused === false ? "RESUMING TRACKING" : root.working
                ? "APPS & SITES  ·  LIMITS RESET EACH HOUR"
                : root.widget && root.widget.snapshot && root.widget.snapshot.idle ? "TRACKING PAUSED WHILE IDLE"
                : "TRACKING PAUSED BY SCHEDULE"
              textFormat: Text.PlainText
              color: root.mutedText
              font.pixelSize: Style.font.caption
              font.bold: true
              wrapMode: Text.WordWrap
            }

            Repeater {
              model: trackedModel
              delegate: Column {
                id: targetGroup
                visible: root.page === "now" ? visibleWindows > 0
                  : root.page === "review" ? !configured && root.ignoredTargets.indexOf(targetId) < 0
                  : configured && root.manageSection === "apps" && root.matchesApp(targetId, targetName, targetCategory)
                required property string targetId
                required property string targetName
                required property string targetCategory
                required property real quotaSeconds
                required property string limitAction
                required property real usedSeconds
                required property int visibleWindows
                required property real todaySeconds
                required property bool linked
                required property bool configured
                required property bool focused
                required property string siteScopeIds
                required property string domainFamily
                required property string domainFamilies
                readonly property var entry: ({
                  id: targetId,
                  name: targetName,
                  category: targetCategory,
                  quota_seconds: quotaSeconds,
                  limit_action: limitAction,
                  used_seconds: usedSeconds,
                  today_seconds: todaySeconds,
                  linked: linked,
                  focused: focused,
                  site_scopes: JSON.parse(siteScopeIds),
                  grouping_scope: domainFamily,
                  grouping_scopes: JSON.parse(domainFamilies)
                })
                width: parent.width
                spacing: Style.space(7)

                Rectangle {
                id: targetCard
                readonly property var entry: targetGroup.entry
                readonly property string category: root.pendingCategories[entry.id] || String(entry.category || "neutral")
                readonly property int quotaMinutes: root.pendingQuotas[entry.id] || Math.round(Number(entry.quota_seconds || 600) / 60)
                readonly property string limitAction: root.pendingLimitActions[entry.id] || entry.limit_action || "close"
                function changeCategory(value) {
                  if (category === value) return
                  var categories = Object.assign({}, root.pendingCategories)
                  categories[entry.id] = value
                  root.pendingCategories = categories
                  root.runAgent(["classify", entry.id, value])
                }
                function changeQuota(delta) {
                  var next = Math.max(1, Math.min(120, quotaMinutes + delta))
                  if (next === quotaMinutes) return
                  var quotas = Object.assign({}, root.pendingQuotas)
                  quotas[entry.id] = next
                  root.pendingQuotas = quotas
                  root.runAgent(["quota", entry.id, String(next)])
                }
                function changeLimitAction(value) {
                  if (limitAction === value) return
                  var actions = Object.assign({}, root.pendingLimitActions)
                  actions[entry.id] = value
                  root.pendingLimitActions = actions
                  root.runAgent(["limit-action", entry.id, value])
                }
                width: parent.width
                implicitHeight: targetContent.implicitHeight + Style.space(18)
                radius: Style.cornerRadius
                color: root.softSurface
                border.width: Style.spacing.hairline
                border.color: root.outlineColor

                Column {
                  id: targetContent
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.top: parent.top
                  anchors.margins: Style.space(9)
                  spacing: Style.space(7)

                  Row {
                    id: targetHeader
                    width: parent.width
                    height: Math.max(nameBlock.implicitHeight,
                      remainingBadge.visible ? remainingBadge.height : 0)
                    spacing: Style.space(10)

                    Column {
                      id: nameBlock
                      width: targetHeader.width - (remainingBadge.visible
                        ? remainingBadge.width + targetHeader.spacing : 0)
                      spacing: Style.space(4)

                      Text {
                        width: parent.width
                        text: root.displayName(targetCard.entry)
                        textFormat: Text.PlainText
                        color: root.textColor
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        font.bold: true
                        wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                      }

                      Text {
                        readonly property string domain: String(targetCard.entry.id || "").slice(5)
                        visible: String(targetCard.entry.id || "").startsWith("site:")
                          && root.displayName(targetCard.entry).toLowerCase() !== domain.toLowerCase()
                        width: parent.width
                        text: domain
                        textFormat: Text.PlainText
                        color: root.mutedText
                        font.pixelSize: Style.font.caption
                        wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                      }

                      Text {
                        width: parent.width
                        text: (targetCard.entry.focused ? "●  " : "")
                          + (targetCard.entry.linked ? "GROUP"
                            : String(targetCard.entry.id || "").startsWith("site:") ? "SITE" : "APP")
                          + "  ·  " + root.formatElapsed(targetCard.entry.today_seconds) + " TODAY"
                        textFormat: Text.PlainText
                        color: root.mutedText
                        font.pixelSize: Style.font.caption
                        elide: Text.ElideRight
                      }
                    }

                    Rectangle {
                      id: remainingBadge
                      visible: targetCard.category === "consumption"
                      width: remainingText.implicitWidth + Style.space(20)
                      height: Style.space(34)
                      radius: Style.cornerRadius
                      color: root.hoverSurface
                      border.width: Style.spacing.hairline
                      border.color: root.outlineColor

                      Text {
                        id: remainingText
                        anchors.centerIn: parent
                        text: root.formatTime(Math.max(0, targetCard.quotaMinutes * 60
                          - Number(targetCard.entry.used_seconds || 0))) + " left"
                        textFormat: Text.PlainText
                        color: root.textColor
                        font.pixelSize: Style.font.bodySmall
                        font.bold: true
                        wrapMode: Text.NoWrap
                      }
                    }
                  }

                  Rectangle {
                    width: parent.width
                    height: Style.space(3)
                    radius: height / 2
                    color: root.hoverSurface
                    Rectangle {
                      width: parent.width * Math.min(1, targetCard.entry.today_seconds / root.maxTodaySeconds)
                      height: parent.height
                      radius: parent.radius
                      color: targetCard.category === "productive" ? root.productiveColor
                        : targetCard.category === "consumption" ? root.consumptionColor : root.mutedText
                      Behavior on width { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                    }
                  }

                  Row {
                    id: categoryRow
                    width: parent.width
                    height: Style.space(28)
                    spacing: Style.space(5)

                    Repeater {
                      model: [
                        { id: "productive", label: "Productive" },
                        { id: "neutral", label: "Neutral" },
                        { id: "consumption", label: "Consumption" }
                      ]
                      delegate: Rectangle {
                        required property var modelData
                        readonly property bool selected: targetCard.category === modelData.id
                        width: (categoryRow.width - categoryRow.spacing * 2) / 3
                        height: categoryRow.height
                        radius: Style.cornerRadius
                        color: selected ? root.textColor : root.hoverSurface
                        border.width: Style.spacing.hairline
                        border.color: selected ? root.textColor : root.outlineColor

                        Text {
                          anchors.centerIn: parent
                          width: parent.width - Style.space(8)
                          text: modelData.label
                          textFormat: Text.PlainText
                          color: parent.selected ? Color.popups.background : root.textColor
                          horizontalAlignment: Text.AlignHCenter
                          elide: Text.ElideRight
                          font.pixelSize: Style.font.bodySmall
                          font.bold: parent.selected
                        }

                        MouseArea {
                          anchors.fill: parent
                          cursorShape: Qt.PointingHandCursor
                          onClicked: targetCard.changeCategory(modelData.id)
                        }
                      }
                    }
                  }

                  Repeater {
                    model: root.page === "manage" ? targetCard.entry.site_scopes : []
                    delegate: Column {
                      id: scopeCard
                      required property string modelData
                      readonly property string mode: root.pendingSubdomainRules[targetCard.entry.grouping_scope] || root.subdomainRules[targetCard.entry.grouping_scope] || "smart"
                      width: parent.width
                      spacing: Style.space(5)
                      Text {
                        text: "DOMAINS · " + targetCard.entry.grouping_scopes.join(" · ")
                        textFormat: Text.PlainText
                        width: parent.width
                        elide: Text.ElideMiddle
                        color: root.mutedText
                        font.pixelSize: Style.font.caption
                      }
                      Row {
                        width: parent.width
                        spacing: Style.space(5)
                        Repeater {
                          model: [
                            {id: "smart", label: "Smart", hint: "Match declared application names or manifest URLs. Sites without a match stay separate."},
                            {id: "group", label: "Group", hint: "Group all sites in these domain families. Recorded time is combined."},
                            {id: "separate", label: "Separate", hint: "Keep sites in these domain families independent. Existing links stay."}
                          ]
                          delegate: Omarchy.Button {
                            required property var modelData
                            objectName: modelData.id === "group" ? "subdomainGroupButton" : "subdomainModeButton"
                            width: (parent.width - parent.spacing * 2) / 3
                            text: modelData.label
                            tooltipText: modelData.hint
                            foreground: root.textColor
                            fontSize: Style.font.bodySmall
                            bordered: true
                            focusable: true
                            selected: scopeCard.mode === modelData.id
                            enabled: root.serviceConnected
                            onClicked: root.setSubdomainRule(scopeCard.modelData, modelData.id, targetCard.entry.grouping_scope)
                          }
                        }
                      }
                    }
                  }

                  Omarchy.Button {
                    objectName: "excludeTargetButton"
                    visible: root.page === "review" || root.page === "manage"
                    width: parent.width
                    text: "Exclude from tracking"
                    foreground: root.textColor
                    fontSize: Style.font.bodySmall
                    bordered: true
                    focusable: true
                    onClicked: root.excludeTarget(targetCard.entry.id)
                  }

                  Row {
                    visible: targetCard.category === "consumption"
                    width: parent.width
                    height: quotaControls.height
                    spacing: Style.space(8)

                    Text {
                      width: parent.width - quotaControls.width - parent.spacing
                      anchors.verticalCenter: parent.verticalCenter
                      text: "HOURLY LIMIT"
                      textFormat: Text.PlainText
                      color: root.mutedText
                      font.pixelSize: Style.font.caption
                      font.bold: true
                    }

                    Row {
                      id: quotaControls
                      height: Style.space(30)
                      spacing: Style.space(4)

                      Rectangle {
                        width: Style.space(30)
                        height: parent.height
                        radius: Style.cornerRadius
                        color: root.hoverSurface
                        border.width: Style.spacing.hairline
                        border.color: root.outlineColor
                        Text {
                          anchors.centerIn: parent
                          text: "−"
                          color: root.textColor
                          font.pixelSize: Style.font.title
                        }
                        MouseArea {
                          anchors.fill: parent
                          cursorShape: Qt.PointingHandCursor
                          onClicked: targetCard.changeQuota(-1)
                        }
                      }

                      Text {
                        width: Style.space(48)
                        height: parent.height
                        text: targetCard.quotaMinutes + "m"
                        textFormat: Text.PlainText
                        color: root.textColor
                        font.family: "monospace"
                        font.pixelSize: Style.font.body
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                      }

                      Rectangle {
                        width: Style.space(30)
                        height: parent.height
                        radius: Style.cornerRadius
                        color: root.hoverSurface
                        border.width: Style.spacing.hairline
                        border.color: root.outlineColor
                        Text {
                          anchors.centerIn: parent
                          text: "+"
                          color: root.textColor
                          font.pixelSize: Style.font.title
                        }
                        MouseArea {
                          anchors.fill: parent
                          cursorShape: Qt.PointingHandCursor
                          onClicked: targetCard.changeQuota(1)
                        }
                      }
                    }
                  }

                  Column {
                    visible: root.page === "manage" && targetCard.category === "consumption"
                    width: parent.width
                    spacing: Style.space(5)

                    Text {
                      text: "WHEN LIMIT IS REACHED"
                      color: root.mutedText
                      font.pixelSize: Style.font.caption
                      font.bold: true
                    }

                    Row {
                      id: limitActionRow
                      width: parent.width
                      height: Style.space(28)
                      spacing: Style.space(5)
                      Repeater {
                        model: [
                          { id: "close", label: "Close" },
                          { id: "notify", label: "Notify" },
                          { id: "keep_open", label: "Keep open" }
                        ]
                        delegate: Rectangle {
                          required property var modelData
                          readonly property bool selected: targetCard.limitAction === modelData.id
                          width: (limitActionRow.width - limitActionRow.spacing * 2) / 3
                          height: limitActionRow.height
                          radius: Style.cornerRadius
                          color: selected ? root.textColor : root.hoverSurface
                          border.width: Style.spacing.hairline
                          border.color: selected ? root.textColor : root.outlineColor
                          Text {
                            anchors.centerIn: parent
                            width: parent.width - Style.space(8)
                            text: modelData.label
                            color: parent.selected ? Color.popups.background : root.textColor
                            horizontalAlignment: Text.AlignHCenter
                            elide: Text.ElideRight
                            font.pixelSize: Style.font.bodySmall
                            font.bold: parent.selected
                          }
                          MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: targetCard.changeLimitAction(modelData.id)
                          }
                        }
                      }
                    }
                  }
                }
              }
              }
            }

            Rectangle {
              visible: root.page === "review" ? root.reviewCount === 0
                : root.page === "manage" ? root.manageSection === "apps" && root.tracked.filter(function(row) { return row.configured }).length === 0
                  && root.ignoredTargets.length === 0
                : root.activeCount === 0
              width: parent.width
              implicitHeight: emptyNow.implicitHeight + Style.space(32)
              radius: Style.cornerRadius
              color: root.softSurface
              border.width: Style.spacing.hairline
              border.color: root.outlineColor

              Column {
                id: emptyNow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Style.space(16)
                spacing: Style.space(5)

                Text {
                  width: parent.width
                  text: root.page === "review" ? "Everything is classified"
                    : root.page === "manage" ? "No saved apps or sites"
                    : root.working ? "No open apps or sites" : "Tracking is paused"
                  color: root.textColor
                  font.pixelSize: Style.font.body
                  font.bold: true
                }
                Text {
                  width: parent.width
                  text: root.page === "review" ? "New apps and sites will appear here."
                    : root.page === "manage" ? "Choose a role in Now or Review to save an app."
                    : root.working
                    ? "Apps on displayed workspaces appear here while they are open."
                    : "Activity is counted during your scheduled tracking hours."
                  textFormat: Text.PlainText
                  color: root.mutedText
                  font.pixelSize: Style.font.bodySmall
                  wrapMode: Text.WordWrap
                }
              }
            }

            Column {
              visible: root.page === "manage" && root.manageSection === "apps" && root.appFilter === "all" && root.ignoredTargets.length > 0
              width: parent.width
              spacing: Style.space(7)
              Row {
                width: parent.width
                spacing: Style.space(8)
                Text {
                  width: parent.width - excludedToggle.width - (hiddenToggle.visible ? hiddenToggle.width + parent.spacing : 0) - parent.spacing
                  anchors.verticalCenter: parent.verticalCenter
                  text: "EXCLUDED FROM TRACKING"
                  color: root.mutedText
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }
                Omarchy.Button {
                  id: excludedToggle
                  objectName: "excludedVisibilityButton"
                  width: Style.space(80)
                  text: root.hideExcluded ? "Show" : "Hide"
                  foreground: root.textColor
                  fontSize: Style.font.bodySmall
                  bordered: true
                  focusable: true
                  enabled: root.serviceConnected
                  onClicked: root.toggleExcludedVisibility()
                }
                Omarchy.Button {
                  id: hiddenToggle
                  objectName: "revealHiddenExcludedButton"
                  width: Style.space(112)
                  visible: !root.hideExcluded && root.hiddenExcludedTargets.some(function(id) { return root.ignoredTargets.indexOf(id) >= 0 })
                  text: "Show hidden"
                  selected: root.revealHiddenExcluded
                  foreground: root.textColor
                  fontSize: Style.font.caption
                  bordered: true
                  focusable: true
                  onClicked: root.revealHiddenExcluded = !root.revealHiddenExcluded
                }
              }
              Repeater {
                model: root.filteredIgnored
                delegate: Rectangle {
                  objectName: "excludedEntry"
                  required property string modelData
                  width: parent.width
                  height: Style.space(44)
                  radius: Style.cornerRadius
                  color: root.softSurface
                  border.width: Style.spacing.hairline
                  border.color: root.outlineColor
                  Row {
                    anchors.fill: parent
                    anchors.margins: Style.space(8)
                    spacing: Style.space(8)
                    Text {
                      width: parent.width - restoreButton.width - hideEntryButton.width - parent.spacing * 2
                      height: parent.height
                      textFormat: Text.PlainText
                      text: root.displayName({ id: modelData, name: modelData.split(":").slice(1).join(":") })
                      color: root.textColor
                      font.pixelSize: Style.font.bodySmall
                      elide: Text.ElideRight
                      verticalAlignment: Text.AlignVCenter
                    }
                    Omarchy.Button {
                      id: hideEntryButton
                      objectName: "hideExcludedEntryButton"
                      width: Style.space(64)
                      height: parent.height
                      readonly property bool entryHidden: root.hiddenExcludedTargets.indexOf(modelData) >= 0
                      text: entryHidden ? "Unhide" : "Hide"
                      foreground: root.textColor
                      fontSize: Style.font.caption
                      bordered: true
                      focusable: true
                      enabled: root.serviceConnected
                      onClicked: root.setExcludedEntryHidden(modelData, !entryHidden)
                    }
                    Rectangle {
                      id: restoreButton
                      width: restoreLabel.implicitWidth + Style.space(16)
                      height: parent.height
                      radius: Style.cornerRadius
                      color: root.hoverSurface
                      Text {
                        id: restoreLabel
                        anchors.centerIn: parent
                        text: "Track again"
                        color: root.textColor
                        font.pixelSize: Style.font.caption
                        font.bold: true
                      }
                      MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.unexcludeTarget(modelData)
                      }
                    }
                  }
                }
              }
            }
            ManageHeader {
              label: "Diagnostics"; section: "diagnostics"
              statusText: !root.serviceConnected ? "Service offline"
                : root.diagnostics.browser_connected && root.diagnostics.browser_can_close_tabs === false ? "Reload extension"
                : root.diagnostics.browser_connected ? "Connected"
                : !root.diagnostics.browser_running ? "Browser closed"
                : !root.diagnostics.browser_connection_expected ? "Connecting" : "Browser offline"
            }
            Column {
              visible: root.page === "manage" && root.manageSection === "diagnostics"
              width: parent.width
              spacing: Style.space(8)
              Text {
                width: parent.width
                text: "Local service · " + (root.serviceConnected ? "Connected" : "Unavailable")
                color: root.textColor
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                width: parent.width
                text: "Browser extension · " + (!root.serviceConnected ? "Unavailable"
                  : root.diagnostics.browser_connected ? "Connected"
                  : !root.diagnostics.browser_running ? "Browser closed"
                  : !root.diagnostics.browser_connection_expected ? "Connecting" : "Not connected")
                color: root.textColor
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                width: parent.width
                text: !root.serviceConnected ? "Start the Focus user service or run the local installer."
                  : !root.diagnostics.browser_connected ? "Keep website distractions in check."
                  : root.diagnostics.browser_can_close_tabs === false ? "Reload Focus in chrome://extensions to enable tab closing."
                  : root.paused ? "Tracking and limits are paused."
                  : !root.working ? "Tracking is inactive: check your schedule or session idle state."
                  : Number(root.diagnostics.matched_sites || 0) + " visible site(s) recognized."
                color: root.mutedText
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
              Omarchy.Button {
                visible: !root.diagnostics.browser_connected
                text: "Set up extension"
                foreground: root.textColor
                bordered: true
                focusable: true
                fontSize: Style.font.bodySmall
                onClicked: {
                  Quickshell.execDetached(["xdg-open", "https://github.com/NoFlairos/focus#install"])
                  root.close()
                }
              }
              Omarchy.Button {
                visible: !root.serviceConnected
                text: "Restart local service"
                foreground: root.textColor
                bordered: true
                focusable: true
                fontSize: Style.font.bodySmall
                opacity: enabled ? 1 : 0.4
                onClicked: Quickshell.execDetached(["systemctl", "--user", "restart", "focus-ratio.service"])
              }
            }

            ManageHeader { label: "Data export"; section: "data" }
            Column {
              visible: root.page === "manage" && root.manageSection === "data"
              width: parent.width
              spacing: Style.space(8)
              Row {
                width: parent.width
                spacing: Style.space(6)
                Omarchy.Button {
                  width: (parent.width - parent.spacing) / 2
                  text: "Export history · CSV"
                  enabled: root.serviceConnected && !root.dataBusy
                  foreground: root.textColor
                  fontSize: Style.font.bodySmall
                  bordered: true
                  focusable: true
                  onClicked: root.dataCommand(["export-history"])
                }
                Omarchy.Button {
                  width: (parent.width - parent.spacing) / 2
                  text: "Back up settings"
                  enabled: root.serviceConnected && !root.dataBusy
                  foreground: root.textColor
                  fontSize: Style.font.bodySmall
                  bordered: true
                  focusable: true
                  onClicked: root.dataCommand(["backup-settings"])
                }
              }
              Text {
                visible: text.length > 0
                width: parent.width
                textFormat: Text.PlainText
                text: root.dataFeedback
                color: root.mutedText
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
              Omarchy.Button {
                visible: !!root.dataAction.path
                text: "Open export folder"
                foreground: root.textColor
                fontSize: Style.font.bodySmall
                focusable: true
                onClicked: Quickshell.execDetached(["xdg-open", root.dataAction.path.slice(0, root.dataAction.path.lastIndexOf("/"))])
              }
              Omarchy.Button {
                text: root.confirmClearHistory ? "Cancel" : "Clear history…"
                foreground: root.mutedText
                fontSize: Style.font.bodySmall
                focusable: true
                enabled: root.serviceConnected && !root.dataBusy
                onClicked: root.confirmClearHistory = !root.confirmClearHistory
              }
              Text {
                visible: root.confirmClearHistory
                width: parent.width
                text: "Deletes history and resets limits. Settings and exports stay."
                color: root.mutedText
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
              Omarchy.Button {
                visible: root.confirmClearHistory
                text: "Delete history"
                foreground: root.textColor
                fontSize: Style.font.bodySmall
                bordered: true
                focusable: true
                enabled: root.serviceConnected && !root.dataBusy
                onClicked: { root.confirmClearHistory = false; root.dataCommand(["clear-history", "confirm"]) }
              }
            }

          }

          Column {
            visible: root.page === "history"
            width: parent.width
            spacing: Style.space(10)

            Column {
              width: parent.width
              visible: !!root.weekly.current && root.weekly.current.recorded_days > 0
              spacing: Style.space(6)
              Text {
                text: "LAST 7 DAYS"
                color: root.mutedText
                font.pixelSize: Style.font.caption
                font.bold: true
              }
              Text {
                width: parent.width
                text: root.weekly.current ? root.formatElapsed(root.weekly.current.screen_seconds) + " screen time" : ""
                color: root.textColor
                font.pixelSize: Style.font.body
                font.bold: true
              }
              Text {
                width: parent.width
                text: root.weekly.current ? root.minutes(root.weekly.current.productive) + " productive · "
                  + root.minutes(root.weekly.current.neutral) + " neutral · " + root.minutes(root.weekly.current.consumption) + " consumed" : ""
                color: root.mutedText
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
              Text {
                width: parent.width
                text: root.weekly.current ? root.weekly.current.recorded_days + " recorded days"
                  + (root.weekly.screen_delta !== null && root.weekly.screen_delta !== undefined
                    ? " · " + (root.weekly.screen_delta >= 0 ? "+" : "−") + root.formatElapsed(Math.abs(root.weekly.screen_delta))
                      + " vs previous 7 days (" + root.weekly.previous.recorded_days + " recorded)" : "") : ""
                color: root.mutedText
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
            }

            Text {
              width: parent.width
              text: "DAILY ACTIVITY"
              textFormat: Text.PlainText
              color: root.mutedText
              font.pixelSize: Style.font.caption
              font.bold: true
            }

            Repeater {
              model: {
                if (root.page !== "history") return []
                var start = new Date()
                start.setDate(start.getDate() - 6)
                var cutoff = Qt.formatDateTime(start, "yyyy-MM-dd")
                return root.history.filter(function(day) {
                  return String(day.day) >= cutoff
                }).slice(-7).reverse()
              }
              delegate: Rectangle {
                id: historyCard
                required property var modelData
                readonly property real productive: Number(modelData.productive || 0)
                readonly property real neutral: Number(modelData.neutral || 0)
                readonly property real consumed: Number(modelData.consumption || 0)
                readonly property real classified: productive + neutral + consumed
                width: parent.width
                implicitHeight: historyContent.implicitHeight + Style.space(24)
                radius: Style.cornerRadius
                color: root.softSurface
                border.width: Style.spacing.hairline
                border.color: root.outlineColor

                Column {
                  id: historyContent
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.top: parent.top
                  anchors.margins: Style.space(12)
                  spacing: Style.space(9)

                  Row {
                    width: parent.width
                    Text {
                      width: parent.width / 2
                      text: String(historyCard.modelData.day || "")
                      color: root.textColor
                      font.family: "monospace"
                      font.pixelSize: Style.font.body
                      font.bold: true
                    }

                  }

                  Rectangle {
                    width: parent.width
                    height: Style.space(4)
                    radius: height / 2
                    color: root.hoverSurface
                    Row {
                      anchors.fill: parent
                      spacing: 0
                      Rectangle {
                        width: historyCard.classified > 0
                          ? parent.width * historyCard.productive / historyCard.classified : 0
                        height: parent.height
                        color: root.productiveColor
                      }
                      Rectangle {
                        width: historyCard.classified > 0
                          ? parent.width * historyCard.neutral / historyCard.classified : 0
                        height: parent.height
                        color: root.neutralColor
                      }
                      Rectangle {
                        width: historyCard.classified > 0
                          ? parent.width * historyCard.consumed / historyCard.classified : 0
                        height: parent.height
                        color: root.consumptionColor
                      }
                    }
                  }

                  Row {
                    width: parent.width
                    Text {
                      width: parent.width / 2
                      text: "● " + root.minutes(historyCard.productive) + " productive"
                      color: root.productiveColor
                      font.pixelSize: Style.font.bodySmall
                    }
                    Text {
                      width: parent.width / 2
                      text: "● " + root.minutes(historyCard.consumed) + " consumed"
                      color: root.consumptionColor
                      font.pixelSize: Style.font.bodySmall
                      horizontalAlignment: Text.AlignRight
                    }
                  }

                  Text {
                    visible: historyCard.modelData.screen_seconds !== undefined
                      || Number(historyCard.modelData.neutral || 0) > 0
                      || Number(historyCard.modelData.unclassified || 0) > 0
                    width: parent.width
                    text: (historyCard.modelData.screen_seconds !== undefined
                      ? "Screen time " + root.formatElapsed(historyCard.modelData.screen_seconds) : "")
                      + (Number(historyCard.modelData.neutral || 0) > 0
                        ? (historyCard.modelData.screen_seconds !== undefined ? "  ·  " : "")
                          + "● " + root.minutes(historyCard.modelData.neutral) + " neutral" : "")
                      + (Number(historyCard.modelData.unclassified || 0) > 0
                        ? (historyCard.modelData.screen_seconds !== undefined
                          || Number(historyCard.modelData.neutral || 0) > 0 ? "  ·  " : "")
                          + root.minutes(historyCard.modelData.unclassified) + " to classify" : "")
                    color: root.mutedText
                    font.pixelSize: Style.font.caption
                  }
                }
              }
            }

            Rectangle {
              visible: root.history.length === 0
              width: parent.width
              implicitHeight: emptyHistory.implicitHeight + Style.space(32)
              radius: Style.cornerRadius
              color: root.softSurface
              border.width: Style.spacing.hairline
              border.color: root.outlineColor

              Column {
                id: emptyHistory
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Style.space(16)
                spacing: Style.space(5)

                Text {
                  text: "No history yet"
                  color: root.textColor
                  font.pixelSize: Style.font.body
                  font.bold: true
                }
                Text {
                  width: parent.width
                  text: "Daily totals will appear here after tracking starts."
                  color: root.mutedText
                  font.pixelSize: Style.font.bodySmall
                  wrapMode: Text.WordWrap
                }
              }
            }
          }
        }
      }

      Row {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Style.space(20)
        spacing: Style.space(6)

        Repeater {
          model: [
            {bottom: false, symbol: "↑", hint: "Back to top"},
            {bottom: true, symbol: "↓", hint: "Go to bottom"}
          ]
          delegate: Omarchy.Button {
            required property var modelData
            objectName: modelData.bottom ? "scrollToBottomButton" : "scrollToTopButton"
            width: Style.space(36)
            height: Style.space(36)
            text: modelData.symbol
            tooltipText: modelData.hint
            visible: (modelData.bottom ? flick.contentHeight - flick.height - flick.contentY : flick.contentY) > Style.space(80)
            foreground: root.textColor
            background: root.solidPopup
            fontSize: Style.font.body
            bordered: true
            focusable: true
            onClicked: {
              root.finishScheduleEditing()
              flick.cancelFlick()
              scrollJump.stop()
              scrollJump.to = modelData.bottom ? Math.max(0, flick.contentHeight - flick.height) : 0
              scrollJump.restart()
            }
          }
        }
      }
      NumberAnimation {
        id: scrollJump
        target: flick
        property: "contentY"
        duration: 180
        easing.type: Easing.OutCubic
      }

    }
  }
}
