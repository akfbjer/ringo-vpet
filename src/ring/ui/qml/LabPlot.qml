import QtQuick
import QtQuick.Layouts

Panel {
    id: plot
    property string title
    property var series: []
    property var names: []
    property var seriesColors: ["#7465df", "#27a99c", "#dd9560"]
    property bool fixedRange: false
    property real rangeMinimum: 0
    property real rangeMaximum: 1
    Layout.fillWidth: true
    implicitHeight: 155
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 12
        Caption { text: plot.title; Layout.fillWidth: true }
        Canvas {
            id: canvas
            Layout.fillWidth: true; Layout.fillHeight: true
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onPaint: {
                var ctx = getContext("2d"); ctx.reset()
                var colors = plot.seriesColors
                var low = Infinity, high = -Infinity
                for (var s of plot.series) for (var v of s) { low = Math.min(low, v); high = Math.max(high, v) }
                if (!isFinite(low)) { ctx.fillStyle = "#8991a2"; ctx.fillText("等待数据", 8, 30); return }
                if (plot.fixedRange) { low = plot.rangeMinimum; high = plot.rangeMaximum }
                var span = Math.max(high-low, 0.0001)
                ctx.strokeStyle = "#e5e8ef"; ctx.beginPath(); ctx.moveTo(0, height/2); ctx.lineTo(width, height/2); ctx.stroke()
                for (var j=0; j<plot.series.length; j++) {
                    var values = plot.series[j]; ctx.strokeStyle = colors[j%colors.length]; ctx.lineWidth = 1.5; ctx.beginPath()
                    for (var i=0; i<values.length; i++) {
                        var x = i * width / Math.max(1, values.length-1), y = height-16-(values[i]-low)/span*(height-32)
                        if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y)
                    }
                    ctx.stroke(); ctx.fillStyle = colors[j%colors.length]; ctx.fillText(plot.names[j] || "", 8+j*80, 12)
                }
                ctx.fillStyle = "#8991a2"; ctx.fillText(low.toFixed(2)+" … "+high.toFixed(2), 8, height-1)
            }
        }
    }
    onSeriesChanged: canvas.requestPaint()
}
