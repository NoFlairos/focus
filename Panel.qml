import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
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
  readonly property var snapshot: widget && widget.snapshot ? widget.snapshot : ({})
  // A setting shown at its new value at once, until the agent confirms it or 5 s pass.
  component Pending: QtObject {
    id: pending
    property var saved
    property var value: undefined
    readonly property var current: value !== undefined ? value : saved
    property Timer timer: Timer { interval: 5000; onTriggered: pending.value = undefined }
    onSavedChanged: if (value !== undefined && saved === value) { value = undefined; timer.stop() }
    function set(next, command) { value = next; root.runAgent(command); timer.restart() }
  }
  Pending { id: warningSetting; saved: root.snapshot.warn_before_limit === true }
  Pending { id: weeklySetting; saved: root.snapshot.weekly_summary_enabled !== false }
  Pending { id: budgetSetting; saved: Number(root.snapshot.daily_budget_minutes || 0) }
  Pending { id: pauseSetting; saved: root.snapshot.paused === true }
  Pending { id: focusSetting; saved: Number(root.snapshot.focus_until || 0) > 0 }
  readonly property bool warningEnabled: warningSetting.current
  readonly property bool paused: pauseSetting.current
  readonly property bool focusActive: focusSetting.current
  property string headerPicker: ""
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
    headerPicker = ""
    pauseSetting.set(true, ["pause", duration])
  }
  function startFocus(minutes) {
    headerPicker = ""
    focusSetting.set(minutes !== "off", ["focus", minutes])
    if (minutes !== "off") pauseSetting.value = false
  }
  property string appSearch: ""
  property string appFilter: "all"
  property string expandedCardId: ""
  property bool excludedOpen: false
  property string detachingMember: ""
  property string detachFeedback: ""
  property Item activePicker: null
  onOpenedChanged: if (!opened) excludedOpen = false

  function matchesApp(searchText, category, id) {
    if (appFilter !== "all" && (pendingCategories[id] || category) !== appFilter) return false
    var search = appSearch.trim().toLowerCase()
    return !search || searchText.indexOf(search) >= 0
  }
  readonly property var filteredIgnored: appFilter === "all" ? ignoredTargets.filter(function(id) {
    return !root.appSearch.trim() || (id + " " + root.displayName({id:id, name:id.split(":").slice(1).join(":")}))
      .toLowerCase().indexOf(root.appSearch.trim().toLowerCase()) >= 0
  }) : []
  readonly property int matchingAppCount: tracked.filter(function(row) {
    return row.configured && root.matchesApp(root.searchText(row), row.category, row.id)
  }).length
  function searchText(row) {
    return [row.name, row.id].concat(row.members || []).join(" ").toLowerCase()
  }
  Timer {
    id: detachAckTimer
    interval: 6000
    onTriggered: { root.detachingMember = ""; root.detachFeedback = "Detach not confirmed · check Diagnostics" }
  }
  property string mergingSource: ""
  property string mergeFeedback: ""
  readonly property var diagnostics: widget && widget.snapshot ? widget.snapshot.diagnostics || ({}) : ({})
  readonly property bool serviceConnected: widget ? widget.serviceConnected === true : false

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
    }
  }

  // Label, optional hint and −/+ buttons around a value (quotas, budget).
  component Stepper: Row {
    id: stepper
    property string label
    property string hint: ""
    property string valueText
    signal step(int direction)
    width: parent ? parent.width : 0
    height: Style.space(30)
    spacing: Style.space(4)
    Column {
      width: stepper.width - stepMinus.width - stepValue.width - stepPlus.width - stepper.spacing * 3
      anchors.verticalCenter: parent.verticalCenter
      Text { width: parent.width; text: stepper.label; color: root.textColor; font.pixelSize: Style.font.bodySmall; elide: Text.ElideRight }
      Text { width: parent.width; visible: text.length > 0; text: stepper.hint; color: root.mutedText; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
    }
    Omarchy.Button {
      id: stepMinus
      width: Style.space(30); height: parent.height; horizontalPadding: 0
      text: "−"; foreground: root.textColor; fontSize: Style.font.body; bordered: true; focusable: true
      onClicked: stepper.step(-1)
    }
    Text {
      id: stepValue
      width: Style.space(52); height: parent.height
      text: stepper.valueText
      color: root.textColor; font.family: "monospace"; font.pixelSize: Style.font.bodySmall; font.bold: true
      horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
    }
    Omarchy.Button {
      id: stepPlus
      width: Style.space(30); height: parent.height; horizontalPadding: 0
      text: "+"; foreground: root.textColor; fontSize: Style.font.body; bordered: true; focusable: true
      onClicked: stepper.step(1)
    }
  }

  // Segmented choice built from native buttons (category, limit action, subdomain mode).
  component ChoiceRow: Row {
    id: choiceRow
    property var choices: []
    property string current: ""
    property string buttonName: ""
    signal chosen(string id)
    width: parent ? parent.width : 0
    height: Style.space(28)
    spacing: Style.space(5)
    Repeater {
      model: choiceRow.choices
      delegate: Omarchy.Button {
        required property var modelData
        objectName: choiceRow.buttonName ? choiceRow.buttonName + ":" + modelData.id : ""
        width: (choiceRow.width - choiceRow.spacing * (choiceRow.choices.length - 1)) / choiceRow.choices.length
        height: choiceRow.height
        text: modelData.label
        tooltipText: modelData.hint || ""
        selected: choiceRow.current === modelData.id
        enabled: choiceRow.enabled
        foreground: root.textColor
        fontSize: Style.font.bodySmall
        horizontalPadding: Style.space(3)
        bordered: true
        focusable: true
        onClicked: choiceRow.chosen(modelData.id)
      }
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

  Timer {
    id: mergeAckTimer
    interval: 6000
    onTriggered: {
      root.mergingSource = ""
      root.mergeFeedback = "Merge not confirmed · check Diagnostics"
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
    return row.review && ignoredTargets.indexOf(row.id) < 0
  }).length
  readonly property var tabItems: [{ id: "now", label: "Now" }, { id: "review", label: "Review" },
    { id: "history", label: "History" }, { id: "manage", label: "Manage" }]
  readonly property real maxTodaySeconds: Math.max(1, tracked.reduce(function(best, row) {
    return Math.max(best, Number(row.today_seconds || 0))
  }, 0))
  readonly property bool working: !!(widget && widget.snapshot && widget.snapshot.working)
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
  property var pendingLimitPeriods: ({})
  property var commandQueue: []

  function modelRow(row) {
    var scopes = root.siteScopes(row)
    return {
      targetId: String(row.id || ""),
      targetName: String(row.name || ""),
      targetCategory: String(row.category || "neutral"),
      quotaSeconds: Number(row.quota_seconds || 600),
      limitAction: String(row.limit_action || "close"),
      limitPeriod: String(row.limit_period || "hour"),
      limitReason: String(row.limit_reason || ""),
      remainingSeconds: row.remaining_seconds === null || row.remaining_seconds === undefined ? -1 : Number(row.remaining_seconds),
      canSnooze: !!row.can_snooze,
      usedSeconds: Number(row.used_seconds || 0),
      visibleWindows: Number(row.visible_windows || 0),
      todaySeconds: Number(row.today_seconds || 0),
      linked: !!row.linked,
      memberIds: JSON.stringify(row.members || []),
      searchText: root.searchText(row),
      scopeDomain: String(scopes[0] || ""),
      domainFamily: String(row.grouping_scope || scopes[0] || ""),
      familiesLabel: (row.grouping_scopes || scopes).join(" · "),
      configured: !!row.configured,
      review: !!row.review,
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
      if (root.pendingLimitPeriods[row.id] === (row.limit_period || "hour")) {
        var periods = Object.assign({}, root.pendingLimitPeriods)
        delete periods[row.id]
        root.pendingLimitPeriods = periods
      }
    }
    for (var k = trackedModel.count - 1; k >= 0; k--) {
      if (!wanted[trackedModel.get(k).targetId]) trackedModel.remove(k)
    }
  }

  onTrackedChanged: {
    if (scrollBusy) syncDeferred = true
    else syncTracked()
    if (detachingMember && tracked.some(function(row) {
      return row.id === root.detachingMember && (!row.members || row.members.length === 1)
    })) {
      detachingMember = ""
      detachFeedback = ""
      detachAckTimer.stop()
    }
    if (mergingSource && !tracked.some(function(row) { return row.id === root.mergingSource })) {
      mergingSource = ""
      mergeFeedback = ""
      expandedCardId = ""
      mergeAckTimer.stop()
    }
  }
  onSavedIgnoredTargetsChanged: {
    pendingExcluded = pendingExcluded.filter(function(id) { return savedIgnoredTargets.indexOf(id) < 0 })
    pendingUnexcluded = pendingUnexcluded.filter(function(id) { return savedIgnoredTargets.indexOf(id) >= 0 })
  }
  onSavedScheduleChanged: {
    if (pendingSchedule && JSON.stringify(savedSchedule) === JSON.stringify(pendingSchedule)) {
      pendingSchedule = null
      scheduleDraft = null
      scheduleAllDayDraft = null
      scheduleFeedback = ""
      scheduleAckTimer.stop()
      scheduleTimeEdited = false
    }
    if (!scheduleTimeEdited) {
      scheduleStartDraft = savedSchedule.start
      scheduleEndDraft = savedSchedule.end
    }
  }
  Component.onCompleted: {
    syncTracked()
    scheduleStartDraft = savedSchedule.start
    scheduleEndDraft = savedSchedule.end
  }

  ListModel { id: trackedModel }

  // Scrolling: momentum after touchpad gestures; data refreshes wait until the list rests.
  property real wheelVelocity: 0
  property double lastWheelTime: 0
  property bool scrollBusy: false
  property bool syncDeferred: false
  function scrollActivity() {
    scrollBusy = true
    scrollIdle.restart()
  }
  Timer {
    id: glideTimer
    interval: 50
    onTriggered: {
      if (Math.abs(root.wheelVelocity) > 120) flick.flick(0, root.wheelVelocity)
      root.wheelVelocity = 0
    }
  }
  Timer {
    id: scrollIdle
    interval: 300
    onTriggered: {
      root.scrollBusy = flick.moving
      if (!root.scrollBusy && root.syncDeferred) {
        root.syncDeferred = false
        root.syncTracked()
      }
    }
  }


  // One agent process at a time keeps rapid edits in click order.
  Process {
    id: commandProcess
    onExited: function(exitCode) {
      optimisticResetTimer.restart()
      root.dispatchCommand()
    }
  }

  // Drop optimistic values the agent never confirmed (failed or superseded command).
  Timer {
    id: optimisticResetTimer
    interval: 4000
    onTriggered: {
      if (root.commandQueue.length || commandProcess.running) return restart()
      root.pendingCategories = ({})
      root.pendingQuotas = ({})
      root.pendingLimitActions = ({})
      root.pendingLimitPeriods = ({})
    }
  }

  function dispatchCommand() {
    if (commandProcess.running || !commandQueue.length || !widget) return
    var next = commandQueue[0]
    commandQueue = commandQueue.slice(1)
    commandProcess.command = ["python3", widget.agentPath].concat(next)
    commandProcess.running = true
  }


  function runAgent(args) {
    if (!widget) return
    commandQueue = commandQueue.concat([args])
    Qt.callLater(dispatchCommand)
  }

  function setSchedule(next) {
    if (JSON.stringify(next) === JSON.stringify(schedule)) return
    scheduleDraft = next
    scheduleFeedback = ""
    scheduleAutosave.restart()
  }

  // Changes save on their own; a time being typed waits until it is complete.
  Timer {
    id: scheduleAutosave
    interval: 900
    onTriggered: root.saveSchedule(false)
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

  function saveSchedule(explicit) {
    var start = scheduleAllDay ? "00:00" : scheduleStartDraft.trim()
    var end = scheduleAllDay ? "00:00" : scheduleEndDraft.trim()
    var validTime = /^([01][0-9]|2[0-3]):[0-5][0-9]$/
    if (!validTime.test(start) || !validTime.test(end)) {
      if (explicit) scheduleFeedback = "Use 24-hour time, for example 09:30"
      return
    }
    var next = { weekdays: schedule.weekdays.slice(), start: start, end: end }
    if (JSON.stringify(next) === JSON.stringify(savedSchedule)) {
      scheduleDraft = null
      scheduleAllDayDraft = null
      scheduleTimeEdited = false
      scheduleFeedback = ""
      return
    }
    scheduleDraft = next
    pendingSchedule = next
    scheduleFeedback = ""
    runAgent(["schedule", next.weekdays.join(","), next.start, next.end])
    scheduleAckTimer.restart()
  }

  // Open an entry from Now in Manage, expanded and scrolled into view.
  function revealCard(item, id) {
    appSearch = ""
    appFilter = "all"
    page = "manage"
    manageSection = "apps"
    expandedCardId = id
    revealTarget = item
    revealTimer.restart()
  }
  property Item revealTarget: null
  Timer {
    id: revealTimer
    interval: 60
    onTriggered: if (root.revealTarget) flick.contentY = Math.max(0, Math.min(flick.contentHeight - flick.height,
      root.revealTarget.mapToItem(content, 0, 0).y - Style.space(8)))
  }

  function mergeInto(source, destination) {
    mergingSource = source
    mergeFeedback = ""
    runAgent(["merge", source, destination])
    mergeAckTimer.restart()
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
      root.scheduleFeedback = "Not saved · check Diagnostics"
    }
  }

  function togglePause() {
    pauseSetting.set(!paused, ["pause", paused ? "off" : "on"])
  }

  function formatTime(seconds) {
    seconds = Math.max(0, Number(seconds || 0))
    if (seconds >= 3600) return formatElapsed(seconds)
    return Math.floor(seconds / 60) + ":" + String(Math.floor(seconds % 60)).padStart(2, "0")
  }

  function formatQuota(minutes) {
    return minutes >= 60 ? Math.floor(minutes / 60) + "h" + (minutes % 60 ? String(minutes % 60).padStart(2, "0") : "") : minutes + "m"
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

  // Names come ready from the agent; members and exclusions use its label map.
  function displayName(target) {
    var labels = snapshot.labels || ({})
    return String(labels[target.id] || target.name || target.id || "")
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
        if (root.activePicker && root.activePicker.popupOpen) root.activePicker.close()
        else root.close()
      }
      onTabRequested: function(direction) {
        if (root.activePicker && root.activePicker.popupOpen) return
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

        maximumFlickVelocity: 5000
        onMovementStarted: root.scrollActivity()
        onMovementEnded: scrollIdle.restart()

        WheelHandler {
          target: null
          acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
          onWheel: function(event) {
            event.accepted = true
            root.scrollActivity()
            var now = Date.now()
            var limit = Math.max(0, flick.contentHeight - flick.height)
            if (event.pixelDelta.y !== 0) {
              // Touchpad: follow the fingers 1:1, then glide on release like other apps.
              scrollJump.stop()
              flick.cancelFlick()
              var elapsed = now - root.lastWheelTime
              var instant = event.pixelDelta.y * 1000 / Math.max(8, Math.min(100, elapsed))
              root.wheelVelocity = elapsed > 100 ? instant : root.wheelVelocity * 0.6 + instant * 0.4
              root.lastWheelTime = now
              flick.contentY = Math.max(0, Math.min(limit, flick.contentY - event.pixelDelta.y))
              glideTimer.restart()
            } else if (event.angleDelta.y !== 0) {
              // Mouse wheel: animate each notch instead of jumping.
              var from = scrollJump.running ? scrollJump.to : flick.contentY
              scrollJump.stop()
              scrollJump.to = Math.max(0, Math.min(limit, from - event.angleDelta.y / 120 * Style.space(120)))
              scrollJump.restart()
            }
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
              spacing: Style.space(6)
              Text {
                width: parent.width - focusButton.width - pauseButton.width - parent.spacing * 2
                text: "Focus"
                textFormat: Text.PlainText
                color: root.textColor
                font.family: root.bar ? root.bar.fontFamily : Style.font.family
                font.pixelSize: Style.font.heading
                anchors.verticalCenter: parent.verticalCenter
                font.bold: true
              }
              Omarchy.Button {
                id: focusButton
                anchors.verticalCenter: parent.verticalCenter
                height: Style.space(28)
                text: root.focusActive ? "End session" : "Focus session"
                tooltipText: "Block all Consumption for a while"
                selected: root.headerPicker === "focus" || root.focusActive
                foreground: root.textColor
                fontSize: Style.font.caption
                horizontalPadding: Style.space(10)
                bordered: true
                focusable: true
                onClicked: root.focusActive ? root.startFocus("off")
                  : root.headerPicker = root.headerPicker === "focus" ? "" : "focus"
              }
              Omarchy.Button {
                id: pauseButton
                anchors.verticalCenter: parent.verticalCenter
                height: Style.space(28)
                text: root.paused ? "Resume" : "Pause"
                selected: root.headerPicker === "pause"
                foreground: root.textColor
                fontSize: Style.font.caption
                horizontalPadding: Style.space(10)
                bordered: true
                focusable: true
                onClicked: root.paused ? root.togglePause()
                  : root.headerPicker = root.headerPicker === "pause" ? "" : "pause"
              }
            }

            Row {
              visible: root.headerPicker !== ""
              width: parent.width
              spacing: Style.space(4)
              Repeater {
                model: root.headerPicker === "focus"
                  ? [{label:"25 min",value:"25"}, {label:"50 min",value:"50"}, {label:"90 min",value:"90"}]
                  : [{label:"15 min",value:"15"}, {label:"1 hour",value:"60"},
                     {label:"Tomorrow",value:"tomorrow"}, {label:"Until resumed",value:"on"}]
                delegate: Omarchy.Button {
                  required property var modelData
                  objectName: root.headerPicker + "Choice"
                  width: (parent.width - Style.space(4) * (root.headerPicker === "focus" ? 2 : 3)) / (root.headerPicker === "focus" ? 3 : 4)
                  text: modelData.label
                  foreground: root.textColor
                  fontSize: Style.font.caption
                  horizontalPadding: Style.space(3)
                  focusable: true
                  bordered: true
                  onClicked: root.headerPicker === "focus" ? root.startFocus(modelData.value) : root.startPause(modelData.value)
                }
              }
            }

            Text {
              id: screenTimeText
              width: parent.width
              text: "Today’s screen time " + (root.today.screen_seconds !== undefined
                ? root.formatElapsed(root.today.screen_seconds) : "—")
                + (root.focusActive && root.snapshot.focus_until
                  ? "  ·  Focus session until " + Qt.formatDateTime(new Date(root.snapshot.focus_until * 1000), "HH:mm")
                  : root.paused && root.snapshot.pause_until
                  ? "  ·  Resumes " + Qt.formatDateTime(new Date(root.snapshot.pause_until * 1000), "ddd HH:mm") : "")
              color: root.mutedText
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              HoverHandler { id: screenTimeHover }
              ToolTip.visible: screenTimeHover.hovered
              ToolTip.delay: 500
              ToolTip.text: "Visible apps counted once during tracking hours"
                + (root.today.screen_started_at
                  ? " · recorded since " + Qt.formatDateTime(new Date(root.today.screen_started_at), "HH:mm") : "")
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
                    text: modelData.id === "review" && root.reviewCount > 0
                      ? modelData.label + " · " + root.reviewCount : modelData.label
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
                          scheduleAutosave.restart()
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
                      onAccepted: root.saveSchedule(true)
                      onEditingFinished: root.saveSchedule(true)
                      background: Rectangle {
                        radius: Style.cornerRadius
                        color: scheduleStart.activeFocus ? root.hoverSurface : "transparent"
                      }
                      onTextEdited: {
                        root.scheduleTimeEdited = true
                        root.scheduleStartDraft = text
                        root.scheduleFeedback = ""
                        scheduleAutosave.restart()
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
                      onAccepted: root.saveSchedule(true)
                      onEditingFinished: root.saveSchedule(true)
                      background: Rectangle {
                        radius: Style.cornerRadius
                        color: scheduleEnd.activeFocus ? root.hoverSurface : "transparent"
                      }
                      onTextEdited: {
                        root.scheduleTimeEdited = true
                        root.scheduleEndDraft = text
                        root.scheduleFeedback = ""
                        scheduleAutosave.restart()
                      }
                    }
                  }
                }

                Text {
                  width: parent.width
                  visible: text.length > 0
                  text: root.scheduleFeedback ? root.scheduleFeedback
                    : root.pendingSchedule ? "Saving…"
                    : root.schedule.weekdays.length === 0 ? "Select a day to enable tracking"
                    : !root.scheduleAllDay && scheduleStart.text > scheduleEnd.text ? "Ends the following day"
                    : ""
                  color: root.mutedText
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.WordWrap
                }

              }
            }

            ManageHeader { label: "Apps & sites"; section: "apps" }
            Column {
              visible: root.page === "manage" && root.manageSection === "apps"
              width: parent.width
              spacing: Style.space(8)
              Repeater {
                model: root.suggestions
                delegate: Row {
                  required property var modelData
                  width: parent.width
                  height: Style.space(30)
                  spacing: Style.space(6)
                  Text {
                    objectName: "suggestionLabel"
                    width: parent.width - suggestionMerge.width - suggestionDismiss.width - parent.spacing * 2
                    height: parent.height
                    text: modelData.name
                    textFormat: Text.PlainText
                    color: root.textColor
                    font.pixelSize: Style.font.bodySmall
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    HoverHandler { id: suggestionHover }
                    ToolTip.visible: suggestionHover.hovered
                    ToolTip.text: modelData.source.split(":").slice(1).join(":") + " + " + modelData.destination.split(":").slice(1).join(":")
                  }
                  Omarchy.Button {
                    id: suggestionMerge
                    height: parent.height
                    text: "Merge"
                    foreground: root.textColor
                    fontSize: Style.font.caption
                    bordered: true
                    focusable: true
                    enabled: root.serviceConnected && !root.mergingSource
                    onClicked: root.mergeInto(modelData.source, modelData.destination)
                  }
                  Omarchy.Button {
                    id: suggestionDismiss
                    height: parent.height
                    text: "Dismiss"
                    foreground: root.mutedText
                    fontSize: Style.font.caption
                    focusable: true
                    onClicked: root.runAgent(["dismiss-suggestion", modelData.source, modelData.destination])
                  }
                }
              }
              Omarchy.Toggle {
                objectName: "warningToggle"
                width: parent.width
                label: "Warn before limit"
                description: "Up to 2 minutes before"
                checked: root.warningEnabled
                foreground: root.textColor
                titleSize: Style.font.bodySmall
                onClicked: warningSetting.set(!root.warningEnabled, ["warning", root.warningEnabled ? "off" : "on"])
              }
              Stepper {
                objectName: "budgetStepper"
                label: "Daily Consumption budget"
                hint: budgetSetting.current > 0 ? root.formatElapsed(Number(root.snapshot.budget_used_seconds || 0)) + " used today" : "All Consumption combined"
                valueText: budgetSetting.current > 0 ? root.formatQuota(budgetSetting.current) : "Off"
                onStep: function(direction) {
                  var next = Math.max(0, Math.min(720, budgetSetting.current + direction * 15))
                  if (next !== budgetSetting.current) budgetSetting.set(next, ["budget", String(next)])
                }
              }
              Omarchy.TextField {
                objectName: "appSearch"
                width: parent.width
                foreground: root.textColor
                placeholderText: "Search"
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
                visible: root.matchingAppCount === 0 && root.filteredIgnored.length === 0
                  && (root.appSearch.trim() !== "" || root.appFilter !== "all")
                text: "No matching entries"
                color: root.mutedText
                font.pixelSize: Style.font.caption
              }
            }

            Repeater {
              model: trackedModel
              delegate: Column {
                id: targetGroup
                visible: root.page === "now" ? visibleWindows > 0
                  : root.page === "review" ? review && root.ignoredTargets.indexOf(targetId) < 0
                  : configured && root.manageSection === "apps" && root.matchesApp(searchText, targetCategory, targetId)
                required property string targetId
                required property string targetName
                required property string targetCategory
                required property real quotaSeconds
                required property string limitAction
                required property string limitPeriod
                required property string limitReason
                required property real remainingSeconds
                required property bool canSnooze
                required property real usedSeconds
                required property int visibleWindows
                required property real todaySeconds
                required property bool linked
                required property bool configured
                required property bool review
                required property bool focused
                required property string memberIds
                required property string searchText
                required property string scopeDomain
                required property string domainFamily
                required property string familiesLabel
                readonly property var members: JSON.parse(memberIds)
                readonly property bool expanded: root.expandedCardId === targetId && root.page !== "now"
                width: parent.width
                spacing: Style.space(7)

                Rectangle {
                id: targetCard
                readonly property string targetId: targetGroup.targetId
                readonly property string category: root.pendingCategories[targetId] || targetGroup.targetCategory
                readonly property int quotaMinutes: root.pendingQuotas[targetId] || Math.round(targetGroup.quotaSeconds / 60)
                readonly property string limitAction: root.pendingLimitActions[targetId] || targetGroup.limitAction
                readonly property string limitPeriod: root.pendingLimitPeriods[targetId] || targetGroup.limitPeriod
                readonly property string label: root.displayName({ id: targetId, name: targetGroup.targetName })
                function changeCategory(value) {
                  if (category === value) return
                  var categories = Object.assign({}, root.pendingCategories)
                  categories[targetId] = value
                  root.pendingCategories = categories
                  root.runAgent(["classify", targetId, value])
                }
                function changeQuota(delta) {
                  var step = limitPeriod === "day" ? (quotaMinutes >= 60 ? 15 : 5) : 1
                  var next = Math.max(1, Math.min(limitPeriod === "day" ? 720 : 120, quotaMinutes + delta * step))
                  if (next === quotaMinutes) return
                  var quotas = Object.assign({}, root.pendingQuotas)
                  quotas[targetId] = next
                  root.pendingQuotas = quotas
                  root.runAgent(["quota", targetId, String(next)])
                }
                function changeLimitPeriod(value) {
                  if (limitPeriod === value) return
                  var periods = Object.assign({}, root.pendingLimitPeriods)
                  periods[targetId] = value
                  root.pendingLimitPeriods = periods
                  var quotas = Object.assign({}, root.pendingQuotas)
                  quotas[targetId] = value === "day" ? 60 : 10
                  root.pendingQuotas = quotas
                  root.runAgent(["limit-period", targetId, value])
                }
                function changeLimitAction(value) {
                  if (limitAction === value) return
                  var actions = Object.assign({}, root.pendingLimitActions)
                  actions[targetId] = value
                  root.pendingLimitActions = actions
                  root.runAgent(["limit-action", targetId, value])
                }
                width: parent.width
                implicitHeight: targetContent.implicitHeight + Style.space(18)
                radius: Style.cornerRadius
                color: root.softSurface
                border.width: Style.spacing.hairline
                border.color: root.outlineColor

                // On Now, the name opens the entry in Manage.
                MouseArea {
                  z: 1
                  x: targetContent.x
                  y: targetContent.y
                  width: nameBlock.width
                  height: targetHeader.height
                  enabled: root.page === "now" && targetGroup.configured
                  cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                  onClicked: root.revealCard(targetGroup, targetCard.targetId)
                }

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
                        text: targetCard.label
                        textFormat: Text.PlainText
                        color: root.textColor
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        font.bold: true
                        wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                      }

                      Text {
                        width: parent.width
                        text: (targetGroup.focused ? "●  " : "")
                          + (targetCard.targetId.startsWith("site:")
                            && targetCard.label.toLowerCase() !== targetCard.targetId.slice(5).toLowerCase()
                            ? targetCard.targetId.slice(5) + "  ·  " : "")
                          + (targetGroup.todaySeconds > 0 ? root.formatElapsed(targetGroup.todaySeconds) + " today" : "Not used today")
                          + (targetGroup.linked ? "  ·  " + targetGroup.members.length + " linked" : "")
                        textFormat: Text.PlainText
                        color: root.mutedText
                        font.pixelSize: Style.font.caption
                        elide: Text.ElideMiddle
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
                        text: targetGroup.remainingSeconds === 0 && targetGroup.limitReason === "focus" ? "Focus"
                          : targetGroup.remainingSeconds === 0 && targetGroup.limitReason === "budget" ? "Budget"
                          : root.formatTime(targetGroup.remainingSeconds >= 0 ? targetGroup.remainingSeconds
                            : targetCard.quotaMinutes * 60) + " left"
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
                      width: parent.width * Math.min(1, targetGroup.todaySeconds / root.maxTodaySeconds)
                      height: parent.height
                      radius: parent.radius
                      color: targetCard.category === "productive" ? root.productiveColor
                        : targetCard.category === "consumption" ? root.consumptionColor : root.mutedText
                      Behavior on width { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                    }
                  }

                  // Now stays a glance; classification and limits live in Review and Manage.
                  ChoiceRow {
                    visible: root.page !== "now" || !targetGroup.configured
                    choices: [{ id: "productive", label: "Productive" }, { id: "neutral", label: "Neutral" },
                      { id: "consumption", label: "Consumption" }]
                    current: targetCard.category
                    onChosen: function(id) { targetCard.changeCategory(id) }
                  }

                  Omarchy.Button {
                    objectName: "snoozeButton"
                    visible: targetGroup.canSnooze
                    width: parent.width
                    text: "5 more minutes"
                    tooltipText: "Once per limit period"
                    foreground: root.textColor
                    fontSize: Style.font.bodySmall
                    bordered: true
                    focusable: true
                    enabled: root.serviceConnected
                    onClicked: root.runAgent(["snooze", targetCard.targetId])
                  }

                  Stepper {
                    visible: targetCard.category === "consumption" && root.page !== "now"
                    label: targetCard.limitPeriod === "day" ? "Daily limit" : "Hourly limit"
                    valueText: root.formatQuota(targetCard.quotaMinutes)
                    onStep: function(direction) { targetCard.changeQuota(direction) }
                  }

                  Loader {
                    width: parent.width
                    active: targetGroup.expanded
                    visible: active
                    sourceComponent: Column {
                      spacing: Style.space(7)

                      ChoiceRow {
                        visible: targetCard.category === "consumption"
                        buttonName: "limitPeriodButton"
                        choices: [{ id: "hour", label: "Per hour" }, { id: "day", label: "Per day" }]
                        current: targetCard.limitPeriod
                        onChosen: function(id) { targetCard.changeLimitPeriod(id) }
                      }
                      Text {
                        visible: targetCard.category === "consumption"
                        text: "When limit is reached"
                        color: root.mutedText
                        font.pixelSize: Style.font.caption
                      }
                      ChoiceRow {
                        visible: targetCard.category === "consumption"
                        choices: [{ id: "close", label: "Close" }, { id: "notify", label: "Notify" },
                          { id: "keep_open", label: "Keep open" }]
                        current: targetCard.limitAction
                        onChosen: function(id) { targetCard.changeLimitAction(id) }
                      }

                      Text {
                        visible: targetGroup.scopeDomain !== "" && targetGroup.configured
                        width: parent.width
                        text: "Subdomains · " + targetGroup.familiesLabel
                        textFormat: Text.PlainText
                        elide: Text.ElideMiddle
                        color: root.mutedText
                        font.pixelSize: Style.font.caption
                      }
                      ChoiceRow {
                        visible: targetGroup.scopeDomain !== "" && targetGroup.configured
                        readonly property string mode: root.pendingSubdomainRules[targetGroup.domainFamily]
                          || root.subdomainRules[targetGroup.domainFamily] || "smart"
                        choices: [
                          { id: "smart", label: "Smart", hint: "Merge subdomains unless they declare their own app or category." },
                          { id: "group", label: "Group", hint: "Merge every site in this domain family." },
                          { id: "separate", label: "Separate", hint: "Keep sites in this domain family independent." }]
                        current: mode
                        buttonName: "subdomainModeButton"
                        enabled: root.serviceConnected
                        onChosen: function(id) { root.setSubdomainRule(targetGroup.scopeDomain, id, targetGroup.domainFamily) }
                      }

                      Repeater {
                        model: targetGroup.linked ? targetGroup.members : []
                        delegate: Row {
                          required property string modelData
                          width: parent.width
                          height: Style.space(26)
                          spacing: Style.space(8)
                          Text {
                            width: parent.width - detachButton.width - parent.spacing
                            height: parent.height
                            text: root.displayName({id: modelData, name: modelData.split(":").slice(1).join(":")})
                            textFormat: Text.PlainText
                            color: root.textColor
                            font.pixelSize: Style.font.bodySmall
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideMiddle
                          }
                          Omarchy.Button {
                            id: detachButton
                            height: parent.height
                            text: root.detachingMember === modelData ? "Detaching…" : "Detach"
                            foreground: root.textColor
                            fontSize: Style.font.caption
                            focusable: true
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

                      Row {
                        width: parent.width
                        spacing: Style.space(6)
                        TargetPicker {
                          id: mergePicker
                          objectName: "mergePicker"
                          width: parent.width - mergeButton.width - parent.spacing
                          triggerLabel: value ? "" : "Merge into…"
                          model: root.tracked.filter(function(row) {
                            return row.configured && row.id !== targetCard.targetId && root.ignoredTargets.indexOf(row.id) < 0
                          }).map(function(row) {
                            return { id: row.id, name: row.name, identity: row.id.split(":").slice(1).join(":") }
                          })
                          enabled: !root.mergingSource && !root.detachingMember
                          Component.onCompleted: root.activePicker = mergePicker
                        }
                        Omarchy.Button {
                          id: mergeButton
                          text: root.mergingSource === targetCard.targetId ? "Merging…" : "Merge"
                          foreground: root.textColor
                          fontSize: Style.font.caption
                          bordered: true
                          focusable: true
                          enabled: root.serviceConnected && !root.mergingSource && mergePicker.currentIndex >= 0
                          onClicked: root.mergeInto(targetCard.targetId, mergePicker.value)
                        }
                      }

                      Text {
                        width: parent.width
                        visible: text.length > 0
                        text: root.mergeFeedback || root.detachFeedback
                        color: root.mutedText
                        font.pixelSize: Style.font.caption
                        wrapMode: Text.WordWrap
                      }
                    }
                  }

                  Omarchy.Button {
                    objectName: "excludeTargetButton"
                    visible: root.page === "review" || targetGroup.expanded
                    width: parent.width
                    text: "Exclude from tracking"
                    foreground: root.textColor
                    fontSize: Style.font.bodySmall
                    bordered: true
                    focusable: true
                    onClicked: root.excludeTarget(targetCard.targetId)
                  }

                  Omarchy.Button {
                    objectName: "cardDetailsButton"
                    visible: root.page !== "now"
                    width: parent.width
                    height: Style.space(24)
                    text: targetGroup.expanded ? "Less" : "More"
                    foreground: root.mutedText
                    fontSize: Style.font.caption
                    focusable: true
                    onClicked: {
                      root.expandedCardId = targetGroup.expanded ? "" : targetCard.targetId
                      root.mergeFeedback = ""
                      root.detachFeedback = ""
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
                    : root.working ? "No open apps or sites"
                    : root.paused ? "Tracking paused"
                    : root.widget && root.widget.snapshot && root.widget.snapshot.idle ? "Paused while idle"
                    : "Outside tracking hours"
                  color: root.textColor
                  font.pixelSize: Style.font.body
                  font.bold: true
                }
                Text {
                  width: parent.width
                  text: root.page === "review" ? "New apps and sites will appear here."
                    : root.page === "manage" ? "Choose a role in Now or Review to save an app."
                    : root.working ? "Apps on displayed workspaces appear here while they are open."
                    : root.paused ? "Limits are paused too."
                    : "Activity counts during your tracking schedule."
                  textFormat: Text.PlainText
                  color: root.mutedText
                  font.pixelSize: Style.font.bodySmall
                  wrapMode: Text.WordWrap
                }
              }
            }

            // Excluded entries stay collapsed: private by default, one click to review.
            Column {
              visible: root.page === "manage" && root.manageSection === "apps" && root.filteredIgnored.length > 0
              width: parent.width
              spacing: Style.space(6)
              Omarchy.Button {
                objectName: "excludedToggle"
                width: parent.width
                text: "Excluded · " + root.filteredIgnored.length
                leftAlign: true
                selected: root.excludedOpen
                foreground: root.mutedText
                fontSize: Style.font.bodySmall
                focusable: true
                onClicked: root.excludedOpen = !root.excludedOpen
              }
              Repeater {
                model: root.excludedOpen ? root.filteredIgnored : []
                delegate: Row {
                  objectName: "excludedEntry"
                  required property string modelData
                  width: parent.width
                  height: Style.space(30)
                  spacing: Style.space(8)
                  Text {
                    width: parent.width - restoreButton.width - parent.spacing
                    height: parent.height
                    textFormat: Text.PlainText
                    text: root.displayName({ id: modelData, name: modelData.split(":").slice(1).join(":") })
                    color: root.textColor
                    font.pixelSize: Style.font.bodySmall
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                  }
                  Omarchy.Button {
                    id: restoreButton
                    height: parent.height
                    text: "Track again"
                    foreground: root.textColor
                    fontSize: Style.font.caption
                    bordered: true
                    focusable: true
                    onClicked: root.unexcludeTarget(modelData)
                  }
                }
              }
            }
            ManageHeader {
              label: "Connection & data"; section: "diagnostics"
              statusText: root.widget ? root.widget.connectionLabel : ""
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
                  : root.widget ? root.widget.connectionLabel : "")
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

            Column {
              visible: root.page === "manage" && root.manageSection === "diagnostics"
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
              spacing: Style.space(4)
              Text {
                text: "LAST 7 DAYS"
                color: root.mutedText
                font.pixelSize: Style.font.caption
                font.bold: true
              }
              Text {
                width: parent.width
                text: root.weekly.current ? root.formatElapsed(root.weekly.current.screen_seconds) + " screen time"
                  + (root.weekly.screen_delta !== null && root.weekly.screen_delta !== undefined
                    ? "  ·  " + (root.weekly.screen_delta >= 0 ? "+" : "−")
                      + root.formatElapsed(Math.abs(root.weekly.screen_delta)) + " vs last week" : "") : ""
                color: root.textColor
                font.pixelSize: Style.font.bodySmall
                font.bold: true
              }
              Text {
                width: parent.width
                text: root.weekly.current ? root.minutes(root.weekly.current.productive) + " productive  ·  "
                  + root.minutes(root.weekly.current.neutral) + " neutral  ·  " + root.minutes(root.weekly.current.consumption) + " consumed" : ""
                color: root.mutedText
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
            }

            Column {
              width: parent.width
              spacing: Style.space(2)
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
                delegate: Row {
                  id: historyRow
                  required property var modelData
                  readonly property real productive: Number(modelData.productive || 0)
                  readonly property real neutral: Number(modelData.neutral || 0)
                  readonly property real consumed: Number(modelData.consumption || 0)
                  readonly property real classified: productive + neutral + consumed
                  width: parent.width
                  height: Style.space(30)
                  spacing: Style.space(10)
                  HoverHandler { id: historyHover }
                  ToolTip.visible: historyHover.hovered
                  ToolTip.delay: 400
                  ToolTip.text: root.minutes(productive) + " productive · " + root.minutes(neutral) + " neutral · "
                    + root.minutes(consumed) + " consumed"
                  Text {
                    width: Style.space(58)
                    height: parent.height
                    text: Qt.formatDate(new Date(String(historyRow.modelData.day) + "T12:00:00"), "ddd d")
                    color: root.textColor
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                    verticalAlignment: Text.AlignVCenter
                  }
                  Rectangle {
                    width: parent.width - Style.space(58) - historyTotal.width - parent.spacing * 2
                    height: Style.space(6)
                    anchors.verticalCenter: parent.verticalCenter
                    radius: height / 2
                    color: root.hoverSurface
                    clip: true
                    Row {
                      anchors.fill: parent
                      Rectangle {
                        width: historyRow.classified > 0 ? parent.width * historyRow.productive / historyRow.classified : 0
                        height: parent.height
                        color: root.productiveColor
                      }
                      Rectangle {
                        width: historyRow.classified > 0 ? parent.width * historyRow.neutral / historyRow.classified : 0
                        height: parent.height
                        color: root.neutralColor
                      }
                      Rectangle {
                        width: historyRow.classified > 0 ? parent.width * historyRow.consumed / historyRow.classified : 0
                        height: parent.height
                        color: root.consumptionColor
                      }
                    }
                  }
                  Text {
                    id: historyTotal
                    width: Style.space(64)
                    height: parent.height
                    text: historyRow.modelData.screen_seconds !== undefined
                      ? root.formatElapsed(historyRow.modelData.screen_seconds) : root.minutes(historyRow.classified)
                    color: root.mutedText
                    font.pixelSize: Style.font.caption
                    horizontalAlignment: Text.AlignRight
                    verticalAlignment: Text.AlignVCenter
                  }
                }
              }
            }

            Omarchy.Toggle {
              objectName: "weeklyToggle"
              width: parent.width
              label: "Weekly summary"
              description: "A notification each Monday"
              checked: weeklySetting.current
              foreground: root.textColor
              titleSize: Style.font.bodySmall
              onClicked: weeklySetting.set(!weeklySetting.current, ["weekly-summary", weeklySetting.current ? "off" : "on"])
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
