import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    property var snapshot
    property var lab: snapshot && snapshot.ringoLab ? snapshot.ringoLab : ({devices: [], recording: false, path: "", error: "", count: 0})
    objectName: "ringoLabPage"
    property string address: ""
    onLabChanged: {
        if (!lab.devices.some(d => d.address === address))
            address = lab.devices.length ? lab.devices[0].address : ""
    }
    property var device: {
        for (var d of lab.devices) if (d.address === address) return d
        return null
    }
    property var plots: device ? device.plots : ({})
    spacing: 12
    RowLayout {
        Layout.fillWidth: true
        SelectField {
            objectName: "ringoLabDeviceSelector"
            Layout.preferredWidth: 240
            model: page.lab.devices; textRole: "name"
            currentIndex: page.lab.devices.findIndex(d => d.address === page.address)
            enabled: count > 0
            displayText: count ? currentText : "暂无已连接的 Ringo"
            onActivated: page.address = page.lab.devices[currentIndex].address
        }
        Item { Layout.fillWidth: true }
        ActionButton { text: page.lab.recording ? "停止全量录制" : "全量录制"; primary: true; enabled: page.lab.recording || page.lab.devices.some(d => d.connected); onClicked: studio.ringoControl("", "record") }
        ActionButton { text: "打开目录"; onClicked: studio.openRecordings() }
    }
    Caption { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "IMU 和音频可分别录制；全量录制保留所有已连接 Ringo 的原始数据。" }
    Caption { Layout.fillWidth: true; wrapMode: Text.Wrap; visible: text.length > 0; text: page.lab.error || (page.lab.recording ? "录制中 · " + page.lab.count + " 条 · " : "") + page.lab.path; color: page.lab.error ? "#ce5765" : Theme.muted }
    RowLayout {
        Layout.fillWidth: true
        ActionButton {
            objectName: "imuRecordStartButton"; text: "开始录制 IMU"; primary: true
            enabled: !!page.device && !page.device.busy && !page.device.imuRecording && !page.device.imuSaving
            onClicked: studio.ringoControl(page.address, "imu_record_start")
        }
        ActionButton {
            objectName: "imuRecordStopButton"; text: "结束录制 IMU"
            enabled: !!page.device && !page.device.busy && page.device.imuRecording
            onClicked: studio.ringoControl(page.address, "imu_record_stop")
        }
        Caption {
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: page.device && page.device.imuSaving ? "正在保存…"
                  : page.device && page.device.imuRecording ? "IMU 录制中 · " + page.device.imuCount + " 帧"
                  : "当前戒指 · 六轴与时间戳 · HDF5"
        }
    }
    Caption {
        Layout.fillWidth: true; wrapMode: Text.Wrap; visible: text.length > 0
        text: page.device && page.device.imuRecording ? (page.device.imuError || page.device.imuPath)
              : page.lab.lastIMU && page.lab.lastIMU.path ? (page.lab.lastIMU.error || "已保存 · " + page.lab.lastIMU.count + " 帧") + " · " + page.lab.lastIMU.path : ""
    }
    RowLayout {
        Layout.fillWidth: true
        ActionButton {
            objectName: "audioStartButton"; text: "开始录音"; primary: true
            enabled: !!page.device && !page.device.busy && !page.device.audioRecording && !page.device.audioSaving
            onClicked: studio.ringoControl(page.address, "audio_start")
        }
        ActionButton {
            objectName: "audioStopButton"; text: "结束录音"
            enabled: !!page.device && !page.device.busy && page.device.audioRecording
            onClicked: studio.ringoControl(page.address, "audio_stop")
        }
        Caption {
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: page.device && (page.device.audioRecording || page.device.audioSaving)
                  ? (page.device.audioSaving ? "正在保存…" : "录音中 · " + Number(page.device.audioSeconds).toFixed(1) + " s · WAV / 16 kHz / 单声道")
                  : "录制所选戒指的实时音频，结束后保存为 WAV"
        }
    }
    Caption {
        Layout.fillWidth: true; wrapMode: Text.Wrap; visible: text.length > 0
        text: page.device && page.device.audioRecording ? (page.device.audioError ? page.device.audioError + " · " : "") + page.device.audioPath
              : page.lab.lastAudio && page.lab.lastAudio.path
                ? (page.lab.lastAudio.error || "已保存 · " + Number(page.lab.lastAudio.seconds).toFixed(1) + " s") + " · " + page.lab.lastAudio.path : ""
    }
    ScrollView {
        objectName: "ringoLabScroll"
        Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
        ColumnLayout {
            width: parent.width; spacing: 12
            Caption { visible: !page.device; text: "请先在主页「设备」连接 Ringo，再到实验室选择已连接的戒指" }
            Flow {
                Layout.fillWidth: true; spacing: 8
                Repeater {
                    model: [{t:"LED 开",a:"led_on"},{t:"LED 关",a:"led_off"},{t:"IMU 开",a:"imu"},{t:"IMU 停",a:"imu_stop"},{t:"PPG 绿光",a:"ppg_green"},{t:"PPG 红光",a:"ppg_red"},{t:"PPG 红外",a:"ppg_ir"},{t:"PPG 停",a:"ppg_stop"},{t:"麦克风开",a:"mic"},{t:"麦克风停",a:"mic_stop"}]
                    delegate: ActionButton {
                        required property var modelData
                        text: modelData.t; enabled: !!page.device && page.device.connected && !page.device.busy
                        onClicked: studio.ringoControl(page.device.address, modelData.a)
                    }
                }
            }
            Caption { Layout.fillWidth: true; wrapMode: Text.Wrap; text: page.device ? page.device.request : "" }
            Caption { Layout.fillWidth: true; wrapMode: Text.Wrap; text: page.device ? (page.device.connected ? "已连接" : "已断开") + " · 数据异常 " + page.device.gaps + " · 无效包 " + (page.device.counts.invalid || 0) : "" }
            GridLayout {
                columns: width > 740 ? 2 : 1
                Layout.fillWidth: true
                RingoImuPlot { address: page.address; channel: 0 }
                RingoImuPlot { address: page.address; channel: 3 }
                LabPlot { title: "PPG 绿光 · 原始 ADC"; names: ["绿光"]; seriesColors: ["#27a99c"]; series: [page.plots.green || []] }
                LabPlot { title: "PPG 红光 · 原始 ADC"; names: ["红光"]; seriesColors: ["#ce5765"]; series: [page.plots.red || []] }
                LabPlot { title: "PPG 红外 · 原始 ADC"; names: ["红外"]; seriesColors: ["#7465df"]; series: [page.plots.ir || []] }
                LabPlot { fixedRange: true; rangeMinimum: 0; rangeMaximum: 1; title: "麦克风 · PCM 峰值包络 · 0–1"; names: ["5 ms peak"]; series: [page.plots.pcm || []] }
                LabPlot { title: "麦克风 · " + (page.device && page.device.audioEncoding ? page.device.audioEncoding.toUpperCase() : "等待编码") + " 分片字节数"; names: ["bytes"]; series: [page.plots.audio_bytes || []] }
            }
            Caption { Layout.fillWidth: true; wrapMode: Text.Wrap; text: page.device ? page.device.audioError : "" }
            Caption { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "PPG 按固件模式切换；红光采集会同时启用红外。" }
            Heading { text: "按钮事件"; font.pixelSize: 16 }
            Panel {
                Layout.fillWidth: true; Layout.preferredHeight: 150
                ListView {
                    id: buttonEvents
                    objectName: "ringoButtonEvents"
                    anchors.fill: parent; anchors.margins: 12; clip: true; spacing: 4
                    boundsBehavior: Flickable.StopAtBounds
                    model: page.device ? page.device.buttons : []
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AlwaysOn }
                    delegate: Caption {
                        required property var modelData
                        width: buttonEvents.width - 18; height: 25
                        text: modelData.label + "   ·   #" + modelData.seq + "   ·   " + modelData.uptime_ms + " ms"
                    }
                    Caption { anchors.centerIn: parent; visible: buttonEvents.count === 0; text: "暂无按钮事件" }
                }
            }
        }
    }
}
