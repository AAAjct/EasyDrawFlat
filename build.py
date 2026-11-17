"""在 Windows 上生成无需 Python 的单文件程序。"""
from pathlib import Path
import subprocess
import sys
import os
import argparse

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description="构建 EasyDrawFlat Windows 程序")
parser.add_argument("--distpath", type=Path, default=ROOT / "dist" / "v2.6", help="程序输出目录")
args = parser.parse_args()
sys.path.insert(0, str(ROOT))
from main import create_app, icon

app = create_app()
icon("app").pixmap(256, 256).save(str(ROOT / "EasyDrawFlat.ico"))
# 只在 Python、Qt 自身和 Windows 中解析依赖，避免 PATH 中其他软件
# 的同名 DLL（例如 Poppler 的 ICU）混入安装包。
env = os.environ.copy()
windows = Path(env.get("SystemRoot", r"C:\Windows"))
env["PATH"] = os.pathsep.join(map(str, [Path(sys.executable).parent,
    Path(sys.executable).parent / "Scripts", windows / "System32", windows]))
subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
    "--distpath", str(args.distpath.resolve()), "--workpath", str(ROOT / "build"),
    str(ROOT / "windows.spec")], cwd=ROOT, env=env, check=True)
