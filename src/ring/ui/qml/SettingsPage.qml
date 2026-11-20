import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Ring 1.0

Panel {
    property var snapshot

            Layout.fillWidth: true; Layout.fillHeight: true
            ColumnLayout { anchors.fill: parent; anchors.margins: 28; spacing: 20
                Heading { text: "运行环境" }
                Repeater { model: [
                    {name:"数据服务", value:"127.0.0.1:"+snapshot.port+"  ·  "+(snapshot.serverReady ? "在线" : "未就绪")},
                    {name:"连接恢复", value:"意外断线自动重连，手动断开后停止"},
                    {name:"当前版本", value:"0.1"}].concat(studio.hasRecording ? [{name:"录制格式", value:"HDF5 · 二进制无损压缩"}] : [])
                    delegate: ColumnLayout { required property var modelData; Layout.fillWidth: true; spacing: 16
                        RowLayout { Layout.fillWidth: true
                            Text { text: modelData.name; color: "#677187"; font.pixelSize: 13; Layout.preferredWidth: 140 }
                            Text { text: modelData.value; color: "#373e53"; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: "#edf0f5" }
                    }
                }
                Item { Layout.fillHeight: true }
            }
        }
