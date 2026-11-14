#!/usr/bin/env python3
"""
日次報告（Claude manager）を毎朝自動で走らせる設定をするインストーラー。
使い方: python3 scripts/install_daily_report.py            （Windowsでは python でも可）
        python3 scripts/install_daily_report.py --uninstall

時刻は hub.config.json の daily_report.time（"07:00" の形。無ければ 07:00）。

- macOS   : launchd に登録（その時刻に寝ていたら、起きたあとに走る）
- Windows : タスクスケジューラに登録（管理者権限不要。その時刻に電源が入っていないと走らない）
- Linux   : 自動起動は未対応。cron に書く1行を案内する
"""
import getpass
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
SCRIPT = HUB / 'scripts' / 'claude_manager.py'
LOG = HUB / 'dashboard' / 'logs' / 'claude-manager.log'
PYTHON = sys.executable
TASK_NAME = 'agent-hub-daily-report'


def report_time():
    try:
        raw = json.loads((HUB / 'hub.config.json').read_text(encoding='utf-8'))['daily_report']['time']
        m = re.fullmatch(r'(\d{1,2}):(\d{2})', str(raw).strip())
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour < 24 and minute < 60:
            return hour, minute
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return 7, 0


def plist_path():
    label = f"com.{getpass.getuser()}.agent-hub.daily-report"
    return label, Path.home() / 'Library' / 'LaunchAgents' / f"{label}.plist"


def install_macos(hour, minute):
    label, path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # launchd は PATH が最小なので、claude と python の置き場所を足しておく
    dirs = [str(Path.home() / '.local' / 'bin'), str(Path(PYTHON).parent),
            '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin']
    content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{PYTHON}</string>
    <string>{SCRIPT}</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key><string>{HUB}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>{':'.join(dict.fromkeys(dirs))}</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>{minute}</integer></dict>
  <key>StandardOutPath</key><string>{LOG}</string>
  <key>StandardErrorPath</key><string>{LOG}</string>
</dict>
</plist>
'''
    path.write_text(content, encoding='utf-8')
    subprocess.run(['launchctl', 'unload', str(path)], capture_output=True)
    subprocess.run(['launchctl', 'load', str(path)], check=True)
    print(f"✅ 日次報告を毎朝 {hour}:{minute:02d} に登録しました（launchd）: {label}")
    print(f"   ログ: {LOG}")


def uninstall_macos():
    _, path = plist_path()
    subprocess.run(['launchctl', 'unload', str(path)], capture_output=True)
    path.unlink(missing_ok=True)
    print("✅ 日次報告の自動起動を解除しました。")


def install_windows(hour, minute):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    bat = HUB / 'dashboard' / 'logs' / 'run_daily_report.bat'
    bat_content = (
        '@echo off\r\n'
        f'cd /d "{HUB}"\r\n'
        f'"{PYTHON}" "{SCRIPT}" run >> "{LOG}" 2>&1\r\n'
    )
    # cmdはバッチをANSI（日本語環境ではcp932）で解釈する。install_dashboard.py と同じ理由
    try:
        bat.write_text(bat_content, encoding='mbcs')
    except (UnicodeEncodeError, LookupError):
        bat.write_text(bat_content, encoding='utf-8')
    subprocess.run(['schtasks', '/Create', '/F', '/SC', 'DAILY', '/TN', TASK_NAME,
                    '/TR', f'"{bat}"', '/ST', f'{hour:02d}:{minute:02d}'], check=True)
    print(f"✅ 日次報告を毎朝 {hour}:{minute:02d} に登録しました（タスクスケジューラ）: {TASK_NAME}")
    print("   その時刻にPCの電源が入っていない日は走りません。司令塔に「集め直して」と言えば取り直せます。")
    print(f"   ログ: {LOG}")


def uninstall_windows():
    subprocess.run(['schtasks', '/Delete', '/F', '/TN', TASK_NAME], capture_output=True)
    print("✅ 日次報告の自動起動を解除しました。")


def install_linux(hour, minute):
    print("Linuxの自動起動は未対応です。cron に次の1行を足してください（crontab -e）：")
    print(f'   {minute} {hour} * * * cd "{HUB}" && "{PYTHON}" "{SCRIPT}" run >> "{LOG}" 2>&1')


def main():
    system = platform.system()
    if '--uninstall' in sys.argv:
        if system == 'Darwin':
            uninstall_macos()
        elif system == 'Windows':
            uninstall_windows()
        else:
            print("cron に足した行を消してください（crontab -e）。")
        return
    hour, minute = report_time()
    if system == 'Darwin':
        install_macos(hour, minute)
    elif system == 'Windows':
        install_windows(hour, minute)
    else:
        install_linux(hour, minute)


if __name__ == '__main__':
    main()
