import QtQuick
import QtQuick.Layouts
import Ring 1.0

Panel {
    id: panel
    property var deviceInfo
    property bool drawing: true
    readonly property bool ringo: deviceInfo.driver === "ringo"
    readonly property string deviceAddress: String(deviceInfo.address)
    readonly property string deviceName: String(deviceInfo.name)
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 6
        RowLayout {
            Layout.fillWidth: true
            Heading { text: panel.deviceName; elide: Text.ElideRight; Layout.fillWidth: true }
            Caption { text: panel.deviceAddress.slice(-8); font.pixelSize: 10 }
            Caption { text: Number(panel.deviceInfo.fps).toFixed(0) + " Hz" }
            Repeater {
                visible: !panel.ringo
                model: [{t:"X", c:"#7465df"}, {t:"Y", c:"#27a99c"}, {t:"Z", c:"#dd9560"}]
                delegate: Text { visible: !panel.ringo; required property var modelData; text: "— " + modelData.t; color: modelData.c; font.pixelSize: 10; Layout.leftMargin: 6 }
            }
        }
        Caption { visible: !panel.ringo; text: "加速度  ·  ±" + accTrace.yLimit + " m/s²"; Layout.topMargin: 8 }
        Trace {
            visible: !panel.ringo
            id: accTrace
            objectName: "acc-" + panel.deviceAddress
            address: panel.deviceAddress; running: panel.drawing && !panel.ringo; autoRange: studio.autoRange
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 80; channel: 0
        }
        Caption { visible: !panel.ringo; text: "角速度  ·  ±" + gyrTrace.yLimit + " rad/s" }
        Trace {
            visible: !panel.ringo
            id: gyrTrace
            objectName: "gyr-" + panel.deviceAddress
            address: panel.deviceAddress; running: panel.drawing && !panel.ringo; autoRange: studio.autoRange
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 80; channel: 3
        }
        RingoImuPlot { visible: panel.ringo; address: panel.deviceAddress; channel: 0; drawing: panel.drawing; automaticRange: studio.autoRange; Layout.fillHeight: true }
        RingoImuPlot { visible: panel.ringo; address: panel.deviceAddress; channel: 3; drawing: panel.drawing; automaticRange: studio.autoRange; Layout.fillHeight: true }
        RowLayout {
            visible: !panel.ringo
            Layout.fillWidth: true
            Caption { text: "−6 s"; font.pixelSize: 10 }
            Item { Layout.fillWidth: true }
            Caption { text: "现在"; font.pixelSize: 10 }
        }
    }
}
