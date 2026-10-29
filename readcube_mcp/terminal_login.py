"""Open a local terminal for password login without putting secrets in MCP messages."""

import argparse
import getpass
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from readcube_client import Settings
from readcube_client.auth import LoginFailure, password_login
from readcube_client.errors import AuthenticationError


def open_terminal(command: list[str]) -> None:
    """Open a private one-use macOS Terminal launcher containing no credentials."""
    folder = Path(tempfile.mkdtemp(prefix="readcube-login-"))
    launcher = folder / "ReadCube Login.command"
    script = (
        "#!/bin/sh\n"
        f"cd {shlex.quote(os.getcwd())} || exit 1\n"
        'rm -f -- "$0"\n'
        f"rmdir -- {shlex.quote(str(folder))} 2>/dev/null || :\n"
        "exec " + shlex.join(command) + "\n"
    )
    try:
        launcher.write_text(script, encoding="utf-8")
        launcher.chmod(0o700)
        subprocess.run(
            ["/usr/bin/open", "-a", "Terminal", str(launcher)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        launcher.unlink(missing_ok=True)
        folder.rmdir()
        raise OSError("Unable to open Terminal") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        settings = Settings.from_toml(args.config) if args.config else Settings()
        print("ReadCube 登录：密码不会显示或写入聊天；验证成功后才保存会话。")
        email = input("ReadCube 邮箱: ").strip()
        password = getpass.getpass("ReadCube 密码: ")
        try:
            result = password_login(
                email,
                password,
                settings.session_file,
                client_version=settings.client_version,
                timeout=settings.timeout,
            )
        finally:
            del password
            del email
        print(f"登录及连接验证成功；可访问 {result['collection_count']} 个 Collection。")
        print("新会话可能需要重新进行接口验证。")
        return 0
    except (LoginFailure, AuthenticationError, ValueError, OSError):
        print("登录未完成；请检查账号或网络。SSO/MFA 暂不支持。原有会话未被失败请求覆盖。")
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n登录已取消；原有会话未更改。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
