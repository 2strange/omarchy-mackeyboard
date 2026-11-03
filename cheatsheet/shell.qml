import QtQuick
import Quickshell
import Quickshell.Io

// Cheat sheet: every character of your layout's Mac variant on Option and Shift+Option, read
// from libxkbcommon by keyboard-config.py. Run with `qs -p <this folder>`; Esc closes it.
ShellRoot {
  id: shell

  // A plain path: Quickshell turns a URL that leaves its config folder ("../") into qrc:/qs-blackhole.
  readonly property string helper: Quickshell.shellDir + "/../keyboard-config.py"
  property var sheet: ({ rows: [] })
  property string error: ""
  // Characters people look for most when they come from a Mac: shown brighter.
  readonly property string wanted: "@|\\{}[]~€≠…–—„“”‚‘’«»"

  readonly property color bg: "#1e1e22"
  readonly property color fg: "#e8e6e3"
  readonly property color dim: "#8a8780"
  readonly property color surface: "#2c2c32"
  readonly property color accent: "#e0913a"

  Process {
    command: ["python3", "-I", shell.helper, "cheatsheet"]
    running: true
    stdout: StdioCollector {
      onStreamFinished: {
        try { shell.sheet = JSON.parse(text) } catch (e) { shell.error = "Could not read your layout (" + e + ")"; return }
        if (shell.sheet.error) shell.error = shell.sheet.error
      }
    }
  }

  FloatingWindow {
    id: win
    title: "Mac Keyboard: Option characters"
    color: shell.bg
    implicitWidth: 980
    implicitHeight: 470
    onVisibleChanged: if (!visible) Qt.quit()  // closed by the compositor (Super+W): end the qs process too
    // Hyprland may tile the window: the keys scale with its width (13 keys plus the row offsets).
    readonly property real cap: Math.max(34, Math.min(72, (width - 48 - 12 * 6 - 46) / 13))

    Item {
      anchors.fill: parent
      focus: true
      Keys.onEscapePressed: Qt.quit()

      Column {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 16

        Column {
          spacing: 4
          Text { text: "Option characters"; color: shell.fg; font.pixelSize: 22; font.bold: true }
          Text {
            textFormat: Text.PlainText
            text: shell.error !== "" ? shell.error
              : "Layout " + (shell.sheet.layout || "?") + (shell.sheet.variant ? " (" + shell.sheet.variant + ")" : "")
                + ". Big: right Option + key. Small: right Option + Shift + key. Underlined: a dead key, type the next letter after it."
            color: shell.dim; font.pixelSize: 13; width: win.width - 48; wrapMode: Text.WordWrap
          }
        }

        Repeater {
          model: shell.sheet.rows
          delegate: Row {
            id: keyRow
            required property var modelData
            required property int index
            spacing: 6
            leftPadding: ([0, 0.5, 0.7, 0.33][keyRow.index] || 0) * win.cap
            Repeater {
              model: keyRow.modelData
              delegate: Rectangle {
                id: cap
                required property var modelData
                readonly property bool hot: modelData.option !== "" && shell.wanted.indexOf(modelData.option) >= 0
                readonly property bool hotShift: modelData.shift_option !== "" && shell.wanted.indexOf(modelData.shift_option) >= 0
                width: win.cap
                height: win.cap * 1.1
                radius: 8
                color: shell.surface
                border.width: hot || hotShift ? 2 : 1
                border.color: hot || hotShift ? shell.accent : "#44444c"
                Text {
                  anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 6
                  textFormat: Text.PlainText
                  text: cap.modelData.base
                  color: shell.dim; font.pixelSize: Math.max(10, win.cap * 0.2)
                }
                Text {
                  anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 6
                  textFormat: Text.PlainText
                  text: cap.modelData.shift_option
                  color: cap.hotShift ? shell.accent : shell.dim; font.pixelSize: Math.max(11, win.cap * 0.23)
                }
                Text {
                  anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 6
                  textFormat: Text.PlainText
                  text: cap.modelData.option
                  color: cap.hot ? shell.accent : shell.fg; font.pixelSize: Math.max(16, win.cap * 0.4); font.bold: cap.hot
                }
              }
            }
          }
        }
      }
    }
  }
}
