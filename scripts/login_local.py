#!/usr/bin/env python3
"""Interactive authentication. Never supply credentials as command-line arguments."""

import argparse
from getpass import getpass
from pathlib import Path

from readcube_client.auth import LoginFailure, password_login, validate_saved_session
from readcube_client.errors import AuthenticationError

SESSION = Path.home() / ".config/readcube-client/session.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Validate the saved session without login"
    )
    parser.add_argument("--session-file", type=Path, default=SESSION)
    args = parser.parse_args()
    session_file = args.session_file.expanduser()
    try:
        if args.check:
            result = validate_saved_session(session_file)
            print(f"会话验证通过；可访问 {result['collection_count']} 个 Collection。")
            if result["session_changed"]:
                print("服务端已更新 Cookie；旧的会话绑定接口验证状态需要重新验证。")
            return 0
        print("ReadCube 本地登录：密码不显示、不记录；只读验证成功后才更新本机 0600 会话文件。")
        email = input("ReadCube 邮箱: ").strip()
        password = getpass("ReadCube 密码: ")
        try:
            result = password_login(email, password, session_file)
        finally:
            del password
        print(f"登录及只读验证通过；可访问 {result['collection_count']} 个 Collection。")
        print(f"会话已保存到 {session_file}。")
        return 0
    except LoginFailure as exc:
        print(f"认证未完成 [{exc.code}]：{exc}。原有会话文件未被失败请求覆盖。")
        if exc.code in ("interactive_auth_required", "access_rejected"):
            print("如账户要求 SSO/MFA，请使用正常浏览器登录；本助手不实现或绕过这些步骤。")
        return 1
    except (AuthenticationError, ValueError) as exc:
        print(f"认证未完成：{exc}")
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n登录已取消，未保存新会话。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
