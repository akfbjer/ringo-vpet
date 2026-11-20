import argparse
from pathlib import Path
import sys
import signal
from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QGuiApplication, QFont
from PyQt6.QtQml import QQmlApplicationEngine, qmlRegisterType
import os
from ring.runtime.engine import Engine
from ring.ui.bridge import Bridge
from ring.ui.trace import Trace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--port", type=int, default=17888)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[2]/"data")
    parser.add_argument("--smoke-seconds", type=float, default=0)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
    os.environ["QSG_RENDER_LOOP"] = "basic"
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("Ring Studio")
    app.setOrganizationName("AI Ring")
    app.setFont(QFont(".AppleSystemUIFont", 13))
    from ring.product import load_product
    runtime = Engine(args.data_dir.resolve(), args.port, product=load_product(args.profile))
    bridge = Bridge(runtime)
    signal.signal(signal.SIGINT, lambda *_: bridge.shutdown())
    Trace.engine = runtime
    qmlRegisterType(Trace, "Ring", 1, 0, "Trace")
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("studio", bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent/"ui"/"qml"/"Main.qml")))
    if not engine.rootObjects():
        runtime.close()
        raise SystemExit("QML failed to load")
    bridge.shutdownFinished.connect(lambda: app.exit(0))
    if args.demo:
        runtime.command("demo")
    if args.screenshot:
        def capture():
            engine.rootObjects()[0].grabWindow().save(str(args.screenshot))
        QTimer.singleShot(2500, capture)
    if args.smoke_seconds:
        QTimer.singleShot(int(args.smoke_seconds*1000), bridge.shutdown)
    result = app.exec()
    if runtime.thread.is_alive() and not runtime.closing:
        runtime.close()
    del engine
    sys.exit(result)


if __name__ == "__main__":
    main()
