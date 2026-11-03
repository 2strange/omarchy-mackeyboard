import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Mac Keyboard popup: the Fn switch (Mac functions on/off) with a legend of the
// function row, the Mac layout switch (right Option as on a Mac) with a cheat
// sheet window, and what the special keys of this Mac do. The Fn state and its
// privileged toggle live in Service.qml; layout and keys go through
// keyboard-config.py, which writes ~/.config/hypr/mackeyboard.lua.
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
    root.refreshCfg()
  }
  function openFromHotkey() {
    root.controller.show()
    if (service) service.refresh()
    root.refreshCfg()
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

  // ---- layout and special keys (keyboard-config.py)
  readonly property string helper: decodeURIComponent(Qt.resolvedUrl("keyboard-config.py").toString().replace(/^file:\/\//, ""))
  readonly property string cheatsheetDir: decodeURIComponent(Qt.resolvedUrl("cheatsheet").toString().replace(/^file:\/\//, ""))
  property var cfg: ({})
  property string cfgError: ""
  readonly property var myKeys: (cfg.keys || []).filter(function(k) { return k.mine })
  readonly property var actionOptions: (cfg.actions || []).map(function(a) {
    return { value: a.value, label: a.value === "command" ? "Own command…" : a.label }
  })
  function refreshCfg() {
    if (!readProc.running && !writeProc.running) readProc.running = true
  }
  function runConfig(args) {
    if (writeProc.running) return
    writeProc.command = ["python3", "-I", root.helper].concat(args)
    writeProc.running = true
  }
  Process {
    id: readProc
    command: ["python3", "-I", root.helper, "get"]
    stdout: StdioCollector {
      onStreamFinished: { try { root.cfg = JSON.parse(text) } catch (e) { console.warn("mackeyboard: bad json", e) } }
    }
  }
  Process {
    id: writeProc
    stderr: StdioCollector { id: writeErr }
    onExited: function(code) {
      root.cfgError = code === 0 ? "" : code === 1 ? "Hyprland rejected the change, rolled back"
        : (writeErr.text.trim().replace(/^keyboard-config: /, "") || "Could not apply the change")
      if (code !== 0) console.warn("keyboard-config failed", code, writeErr.text)
      root.refreshCfg()
    }
  }

  // Function row: F1-F2 and F7-F12 are the same on every Mac with F keys; F3-F6 come
  // from keyboard-config.py for this Mac (Intel: Launchpad, keyboard light; Apple Silicon:
  // Spotlight, Dictation, Do Not Disturb).
  readonly property var keys: {
    var mid = {}
    var mine = root.myKeys
    for (var i = 0; i < mine.length; i++)
      mid[mine[i].fn] = mid[mine[i].fn] ? mid[mine[i].fn] + " / " + mine[i].label : mine[i].label
    return [
      ["F1", "Brightness down"], ["F2", "Brightness up"],
      ["F3", mid.F3 || "Mission Control"], ["F4", mid.F4 || "Launchpad / Spotlight"],
      ["F5", mid.F5 || "Keyboard light / Dictation"], ["F6", mid.F6 || "Keyboard light / Do Not Disturb"],
      ["F7", "Previous track"], ["F8", "Play / pause"],
      ["F9", "Next track"], ["F10", "Mute"],
      ["F11", "Volume down"], ["F12", "Volume up"]
    ]
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
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
            Text { text: "Mac Keyboard"; color: root.fg; font.family: root.fontFam; font.pixelSize: Style.font.title; font.bold: true; width: parent.width; elide: Text.ElideRight }
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
              text: !root.service ? ""
                : !root.service.available ? "Not available here: this keyboard is not an Apple keyboard driven by hid_apple (in a VM the host handles the function row)."
                : !root.ready ? "Needs a one-time setup that installs a small root helper (asks for your password once)."
                : root.macOn
                ? "F keys run the printed functions. Hold Fn for F1–F12."
                : "F keys send F1–F12. Hold Fn for the printed functions."
              color: root.dim; font.family: root.fontFam; font.pixelSize: Style.font.caption; width: parent.width; wrapMode: Text.WordWrap
            }
          }
          ToggleSwitch {
            id: sw
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            visible: root.ready
            checked: root.macOn
            enabled: root.ready && !root.busy
            foreground: root.fg
            onToggled: if (root.service) root.service.toggle()
          }
          Button {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            visible: !root.ready && !!root.service && root.service.available
            text: "Set up"
            tooltipText: "Opens a terminal for the one-time setup (asks for your password once)"
            bordered: true
            foreground: root.fg
            fontFamily: root.fontFam
            fontSize: Style.font.caption
            onClicked: root.service.runSetup()
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

        PanelSeparator { width: parent.width; foreground: root.fg }

        // ---------- Mac layout ----------
        Item {
          width: parent.width
          implicitHeight: Math.max(layoutLabels.implicitHeight, layoutSwitch.implicitHeight)
          Column {
            id: layoutLabels
            anchors.left: parent.left
            anchors.right: layoutSwitch.left
            anchors.rightMargin: Style.space(12)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)
            Text { text: "Mac keyboard layout"; color: root.fg; font.family: root.fontFam; font.pixelSize: Style.font.body; width: parent.width; elide: Text.ElideRight }
            Text {
              textFormat: Text.PlainText
              text: root.cfg.mac_available === false
                ? "Your layout (" + (root.cfg.layout || "?") + ") has no Mac variant."
                : root.cfg.mac_layout
                  ? "Right Option types as on a Mac: ⌥L @   ⌥7 |   ⌥⇧7 \\   ⌥8 {   ⌥9 }   ⌥5 [   ⌥6 ]   ⌥N ~"
                  : "Right Option is AltGr, as on a PC keyboard. Switch on for the Mac characters (⌥L @ and more)."
              color: root.dim; font.family: root.fontFam; font.pixelSize: Style.font.caption; width: parent.width; wrapMode: Text.WordWrap
            }
          }
          ToggleSwitch {
            id: layoutSwitch
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            checked: !!root.cfg.mac_layout
            enabled: root.cfg.mac_available === true && !writeProc.running
            foreground: root.fg
            onToggled: root.runConfig(["set", "mac_layout=" + (root.cfg.mac_layout ? "false" : "true")])
          }
        }
        Button {
          text: "All Option characters…"
          tooltipText: "Open a window with every character of your layout on Option and Shift+Option"
          bordered: true
          foreground: root.fg
          fontFamily: root.fontFam
          fontSize: Style.font.caption
          onClicked: Quickshell.execDetached(["qs", "-p", root.cheatsheetDir])
        }

        // ---------- Special keys ----------
        PanelSectionHeader {
          text: "SPECIAL KEYS" + (root.cfg.model ? " · " + root.cfg.model : "")
          foreground: root.fg
          fontFamily: root.fontFam
        }
        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: root.cfg.family === "unknown"
            ? "This is not a Mac the plugin recognizes, so every special key is listed. They act while Mac functions are on."
            : "The keys that differ between Mac generations. They act while Mac functions are on."
          color: root.dim; font.family: root.fontFam; font.pixelSize: Style.font.caption; wrapMode: Text.WordWrap
        }
        Repeater {
          model: root.myKeys
          delegate: Column {
            id: keyRow
            required property var modelData
            width: column.width
            spacing: Style.space(4)
            property bool editing: false
            Item {
              width: parent.width
              implicitHeight: Math.max(keyLabel.implicitHeight, keyChoice.implicitHeight)
              Text {
                id: keyLabel
                anchors.left: parent.left
                anchors.right: keyChoice.left
                anchors.rightMargin: Style.space(12)
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: keyRow.modelData.fn + "  " + keyRow.modelData.label
                color: root.fg; font.family: root.fontFam; font.pixelSize: Style.font.body; elide: Text.ElideRight
              }
              Dropdown {
                id: keyChoice
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(190)
                showLabel: false
                options: root.actionOptions
                value: keyRow.editing ? "command" : keyRow.modelData.action
                foreground: root.fg
                fontFamily: root.fontFam
                onChanged: function(v) {
                  if (v === "command") { keyRow.editing = true; return }
                  keyRow.editing = false
                  root.runConfig(["set", "key." + keyRow.modelData.keysym + "=" + v])
                }
              }
            }
            Item {
              visible: keyRow.editing || keyRow.modelData.action === "command"
              width: parent.width
              implicitHeight: visible ? Math.max(cmdField.implicitHeight, cmdSet.implicitHeight) : 0
              TextField {
                id: cmdField
                anchors.left: parent.left
                anchors.right: cmdSet.left
                anchors.rightMargin: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter
                text: keyRow.modelData.command || ""
                placeholderText: "command, e.g. omarchy-shell -q macos.dock altTabNext"
                foreground: root.fg
                onAccepted: cmdSet.clicked()
              }
              Button {
                id: cmdSet
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: "Set"
                bordered: true
                enabled: cmdField.text.trim() !== "" && !writeProc.running
                foreground: root.fg
                fontFamily: root.fontFam
                fontSize: Style.font.caption
                onClicked: { keyRow.editing = false; root.runConfig(["set-command", keyRow.modelData.keysym, cmdField.text.trim()]) }
              }
            }
          }
        }
        Text {
          visible: root.cfgError !== ""
          width: parent.width
          textFormat: Text.PlainText
          text: root.cfgError
          color: root.fg; font.family: root.fontFam; font.pixelSize: Style.font.caption; wrapMode: Text.WordWrap
        }
      }
    }
  }
}
