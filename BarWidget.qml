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

  // Apple logo (nf-fa-apple). Bright = Mac functions on, dimmed = plain F1-F12.
  readonly property string glyph: ready ? "\uf179" : "󰌌"
  readonly property bool macOn: mode === "media"

  readonly property string tooltip: {
    if (!service) return "Function keys service is loading"
    if (!available) return "This keyboard is not driven by hid_apple"
    if (!service.setupDone) return "Function keys: click to run the one-time setup"
    if (service.sudoDenied) return "Function keys: setup is incomplete, click to run it again"
    if (service.busy) return "Switching function-row mode"
    if (mode === "media") return "Mac Fn keys on (right-click to switch)"
    if (mode === "fkeys") return "Mac Fn keys off (right-click to switch)"
    return "Function row is in an unmanaged mode"
  }

  // Nothing to show on machines without an Apple keyboard.
  visible: available
  implicitWidth: available ? button.implicitWidth : 0
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.glyph
    tooltipText: root.tooltip
    dimmed: root.service ? (root.service.busy || (root.ready && !root.macOn)) : false
    onPressed: function(buttonCode) {
      if (!root.service) return
      if (!root.ready) { if (buttonCode === Qt.LeftButton) root.service.runSetup(); return }
      if (buttonCode === Qt.RightButton) root.service.toggle()
      else if (buttonCode === Qt.LeftButton) root.togglePanel()
    }
  }
}
