# 认证后续研究（2026-10-25）

## 本次结论

新增了可安全调用的密码登录助手、已有会话只读验证、Cookie 本地过期检测与服务端 Cookie 更新后的安全保存。既有 Cookie 会话通过真实 GET `/collections`，返回 8 个 Collection；本次调用 `persist_cookies=False`，未改变当前会话文件或验证 ledger。本轮未重新输入密码、未执行失败登录实验，不能把新增 helper 的完整密码流程标成一次新的实测成功。

## 当前公开来源

- 当前应用 `chunk-QD3Q3KF7.js` 字符偏移 2834740，`getLoginPageUrl()` 生成 `https://www.readcube.com/authentication`，query 使用 client、redirect、theme；桌面 wrapper 还有 api。
- 依据上述明确引用，GET `https://www.readcube.com/authentication?client=webapp&redirect=https%3A%2F%2Fapp.readcube.com%2F&theme=light` 返回 HTTP 200 HTML。保存于被 Git 忽略的 `research/sources/authentication-public.html`，SHA-256 `46159e636c9faa2dcc5d203cc30bef9a53fefc6085f85ba3f11a660af429d51c`。
- HTML 字符偏移 6192 的 form action 为 `https://services.readcube.com/authentication/login`，method POST，data-type=json，data-with-credentials=true。字段名：authenticity_token、client、client_version、api、email、password。动态 CSRF token 不复制到报告或日志。
- 页面明确引用 `/assets/authentication-790e51fa944d7a8f82af85b35eb8c45ec0219208d2586b833e98e31a37544930.js`，已实际 GET HTTP 200；SHA-256 与文件名中的摘要一致。公开源 URL 为 `https://www.readcube.com/assets/authentication-790e51fa944d7a8f82af85b35eb8c45ec0219208d2586b833e98e31a37544930.js`。
- 该 JS 字符偏移 121931 绑定 `.readcube-login-form` 的 ajax:success；130834 的成功处理读取 user/auth_token 并跳转或 postMessage。未提取、返回或持久化响应里的 auth_token。
- JS 字符偏移 120037 将失败响应的 `message` 展示给浏览器用户。SDK 不原样返回这个字段，避免把未审查的响应内容放入代理日志。
- JS 字符偏移 124655 后存在 Google/organization SSO 成功页处理及邮箱验证码界面。未验证此账户的 SSO/MFA，不复用这些路径去绕过正常验证。
- 当前 app JS 的 `/users/info_webapp` GET 位于字符偏移 2341836。本助手沿用已有实测 Collections GET 校验 Cookie；不把用户资料作为成功输出。

## 代码与行为

`readcube_client/auth.py`：

- `load_cookies(path, now=...)` 拒绝符号链接、非普通文件、不安全权限、不明域、异常 Cookie 字段；剔除已过期 Cookie，全部过期时显式报 `session_expired`。
- `save_cookies(cookies, path)` 用同样校验，原子 0600 写入；保留 secure、domain_specified、path、expires、discard。只保存 Cookie 和保存时间，不保存邮箱或密码。
- `session_status(path)` 返回本地可用/expiry 概况，明确 `server_verified=False`；不能由本地存在 Cookie 推断服务端登录仍有效。
- `validate_saved_session(path, persist_cookies=True)` 独立 GET Collections，验证 HTTP 状态和集合数组形状，再保存服务器更新 Cookie；返回的 `cookies_changed` 反映属性变化，`session_changed` 反映会话指纹变化。没有发明 refresh-token 路径；会话撤销/过期需要正常重新登录。
- `password_login(email, password, session_file, ...)` 使用全新的 Cookie jar，单次 form POST → 独立 GET Collections → 原子保存。失败时不会拿旧会话冒充新登录成功，也不会覆盖旧文件。表单维持此前用户已成功使用的 client/client_version/api/email/password 子集；当前页面中的 CSRF 强制分支尚未实测，不声称支持所有认证配置。
- `LoginFailure` 提供 code/status，而不暴露响应体、密码或带 token 的 URL。401 与 403 区分；403 不武断判断为密码错误。429/5xx/网络失败无自动密码重试；SSO/MFA 必须正常完成。

`scripts/login_local.py`：本地 getpass 登录；新增 `--check` 只读核验；失败退出码非零；保留自定义 `--session-file`。不再建议用户在聊天中提供 Cookie。

可由 root 在 client.py 接入本地状态方法或验证方法。`password_login` 是显式认证 helper，不应在未经新登录实测的情况下，把密码、SSO 或 MFA 能力统一标成 VERIFIED，也不应通过 MCP 暴露密码字段。若 SDK 接入登录后新 Cookie，应重建 EvidenceRegistry；旧 session 指纹下验证状态不能迁移给新 session。

## 验证

- 26 项新增认证单元测试与原 client 测试合计 69 passed。覆盖过期、多 Cookie、权限/符号链接、成功后验证再保存、失败保留旧文件、Cookie 不是认证证明、重定向/HTML/业务错误、Cookie 更新、网络错误脱敏及无重试。
- 本次真实只读会话验证通过，未保存响应 Cookie。
- 未执行密码、SSO、验证码、MFA、错误密码、限流或跨账户权限实验；本地 mock 测试不提升实际端点证据级别。
