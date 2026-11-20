import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Ring 1.0

ApplicationWindow {
    id: window
    width: 1320; height: 860
    minimumWidth: 1040; minimumHeight: 740
    visible: true
    title: "Ring Studio"
    color: Theme.background
    property int page: 0
    property int requestedPage: 0
    property bool shuttingDown: false
    property bool firmwareCloseBlocked: false
    property var s: studio.state
    onPageChanged: {
        var destination = pageLoaders.itemAt(page)
        if (destination)
            destination.ensureLoaded()
    }
    function navigate(index) {
        requestedPage = index
        var destination = pageLoaders.itemAt(index)
        destination.ensureLoaded()
        // Keep the current page visible while the destination initializes and
        // its layouts settle. Retain visited pages, including their UI state.
        Qt.callLater(function() {
            if (requestedPage === index && destination.status === Loader.Ready)
                page = index
        })
    }
    onClosing: function(close) {
        close.accepted = false
        if (s.firmware && s.firmware.busy) {
            firmwareCloseBlocked = true
            var index = studio.pages.findIndex(p => p.source === "FirmwarePage.qml")
            if (index >= 0) navigate(index)
            return
        }
        shuttingDown = true
        studio.shutdown()
    }
    font.family: Qt.platform.os === "osx" ? "PingFang SC" : "sans-serif"


    Rectangle {
        id: sidebar
        width: 212; anchors.top: parent.top; anchors.bottom: parent.bottom
        color: "#fbfbfe"
        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 22; spacing: 8
            RowLayout {
                Layout.topMargin: 16; Layout.bottomMargin: 26; spacing: 10
                Rectangle {
                    width: 34; height: 34; radius: 11; color: Theme.accent
                    Rectangle { anchors.centerIn: parent; width: 18; height: 18; radius: 9; color: "transparent"; border.color: "white"; border.width: 3 }
                }
                Text { text: "ring studio"; color: "#292d40"; font.pixelSize: 20; font.weight: Font.DemiBold; font.letterSpacing: -0.6 }
            }
            Caption { text: "工作空间"; font.pixelSize: 10; font.letterSpacing: 1.2; Layout.leftMargin: 13; Layout.bottomMargin: 6 }
            Repeater {
                model: studio.pages
                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    objectName: "nav-" + index
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: modelData.name
                    Keys.onReturnPressed: window.navigate(index)
                    Keys.onSpacePressed: window.navigate(index)
                    border.color: activeFocus ? Theme.accent : "transparent"
                    Layout.fillWidth: true; height: 44; radius: 10
                    color: window.page === index ? Theme.accentSoft : nav.hovered ? "#f0f2f7" : "transparent"
                    Row { anchors.verticalCenter: parent.verticalCenter; x: 13; spacing: 12
                        Text { text: modelData.symbol; color: window.page === index ? Theme.accent : "#9198a8"; font.pixelSize: 18; width: 19 }
                        Text { text: modelData.name; color: window.page === index ? Theme.accent : Theme.secondary; font.pixelSize: 13; font.weight: window.page === index ? Font.DemiBold : Font.Normal }
                    }
                    HoverHandler { id: nav; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: window.navigate(index) }
                }
            }
            Item { Layout.fillHeight: true }
            Row { Layout.topMargin: 14; spacing: 7
                Rectangle { width: 6; height: 6; radius: 3; color: s.serverReady ? "#35ad8a" : "#d88b55"; anchors.verticalCenter: parent.verticalCenter }
                Caption { text: s.serverReady ? "已就绪" : "数据服务未就绪"; font.pixelSize: 11 }
            }
        }
    }
    ColumnLayout {
        anchors.left: sidebar.right; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: footer.top
        anchors.margins: 32; spacing: 22
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                spacing: 6
                Text { text: studio.pages[window.page].name; color: Theme.ink; font.pixelSize: 27; font.weight: Font.DemiBold }
                Caption {
                    text: {
                        var descriptions = {"": "连接戒指，查看实时传感器数据", "RecordingPage.qml": "保存每一次采集，随时查看录制文件", "GesturesPage.qml": "查看戒指识别到的手势与事件", "DensityPage.qml": "观察动作概率与实时识别结果", "ClickPage.qml": "用指尖动作控制光标与点击", "HandwritingPage.qml": "让指尖书写转化为文字", "RingoLabPage.qml": "查看与录制多种传感器数据", "SettingsPage.qml": "工作台信息与运行环境"}
                        descriptions["FirmwarePage.qml"] = "选择匹配的固件，更新指定戒指"
                        return descriptions[studio.pages[window.page].source] || ""
                    }
                    font.pixelSize: 12
                }
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                visible: s.demo; width: 78; height: 27; radius: 6; color: "#fff3df"
                Text { anchors.centerIn: parent; text: "模拟数据"; color: "#a87b35"; font.pixelSize: 11 }
            }
            ActionButton { visible: window.page === 0; text: s.scanning ? "扫描中…" : "+  扫描设备"; primary: true; enabled: !s.scanning; onClicked: studio.action("scan") }
        }
        Item {
            id: pageArea
            Layout.fillWidth: true; Layout.fillHeight: true
            Repeater {
                id: pageLoaders
                model: studio.pages
                delegate: Loader {
                    required property var modelData
                    required property int index
                    objectName: "page-loader-" + index
                    anchors.fill: parent
                    visible: window.page === index
                    function ensureLoaded() {
                        if (status !== Loader.Null)
                            return
                        if (index === 0)
                            sourceComponent = devicePage
                        else
                            setSource(modelData.source, {snapshot: Qt.binding(function() { return window.s })})
                    }
                    Component.onCompleted: { if (index === 0) ensureLoaded() }
                }
            }
        }
    }
    Component {
        id: devicePage
        ColumnLayout {
            spacing: 22
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Toggle { objectName: "autoRangeSwitch"; text: "自动轴范围"; checked: studio.autoRange; onToggled: studio.setAutoRange(checked) }
            }
            RowLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; spacing: 20
                DevicePanel { Layout.preferredWidth: 265; Layout.fillHeight: true; snapshot: window.s }
                SignalList { Layout.fillWidth: true; Layout.fillHeight: true; snapshot: window.s }
            }
        }
    }
    Rectangle {
        id: footer
        anchors.left: sidebar.right; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 36; color: "#fcfcfe"
        Rectangle { width: parent.width; height: 1; color: Theme.border }
        RowLayout { anchors.fill: parent; anchors.leftMargin: 32; anchors.rightMargin: 32
            Text { text: window.firmwareCloseBlocked && s.firmware && s.firmware.busy ? "固件更新进行中，请等待完成后再退出" : s.error || s.status; color: s.error ? "#ce5765" : Theme.muted; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
        }
    }
    // Block duplicate input while the existing shutdown completes, without a status overlay.
    MouseArea { anchors.fill: parent; visible: shuttingDown; z: 20 }
}
