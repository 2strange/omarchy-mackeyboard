import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

// Mac Fn keys popup. One switch (Mac functions on/off) plus a legend of
// what the function row does in each mode. State and the privileged toggle live
// in Service.qml; this file only paints it.
Panel {
  id: root
  moduleName: "io.github.2strange.mackeyboard"
  ipcTarget: "io.github.2strange.mackeyboard"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var service: null
  readonly property var barIdentity: hostWidget || root

  readonly property bool ready: service ? service.ready : false
  readonly property bool macOn: service ? service.mode === "media" : false
  readonly property bool busy: service ? service.busy : false

  function open() {
    setCenterHoverRevealSuppressed(false)
    root.controller.show()
    if (service) service.refresh()
  }
  function openFromHotkey() {
    root.controller.show()
    if (service) service.refresh()
    Qt.callLater(function() { if (root.opened) setCenterHoverRevealSuppressed(true) })
  }
  // Hide first, so the overlay goes away even if anything after this throws.
  function close() {
    root.controller.hide()
    setCenterHoverRevealSuppressed(false)
  }
  function toggle() {
    if (root.opened) root.close()
    else root.openFromHotkey()
  }
  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }
  function setCenterHoverRevealSuppressed(value) {
    if (root.bar && typeof root.bar.setCenterHoverRevealSuppressed === "function")
      root.bar.setCenterHoverRevealSuppressed(value)
    else if (root.bar && "centerHoverRevealSuppressed" in root.bar)
      root.bar.centerHoverRevealSuppressed = value
  }

  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.4)
  readonly property string fontFam: bar ? bar.fontFamily : Style.font.family

  readonly property string statusText: {
    if (!service) return "Loading"
    if (service.lastError !== "") return service.lastError
    if (busy) return "Switching"
    return macOn ? "Mac functions on" : "Mac functions off"
  }

  // Function row of the MacBook Pro 2013-2015 (hid_apple apple_fn_keys table).
  readonly property var keys: [
    ["F1", "Brightness down"], ["F2", "Brightness up"],
    ["F3", "Mission Control"], ["F4", "Launchpad (menu)"],
    ["F5", "Keyboard light down"], ["F6", "Keyboard light up"],
    ["F7", "Previous track"], ["F8", "Play / pause"],
    ["F9", "Next track"], ["F10", "Mute"],
    ["F11", "Volume down"], ["F12", "Volume up"]
  ]

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        anchors.fill: parent
        spacing: Style.space(14)

        // ---------- Hero ----------
        Item {
          width: parent.width
          implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)
          Text {
            id: heroIcon
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: ""
            color: root.macOn ? root.fg : root.dim
            font.family: root.fontFam
            font.pixelSize: Style.font.display
          }
          Column {
            id: heroLabels
            anchors.left: heroIcon.right
            anchors.leftMargin: Style.space(14)
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)
            Text { text: "Mac Fn keys"; color: root.fg; font.family: root.fontFam; font.pixelSize: Style.font.title; font.bold: true; width: parent.width; elide: Text.ElideRight }
            Text { text: root.statusText.toUpperCase(); color: root.dim; font.family: root.fontFam; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1.2; width: parent.width; elide: Text.ElideRight }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.fg }

        // ---------- Switch ----------
        Item {
          width: parent.width
          implicitHeight: Math.max(switchLabels.implicitHeight, sw.implicitHeight)
          Column {
            id: switchLabels
            anchors.left: parent.left
            anchors.right: sw.left
            anchors.rightMargin: Style.space(12)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)
            Text { text: "Mac function keys"; color: root.fg; font.family: root.fontFam; font.pixelSize: Style.font.body; width: parent.width; elide: Text.ElideRight }
            Text {
              text: root.macOn
                ? "F keys run the printed functions. Hold Fn for F1–F12."
                : "F keys send F1–F12. Hold Fn for the printed functions."
              color: root.dim; font.family: root.fontFam; font.pixelSize: Style.font.caption; width: parent.width; wrapMode: Text.WordWrap
            }
          }
          ToggleSwitch {
            id: sw
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            checked: root.macOn
            enabled: root.ready && !root.busy
            foreground: root.fg
            onToggled: if (root.service) root.service.toggle()
          }
        }

        // ---------- Legend ----------
        PanelSectionHeader {
          text: root.macOn ? "WITHOUT FN" : "WITH FN"
          foreground: root.fg
          fontFamily: root.fontFam
        }
        Grid {
          width: parent.width
          columns: 2
          columnSpacing: Style.space(12)
          rowSpacing: Style.space(4)
          Repeater {
            model: root.keys
            delegate: Row {
              required property var modelData
              width: (column.width - Style.space(12)) / 2
              spacing: Style.space(8)
              Text { text: modelData[0]; width: Style.space(28); color: root.fg; font.family: root.fontFam; font.pixelSize: Style.font.caption; font.bold: true }
              Text { text: modelData[1]; width: parent.width - Style.space(36); color: root.dim; font.family: root.fontFam; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
            }
          }
        }

        Text {
          width: parent.width
          text: "Persists in /etc/modprobe.d/hid_apple.conf and is re-applied at login. Right-click the icon to switch without opening this menu."
          color: root.dim
          font.family: root.fontFam
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
