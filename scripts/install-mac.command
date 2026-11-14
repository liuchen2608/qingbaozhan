#!/bin/sh
# Standalone installer: does not require Git or a local checkout.
set -eu
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' '未找到 Python 3。请先从 https://www.python.org/downloads/ 安装 Python 3.10 或更高版本。'
  exit 1
fi
exec python3 - <<'PY'
import json
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

# This exact reviewed application version is retained on GitHub.
REVISION = 'e8203ed13218d60b9310368822c2b6e21f170ff3'
ARCHIVE = f'https://codeload.github.com/liuchen2608/qingbaozhan/zip/{REVISION}'
TARGET = Path.home() / 'Desktop' / '情报站'

def main():
    if sys.platform != 'darwin':
        raise RuntimeError('此脚本仅用于你的 Mac。云端运行不能将文件安装到你的桌面。')
    if sys.version_info < (3, 10):
        raise RuntimeError('需要 Python 3.10 或更高版本。请先安装新版 Python。')
    if TARGET.exists() or TARGET.is_symlink():
        raise RuntimeError(f'目标目录已存在：{TARGET}\n为保护已有文件，本次没有覆盖或删除任何内容。请将该目录的文件列表截图发给助手检查。')
    if not TARGET.parent.is_dir():
        raise RuntimeError('找不到桌面目录，请确认终端具备访问桌面的权限。')
    print('正在从 GitHub 下载情报站源码……', flush=True)
    # Download and check in staging before exclusively creating the destination.
    with tempfile.TemporaryDirectory(prefix='.qingbaozhan-install-', dir=TARGET.parent) as temp:
        root = Path(temp)
        archive = root / 'project.zip'
        request = urllib.request.Request(ARCHIVE, headers={'User-Agent': 'Intelligence-Hub-Installer'})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
        extract = root / 'source'
        with zipfile.ZipFile(archive) as book:
            if sum(i.file_size for i in book.infolist()) > 30_000_000:
                raise RuntimeError('下载包大小异常，已停止安装。')
            for info in book.infolist():
                resolved = (extract / info.filename).resolve()
                if not resolved.is_relative_to(extract.resolve()) or stat.S_ISLNK(info.external_attr >> 16):
                    raise RuntimeError('压缩包路径异常，已停止安装。')
            book.extractall(extract)
        source = extract / f'qingbaozhan-{REVISION}'
        if not all((source / n).is_file() for n in ['run.py', 'setup.sh', 'requirements.txt', 'hub/app.py']):
            raise RuntimeError('下载包不是预期的情报站项目，未写入目标目录。')
        # Create destination exclusively; never merge with an existing user's directory.
        TARGET.mkdir()
        for entry in source.iterdir():
            shutil.move(str(entry), str(TARGET / entry.name))
    for name in ['setup.sh', '启动情报站.command']:
        (TARGET / name).chmod(0o755)
    print(f'源码已保存到：{TARGET}\n正在安装运行依赖……', flush=True)
    subprocess.run(['sh', 'setup.sh'], cwd=TARGET, check=True)
    print('安装完成，正在检查启动端口……', flush=True)
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', 8765)) == 0:
            raise RuntimeError('8765端口已被占用。本次没有启动新的服务，请将终端结果发给助手检查。')
    process = subprocess.Popen([str(TARGET / '.venv/bin/python'), 'run.py'], cwd=TARGET)
    try:
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError('情报站启动失败，请保留上面的错误信息。')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8765/api/status', timeout=1) as response:
                    status = json.load(response)
                if 'model_configured' in status and 'categories' in status:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError('30秒内未检测到服务就绪，请检查上面的启动日志。')
        print('\n服务已响应，正在请求打开浏览器。请保持此终端开启；按 Ctrl+C 停止。', flush=True)
        if not webbrowser.open('http://127.0.0.1:8765'):
            print('浏览器未自动打开。服务已就绪，可手动打开 http://127.0.0.1:8765。', flush=True)
        process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

try:
    main()
except KeyboardInterrupt:
    print('\n情报站已停止。下次可使用桌面文件夹中的“启动情报站.command”。')
except Exception as exc:
    print(f'\n安装或启动未完成：{exc}\n请把此终端结果截图发给助手。不要反复覆盖已有目录。', file=sys.stderr)
    sys.exit(1)
PY
