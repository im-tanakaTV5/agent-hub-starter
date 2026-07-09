#!/usr/bin/env python3
"""
ダッシュボードの自動起動を設定するクロスプラットフォーム・インストーラー。
使い方: python3 dashboard/install_dashboard.py  （Windowsでは python でも可）

- macOS   : launchd に登録（ログイン時起動・クラッシュ時自動再起動）
- Windows : スタートアップフォルダにショートカット用バッチを配置（管理者権限不要）
- Linux   : 自動起動は未対応。手動起動のコマンドを案内する
"""
import getpass
import platform
import subprocess
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
DASHBOARD = HUB / 'dashboard'
PYTHON = sys.executable


def install_macos():
    label = f"com.{getpass.getuser()}.agent-hub.dashboard"
    plist_dir = Path.home() / 'Library' / 'LaunchAgents'
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / f"{label}.plist"

    template = (DASHBOARD / 'launchd.plist.template').read_text(encoding='utf-8')
    content = (template
               .replace('{{HUB_PATH}}', str(HUB))
               .replace('{{USER_NAME}}', getpass.getuser())
               .replace('{{PYTHON_PATH}}', PYTHON))

    (DASHBOARD / 'logs').mkdir(parents=True, exist_ok=True)
    plist_path.write_text(content, encoding='utf-8')

    subprocess.run(['launchctl', 'unload', str(plist_path)], capture_output=True)
    subprocess.run(['launchctl', 'load', str(plist_path)], check=True)

    print(f"✅ ダッシュボードを自動起動に登録しました（launchd）: {label}")
    print("   ブラウザで http://localhost:8765 を開いてください。")
    print(f"   解除したいとき: launchctl unload \"{plist_path}\" && rm \"{plist_path}\"")


def install_windows():
    startup_dir = Path.home() / 'AppData' / 'Roaming' / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'
    startup_dir.mkdir(parents=True, exist_ok=True)
    bat_path = startup_dir / 'agent-hub-dashboard.bat'

    # pythonw があればコンソール窓を出さずに起動できる（なければ通常の python で代用）
    pythonw = Path(PYTHON).with_name('pythonw.exe')
    runner = str(pythonw) if pythonw.exists() else PYTHON

    (DASHBOARD / 'logs').mkdir(parents=True, exist_ok=True)
    server_py = DASHBOARD / 'server.py'
    log_out = DASHBOARD / 'logs' / 'server.out.log'

    bat_content = (
        '@echo off\r\n'
        f'start "" /min "{runner}" "{server_py}" >> "{log_out}" 2>&1\r\n'
    )
    bat_path.write_text(bat_content, encoding='utf-8')

    print(f"✅ ダッシュボードをスタートアップに登録しました: {bat_path}")
    print("   次回ログイン時から自動起動します。今すぐ試したい場合は下記を実行してください。")
    print(f'   "{runner}" "{server_py}"')
    print("   ブラウザで http://localhost:8765 を開いてください。")
    print(f"   解除したいとき: 「{bat_path}」を削除してください。")


def install_linux():
    print("Linuxの自動起動（systemd --user）は未対応です。手動で起動してください：")
    print(f'   "{PYTHON}" "{DASHBOARD / "server.py"}"')
    print("   ブラウザで http://localhost:8765 を開いてください。")
    print("   常時起動したい場合は、上記コマンドをsystemdのuserサービスやcronの@rebootに登録してください。")


def main():
    system = platform.system()
    if system == 'Darwin':
        install_macos()
    elif system == 'Windows':
        install_windows()
    else:
        install_linux()


if __name__ == '__main__':
    main()
