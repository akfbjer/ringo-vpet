import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    objectName: "firmwarePage"
    property var snapshot
    readonly property var f: snapshot && snapshot.firmware ? snapshot.firmware : ({})
    readonly property bool busy: f.busy === true
    property string address: ""
    property string firmwareId: ""
    readonly property var device: snapshot ? snapshot.devices.find(d => d.address === address) : null
    readonly property string family: device ? device.driver : ""
    readonly property var versions: studio.firmwareCatalog.filter(v => v.device === family)
    readonly property var firmware: versions.find(v => v.id === firmwareId)
    readonly property bool canStart: !busy && !!device && device.connected && !device.busy && !!firmware && !f.refreshing
    readonly property var stages: ["检查设备", "上传固件", "重启设备", "验证版本"]
    readonly property int stage: ({idle:0, preflight:0, connecting:0, uploading:1, marking:2, rebooting:2, verifying:3, restoring:3, complete:4})[f.phase] || 0
    onVersionsChanged: {
        if (!versions.some(v => v.id === firmwareId))
            firmwareId = versions.length ? versions[0].id : ""
    }
    Component.onCompleted: studio.refreshFirmware()
    spacing: 18

    RowLayout {
        Layout.fillWidth: true
        Caption { text: "通过蓝牙更新固件 · 一次只更新一枚戒指"; Layout.fillWidth: true }
        ActionButton { text: "固件目录"; onClicked: studio.openFirmwareFolder() }
        ActionButton { text: f.refreshing ? "读取中…" : "刷新版本"; enabled: !page.busy && !f.refreshing; onClicked: studio.refreshFirmware() }
    }
    Panel {
        Layout.fillWidth: true; implicitHeight: 216
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 24; spacing: 16
            Heading { text: "选择更新目标" }
            RowLayout {
                Layout.fillWidth: true; spacing: 24
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 9
                    Caption { text: "戒指" }
                    SelectField {
                        id: deviceSelect
                        objectName: "firmware-device"
                        Layout.fillWidth: true
                        model: studio.firmwareDevices; textRole: "name"; valueRole: "address"
                        enabled: !page.busy && count > 0
                        displayText: page.device ? page.device.name : "选择要更新的戒指"
                        onActivated: page.address = currentValue
                    }
                    Caption {
                        Layout.fillWidth: true; elide: Text.ElideMiddle
                        text: page.device ? page.device.address : "请先在设备页扫描并连接戒指"
                        font.pixelSize: 11
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 9
                    Caption { text: "目标固件版本" }
                    SelectField {
                        objectName: "firmware-version"
                        Layout.fillWidth: true; model: page.versions; textRole: "label"
                        enabled: !page.busy && count > 0
                        currentIndex: page.versions.findIndex(v => v.id === page.firmwareId)
                        displayText: page.firmware ? page.firmware.label : "暂无匹配固件"
                        onActivated: page.firmwareId = page.versions[currentIndex].id
                    }
                    Caption {
                        Layout.fillWidth: true; elide: Text.ElideRight; font.pixelSize: 11
                        text: page.device ? "当前版本 · " + (page.device.firmwareVersion || "连接后读取") : "仅显示适用于所选戒指的固件"
                    }
                }
            }
            Caption {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: !page.device ? "Ringo 与 R1 使用各自的固件，不能交叉烧录。"
                      : !page.versions.length ? "没有适用于此戒指的固件。Ringo 固件不能用于 R1 或 BCL。"
                      : !page.device.connected && !page.busy ? "请先连接所选戒指，再开始烧录。"
                      : "更新前请结束录制与同步；更新期间保持戒指有电、靠近电脑。"
            }
        }
    }
    Panel {
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 290
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 24; spacing: 20
            RowLayout {
                Layout.fillWidth: true
                Heading { text: page.busy ? "正在更新" : page.f.phase === "complete" ? "更新完成" : "固件更新"; font.pixelSize: 20 }
                Item { Layout.fillWidth: true }
                Text { text: page.busy || page.f.phase === "complete" ? Math.round((page.f.progress || 0)*100) + "%" : ""; color: Theme.accent; font.pixelSize: 26; font.weight: Font.DemiBold }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                Repeater {
                    model: page.stages
                    delegate: RowLayout {
                        required property string modelData
                        required property int index
                        Layout.fillWidth: true; spacing: 8
                        Rectangle {
                            width: 24; height: 24; radius: 12
                            color: page.stage >= index && (page.busy || page.f.phase === "complete") ? Theme.accentSoft : Theme.disabledSurface
                            Text { anchors.centerIn: parent; text: String(index + 1); font.pixelSize: 11; color: page.stage >= index && (page.busy || page.f.phase === "complete") ? Theme.accent : Theme.muted }
                        }
                        Caption { text: modelData; color: page.stage === index && page.busy ? Theme.ink : Theme.muted }
                        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border; visible: index < 3 }
                    }
                }
            }
            ProgressBar {
                objectName: "firmware-progress"
                id: progress
                Layout.fillWidth: true; from: 0; to: 1; value: page.f.progress || 0
                background: Rectangle { implicitHeight: 7; radius: 4; color: Theme.accentSoft }
                contentItem: Item { implicitHeight: 7; Rectangle { width: progress.visualPosition * parent.width; height: parent.height; radius: 4; color: Theme.accent } }
            }
            Caption {
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: page.f.message || "准备就绪"
                font.pixelSize: 14; color: Theme.secondary
            }
            Caption {
                visible: page.busy || page.f.phase === "complete"
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: (page.f.deviceName || "") + "  →  " + (page.f.version || "") + (page.f.total ? "  ·  " + Math.round((page.f.sent || 0)/1024) + " / " + Math.round(page.f.total/1024) + " KB" : "")
            }
            Caption { visible: !!page.f.error; text: page.f.error || ""; color: "#bf4b60"; Layout.fillWidth: true; wrapMode: Text.Wrap }
            Caption { visible: !!page.f.warning; text: page.f.warning || ""; color: "#a57536"; Layout.fillWidth: true; wrapMode: Text.Wrap }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                Caption { Layout.fillWidth: true; wrapMode: Text.Wrap; text: page.busy ? "重启与验证阶段请勿断电或退出。" : "烧录前会再次核对设备类型与固件版本。" }
                ActionButton { text: "取消上传"; visible: page.busy; enabled: page.f.cancellable === true; onClicked: studio.cancelFirmware() }
                ActionButton { objectName: "firmware-start"; text: page.busy ? "烧录中…" : "开始烧录"; primary: true; enabled: page.canStart; onClicked: studio.startFirmware(page.address, page.firmwareId) }
            }
        }
    }
}
