import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui

// Bar icon for the MacBook function row. State lives in Service.qml so all
// bars agree. Left click opens the menu (Panel.qml), right click toggles.
BarWidget {
  id: root
  moduleName: "io.github.2strange.mackeyboard"

  // Omarchy 4.x hands third-party widgets a scoped PluginShellApi
  // (bar.shell.serviceFor) instead of ShellRoot._services. The lookup is not
  // reactive, so retry until the shell has created the service.
  property var service: null
  function lookupService() {
    var shell = bar ? bar.shell : null
    var found = shell && typeof shell.serviceFor === "function" ? shell.serviceFor(moduleName) : null
    if (found !== service) service = found
  }
  onBarChanged: { lookupService(); injectPanel() }
  onServiceChanged: injectPanel()
  Component.onCompleted: lookupService()
  Timer {
    interval: 500
    repeat: true
    running: !root.service
    onTriggered: root.lookupService()
  }
  readonly property bool available: service ? service.available : false
  readonly property bool ready: service ? service.ready : false
  readonly property string mode: service ? service.mode : "unavailable"

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
    if ("service" in target) target.service = root.service
  }

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  function open() { if (panelLoader.item && panelLoader.item.openFromHotkey) panelLoader.item.openFromHotkey() }
  function close() { if (panelLoader.item && panelLoader.item.close) panelLoader.item.close() }
  function togglePanel() { if (panelLoader.item && panelLoader.item.toggle) panelLoader.item.toggle() }
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: { root.injectPanel(); Qt.callLater(root.injectPanel) }
  }

  IpcHandler {
    target: "io.github.2strange.mackeyboard"
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.togglePanel() }
  }

  // Apple logo (nf-fa-apple). Bright = Mac functions on, dimmed = plain F1-F12 or no Fn switch here.
  readonly property string glyph: "\uf179"
  readonly property bool macOn: mode === "media"

  readonly property string tooltip: {
    if (!service) return "Mac Keyboard is loading"
    if (!available) return "Mac Keyboard: layout and keys (no Apple function row here)"
    if (!service.setupDone) return "Mac Keyboard: the Fn switch needs a one-time setup (see the menu)"
    if (service.sudoDenied) return "Mac Keyboard: the Fn setup is incomplete (see the menu)"
    if (service.busy) return "Switching function-row mode"
    if (mode === "media") return "Mac functions on (right-click to switch)"
    if (mode === "fkeys") return "Mac functions off (right-click to switch)"
    return "Function row is in an unmanaged mode"
  }

  // Shown on every machine: the Mac layout switch works without an Apple keyboard too
  // (e.g. in a VM); the Fn part of the menu says when it is not available.
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.glyph
    tooltipText: root.tooltip
    dimmed: root.service ? (root.service.busy || !root.ready || !root.macOn) : false
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.togglePanel()
      else if (buttonCode === Qt.RightButton && root.ready) root.service.toggle()
    }
  }
}
