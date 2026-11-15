# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir spec for TeacherJournal (windowed). Build via packaging/build.ps1.
from pathlib import Path

ROOT = Path(SPECPATH).parent

# Qt modules the app does not use (it needs only Core/Gui/Widgets/Svg).
EXCLUDE_QT = [
    "PySide6." + name
    for name in (
        "QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel", "QtWebSockets",
        "QtPdf", "QtPdfWidgets", "QtMultimedia", "QtMultimediaWidgets", "QtSpatialAudio",
        "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic", "Qt3DAnimation", "Qt3DExtras",
        "QtQml", "QtQuick", "QtQuickWidgets", "QtQuick3D", "QtQuickControls2", "QtQuickTest",
        "QtCharts", "QtDataVisualization", "QtGraphs", "QtGraphsWidgets", "QtBluetooth", "QtNfc",
        "QtPositioning", "QtLocation", "QtSensors", "QtSerialPort", "QtSerialBus", "QtRemoteObjects",
        "QtScxml", "QtStateMachine", "QtTextToSpeech", "QtHttpServer", "QtNetworkAuth",
        "QtDesigner", "QtHelp", "QtTest", "QtSql", "QtNetwork", "QtDBus", "QtOpenGL",
        "QtOpenGLWidgets", "QtPrintSupport", "QtXml", "QtConcurrent", "QtLottie", "QtVirtualKeyboard",
    )
] + ["tkinter", "pytest", "pytest_qt", "unittest.mock"]

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "alembic.ini"), "."),
        (str(ROOT / "packaging" / "icon.ico"), "."),
        (str(ROOT / "migrations"), "migrations"),
    ],
    hiddenimports=[
        "alembic.ddl.postgresql",
        "psycopg",
        "psycopg_binary",
        "sqlalchemy.dialects.postgresql.psycopg",
        "journal.models",
        "logging.config",
        "logging.handlers",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDE_QT,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TeacherJournal",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "packaging" / "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TeacherJournal")
