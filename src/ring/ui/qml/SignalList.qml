import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var snapshot
    ListView {
        id: signals
        objectName: "signals"
        anchors.fill: parent
        clip: true
        spacing: 16
        model: studio.connectedDevices
        cacheBuffer: 0
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        delegate: SignalPanel {
            required property var device
            required property int index
            deviceInfo: device
            objectName: "signal-" + device.address
            width: signals.width - 12
            height: signals.count === 1 ? Math.max(device.driver === "ringo" ? 420 : 340, signals.height) : Math.max(device.driver === "ringo" ? 420 : 290, (signals.height - signals.spacing) / 2)
            drawing: root.visible && y + height > signals.contentY && y < signals.contentY + signals.height
        }
    }
    Panel {
        anchors.fill: parent
        visible: signals.count === 0
        Caption { anchors.centerIn: parent; text: "连接设备后显示波形" }
    }
    Connections {
        target: studio
        function onSelectedChanged() {
            let connected = root.snapshot.devices.filter(d => d.connected)
            let index = connected.findIndex(d => d.address === studio.selected)
            if (index >= 0) signals.positionViewAtIndex(index, ListView.Contain)
        }
    }
}
