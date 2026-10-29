"""Local macOS login dialogs. Credentials never enter the MCP protocol or argv."""

import argparse
import subprocess
from pathlib import Path

from readcube_client import Settings
from readcube_client.auth import LoginFailure, password_login
from readcube_client.errors import AuthenticationError

_EMAIL = (
    'activate\ntext returned of (display dialog "请输入 ReadCube 邮箱：" '
    'default answer "" buttons {"取消", "继续"} default button "继续" '
    'with title "ReadCube 本地登录")'
)
_PASSWORD = (
    'activate\ntext returned of (display dialog "请输入 ReadCube 密码：" '
    'default answer "" with hidden answer buttons {"取消", "登录"} '
    'default button "登录" with title "ReadCube 本地登录")'
)
_SUCCESS = (
    'activate\ndisplay dialog "登录及连接验证成功。新会话的接口验证状态可能需要重新检查。" '
    'buttons {"好"} default button "好" with title "ReadCube 本地登录"'
)
_FAILED = (
    'activate\ndisplay dialog "登录未完成。请检查网络及账号，或使用原有终端登录方式。'
    'SSO 和多因素验证暂不支持。原有会话未被此次失败覆盖。" '
    'buttons {"好"} default button "好" with title "ReadCube 本地登录"'
)


def _dialog(script: str) -> str | None:
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.rstrip("\r\n") if result.returncode == 0 else None


def run_login(config: str | None = None) -> bool:
    email = _dialog(_EMAIL)
    if not email:
        return False
    password = _dialog(_PASSWORD)
    if not password:
        return False
    try:
        settings = Settings.from_toml(Path(config)) if config else Settings()
        password_login(
            email,
            password,
            settings.session_file,
            client_version=settings.client_version,
            timeout=settings.timeout,
        )
    except (LoginFailure, AuthenticationError, ValueError, OSError):
        _dialog(_FAILED)
        return False
    finally:
        del password
        del email
    _dialog(_SUCCESS)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    args = parser.parse_args()
    run_login(args.config)


if __name__ == "__main__":
    main()
