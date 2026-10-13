import QtQuick

// The Focus mark: viewfinder corners around a dot, drawn to the bar's icon metrics.
// The dot is filled while tracking, hollow when off, and accented during a session.
Item {
  id: mark
  property color color: "white"
  property color accent: color
  property bool active: true
  property bool session: false
  property int size: 12
  readonly property int stroke: Math.max(1, Math.round(size / 9))
  readonly property int arm: Math.max(3, Math.round(size * 0.3))
  implicitWidth: size
  implicitHeight: size
  width: size
  height: size

  Repeater {
    model: [[0, 0], [1, 0], [0, 1], [1, 1]]
    delegate: Item {
      required property var modelData
      anchors.fill: parent
      Rectangle {
        x: modelData[0] ? mark.size - mark.arm : 0
        y: modelData[1] ? mark.size - mark.stroke : 0
        width: mark.arm
        height: mark.stroke
        color: mark.color
      }
      Rectangle {
        x: modelData[0] ? mark.size - mark.stroke : 0
        y: modelData[1] ? mark.size - mark.arm : 0
        width: mark.stroke
        height: mark.arm
        color: mark.color
      }
    }
  }

  Rectangle {
    // Odd diameter keeps the dot on the pixel grid at the exact centre.
    // A larger dot marks a session even when the theme accent is close to the foreground.
    readonly property int diameter: Math.round(mark.size * (mark.session ? 0.5 : 0.34)) | 1
    anchors.centerIn: parent
    width: diameter
    height: diameter
    radius: diameter / 2
    color: mark.session ? mark.accent : mark.active ? mark.color : "transparent"
    border.width: mark.active || mark.session ? 0 : mark.stroke
    border.color: mark.color
  }
}
