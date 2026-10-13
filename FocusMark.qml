import QtQuick
import QtQuick.Window

// The Focus mark, drawn from assets/focus.svg's geometry as a themed vector image.
// Antialiased like the bar's font icons, so it stays symmetric and centred at
// fractional scales where pixel-snapped rectangles cannot.
// The dot is filled while tracking, hollow when off, and larger and accented
// during a focus session.
Item {
  id: mark
  property color color: "white"
  property color accent: color
  property bool active: true
  property bool session: false
  property real size: 12

  implicitWidth: size
  implicitHeight: size
  width: size
  height: size

  function hex(value) {
    return "#" + [value.r, value.g, value.b].map(function(channel) {
      return Math.round(channel * 255).toString(16).padStart(2, "0")
    }).join("")
  }
  // Corners from the logo path (square caps included in the 32–96 view box).
  readonly property string svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="32 32 64 64">'
    + '<path d="M48 36H36v12m44-12h12v12M36 80v12h12m44-12v12H80" fill="none" stroke="' + hex(color)
    + '" stroke-width="7" stroke-linecap="square"/>'
    + (session ? '<circle cx="64" cy="64" r="15" fill="' + hex(accent) + '"/>'
       : active ? '<circle cx="64" cy="64" r="12" fill="' + hex(color) + '"/>'
       : '<circle cx="64" cy="64" r="9.5" fill="none" stroke="' + hex(color) + '" stroke-width="5"/>')
    + '</svg>'

  Image {
    anchors.fill: parent
    source: "data:image/svg+xml;utf8," + encodeURIComponent(mark.svg)
    sourceSize.width: Math.ceil(mark.size * Screen.devicePixelRatio)
    sourceSize.height: Math.ceil(mark.size * Screen.devicePixelRatio)
    smooth: true
    mipmap: true
    cache: false
  }
}
