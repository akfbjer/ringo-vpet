import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool primary: false
    property bool danger: false
    implicitHeight: 40
    implicitWidth: Math.max(84, label.implicitWidth + 30)
    hoverEnabled: true
    padding: 12
    contentItem: Text {
        id: label
        text: control.text
        font.pixelSize: 13
        font.weight: Font.Medium
        color: !control.enabled ? Theme.disabledText : control.primary ? "white" : control.danger ? "#bf4b60" : Theme.secondary
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 10
        color: !control.enabled ? Theme.disabledSurface : control.primary ? (control.down ? Theme.accentPressed : control.hovered ? Theme.accentHover : Theme.accent) : control.down ? Theme.accentSoft : control.hovered ? Theme.surfaceHover : Theme.surface
        border.color: control.activeFocus ? Theme.accent : control.primary && control.enabled ? "transparent" : control.hovered && control.enabled ? Theme.borderHover : Theme.border
        border.width: control.activeFocus ? 2 : 1
        Behavior on color { ColorAnimation { duration: 100 } }
    }
}
