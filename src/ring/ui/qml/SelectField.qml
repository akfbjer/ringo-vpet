import QtQuick
import QtQuick.Controls

ComboBox {
    id: control
    implicitWidth: 230
    implicitHeight: 42
    leftPadding: 14
    rightPadding: 38
    hoverEnabled: true
    font.pixelSize: 13
    Accessible.name: displayText

    contentItem: Text {
        text: control.displayText
        font: control.font
        color: control.enabled ? Theme.ink : Theme.muted
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Item {
        width: 12; height: 8
        x: control.width - control.rightPadding + 10
        y: (control.height - height) / 2
        rotation: control.popup.visible ? 180 : 0
        Behavior on rotation { NumberAnimation { duration: 140 } }
        Rectangle {
            x: 1; y: 3; width: 7; height: 1.5; radius: 1; rotation: 45
            color: control.enabled ? Theme.secondary : Theme.disabledText
        }
        Rectangle {
            x: 5; y: 3; width: 7; height: 1.5; radius: 1; rotation: -45
            color: control.enabled ? Theme.secondary : Theme.disabledText
        }
    }
    background: Rectangle {
        radius: 10
        color: control.enabled ? Theme.surface : Theme.disabledSurface
        border.width: 1
        border.color: control.activeFocus || control.popup.visible ? Theme.accent
                    : control.hovered && control.enabled ? Theme.borderHover : Theme.border
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
    delegate: ItemDelegate {
        id: option
        required property int index
        width: ListView.view ? ListView.view.width : control.width - 12
        height: 38
        highlighted: control.highlightedIndex === index
        hoverEnabled: true
        leftPadding: 12; rightPadding: 30
        contentItem: Text {
            text: control.textAt(option.index)
            font.pixelSize: 13
            font.weight: option.index === control.currentIndex ? Font.Medium : Font.Normal
            color: option.index === control.currentIndex ? Theme.accent : Theme.ink
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 7
            color: option.highlighted ? Theme.accentSoft : option.hovered ? Theme.surfaceHover : "transparent"
        }
        Rectangle {
            visible: option.index === control.currentIndex
            anchors.right: parent.right; anchors.rightMargin: 13
            anchors.verticalCenter: parent.verticalCenter
            width: 5; height: 5; radius: 3; color: Theme.accent
        }
    }
    popup: Popup {
        y: control.height + 6
        width: control.width
        padding: 6
        implicitHeight: Math.min(contentItem.implicitHeight + topPadding + bottomPadding, 268)
        popupType: Popup.Item
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            spacing: 2
            boundsBehavior: Flickable.StopAtBounds
            ScrollIndicator.vertical: ScrollIndicator { }
        }
        background: Rectangle {
            radius: 12; color: Theme.surface; border.color: Theme.border
            Rectangle {
                z: -1; x: -2; y: 3
                width: parent.width + 4; height: parent.height + 3
                radius: 14; color: "#0a252b3c"
            }
        }
        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 100 }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 80 }
        }
    }
}
