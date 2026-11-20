import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Ring 1.0

Panel {
    property var snapshot

                Layout.preferredWidth: 265; Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 18; spacing: 16
                    RowLayout { Layout.fillWidth: true
                        Heading { text: "设备" }
                        Item { Layout.fillWidth: true }
                        Caption { text: snapshot.devices.length.toString() }
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: "#edf0f5" }
                    ListView {
                        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 10; clip: true
                        model: studio.devices
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Rectangle {
                            required property var device
                            property var modelData: device
                            objectName: "device-" + modelData.address
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: modelData.name + " " + modelData.state
                            Keys.onReturnPressed: studio.select(modelData.address)
                            Keys.onSpacePressed: studio.select(modelData.address)
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            width: ListView.view.width; height: (modelData.driver === "r1" ? 185 : 141) + (modelData.connected && !modelData.simulated ? 23 : 0); radius: 11
                            color: studio.selected === modelData.address ? "#f8f7fe" : "#fcfcfd"
                            border.color: studio.selected === modelData.address ? "#c9c1ef" : "#eceef3"
                            TapHandler { onTapped: studio.select(modelData.address) }
                            ColumnLayout { anchors.fill: parent; anchors.margins: 13; spacing: 8
                                RowLayout { Layout.fillWidth: true
                                    Rectangle { width: 28; height: 28; radius: 14; color: "transparent"; border.color: modelData.connected ? "#8f82d9" : "#bbc1ce"; border.width: 5 }
                                    Column { Layout.leftMargin: 6; Layout.fillWidth: true; spacing: 3
                                        Text { width: parent.width; text: modelData.name; color: Theme.ink; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight }
                                        Caption { text: modelData.state; font.pixelSize: 10; color: modelData.connected ? "#33a58c" : "#969daf" }
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                                Caption { text: modelData.simulated ? "模拟设备" : modelData.address; elide: Text.ElideMiddle; Layout.fillWidth: true; font.pixelSize: 9 }
                                Caption {
                                    visible: modelData.connected && !modelData.simulated
                                    text: "固件版本：" + (modelData.firmwareVersion || "未获取")
                                    Layout.fillWidth: true; font.pixelSize: 10
                                    elide: Text.ElideRight
                                    Accessible.name: text
                                    HoverHandler { id: firmwareHover }
                                    ToolTip.visible: firmwareHover.hovered
                                    ToolTip.text: text
                                }
                                SelectField {
                                    visible: modelData.driver === "r1"
                                    Layout.fillWidth: true
                                    model: ["200 Hz 六轴", "ULP 100 Hz 加速度"]
                                    currentIndex: modelData.imuMode === "ulp100" ? 1 : 0
                                    enabled: !modelData.connected && !modelData.busy && modelData.state !== "重连中" && !snapshot.syncing
                                    Accessible.name: "R1 采集模式"
                                    onActivated: studio.setR1Mode(modelData.address, currentIndex === 1 ? "ulp100" : "six_axis")
                                }
                                RowLayout { Layout.fillWidth: true
                                    Caption { text: modelData.battery < 0 ? "电量 --" : "电量 "+modelData.battery+"%"; font.pixelSize: 11 }
                                    Item { Layout.fillWidth: true }
                                    ActionButton { text: modelData.simulated ? "模拟设备" : modelData.busy ? "请稍候" : modelData.connected || modelData.state === "重连中" ? "断开" : "连接"; implicitWidth: 64; implicitHeight: 29; enabled: !modelData.simulated && !modelData.busy && !snapshot.syncing; onClicked: studio.connectDevice(modelData.address) }
                                }
                            }
                        }
                        Column { anchors.centerIn: parent; visible: snapshot.devices.length === 0; spacing: 12
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: "◎"; color: "#b9b0df"; font.pixelSize: 46 }
                            Caption { text: "还没有发现戒指"; anchors.horizontalCenter: parent.horizontalCenter }
                            Caption { text: "扫描并连接附近的戒指"; font.pixelSize: 10 }
                        }
                    }
                    Caption { text: "选择设备定位波形"; font.pixelSize: 10 }
                }
            }
