import QtQuick
import QtQuick.Layouts
import Ring 1.0

Panel {
    id: plot
    property string address: ""
    property int channel: 0
    property bool drawing: true
    property bool automaticRange: true
    Layout.fillWidth: true
    implicitHeight: 185
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 12; spacing: 4
        RowLayout {
            Layout.fillWidth: true
            Caption { text: plot.channel === 0 ? "加速度 · m/s²" : "角速度 · °/s"; Layout.fillWidth: true }
            Repeater {
                model: plot.channel === 0 ? ["#e74c3c", "#f1c40f", "#2ecc71"] : ["#e74c3c", "#2ecc71", "#3498db"]
                delegate: Text {
                    required property int index
                    required property string modelData
                    text: "— " + ["X", "Y", "Z"][index]; color: modelData; font.pixelSize: 10
                }
            }
        }
        Caption { text: trace.yMinimum.toFixed(2) + " … " + trace.yMaximum.toFixed(2); font.pixelSize: 10 }
        Trace {
            id: trace
            objectName: (plot.channel === 0 ? "acc-" : "gyr-") + plot.address
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 70
            address: plot.address; channel: plot.channel; running: plot.drawing; sdkStyle: true; autoRange: plot.automaticRange
        }
        Caption { text: "最近 3 s · 200 Hz · 原始轴"; font.pixelSize: 10 }
    }
}
