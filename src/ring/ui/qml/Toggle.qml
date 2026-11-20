import QtQuick
import QtQuick.Controls

Switch {
    id: control
    implicitHeight: 32
    spacing: 9
    padding: 0
    indicator: Rectangle {
        implicitWidth: 36; implicitHeight: 22
        x: control.leftPadding
        y: (control.height - height) / 2
        radius: 11
        opacity: control.enabled ? 1 : 0.5
        color: control.checked ? Theme.accent : "#c7cdda"
        Behavior on color { ColorAnimation { duration: 120 } }
        border.color: control.activeFocus ? "#43379e" : "transparent"
        Rectangle {
            width: 18; height: 18; radius: 9; y: 2
            x: control.checked ? 16 : 2
            color: "white"
            Behavior on x { NumberAnimation { duration: 100 } }
        }
    }
    contentItem: Text {
        text: control.text
        leftPadding: control.indicator.width + control.spacing
        verticalAlignment: Text.AlignVCenter
        font.pixelSize: 13
        color: control.enabled ? Theme.secondary : Theme.disabledText
    }
}
