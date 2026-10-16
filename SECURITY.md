# Security Policy

## Historical Date Game container distribution

Containers package the existing security model; they do not add authentication,
authorization, TLS, rate limiting, brute-force protection or a reviewed public
reverse-proxy configuration. Account tokens protect account/admin APIs; guest
sessions are game-only identities, not administrators or a public access-control
layer. There is no independent security certification.

The release defaults to loopback-only HTTP and an unpublished PostgreSQL port.
LAN/public exposure needs an explicit binding, exact frontend origin, access
controls and a separate TLS/proxy/security review. Use HTTPS with
`ENVIRONMENT=production` outside local HTTP operation; Secure guest-cookie and
same-origin request checks remain in force. Forwarded headers are not trusted.

The application runs non-root and serving media is read-only. This does not hide
database passwords, application secrets or private backups from the Docker host
administrator. Keep `.env`, PostgreSQL dumps and all retained media private;
back up the permanent `SECRET_KEY` to preserve identities across recovery. The
build context excludes credentials, raw data and private worktrees by default.
Never upload unredacted traces, credentials, session cookies or private reports.
See [INSTALL.md](INSTALL.md) for safe initialization and recovery limitations.

Security is very important for this project and its community. 🔒

Learn more about it below. 👇

## Versions

The latest version or release is supported.

You are encouraged to write tests for your application and update your versions frequently after ensuring that your tests are passing. This way you will benefit from the latest features, bug fixes, and **security fixes**.

## Reporting a Vulnerability

If you think you found a vulnerability, and even if you are not sure about it, please report it right away by sending an email to: security@tiangolo.com. Please try to be as explicit as possible, describing all the steps and example code to reproduce the security issue.

I (the author, [@tiangolo](https://twitter.com/tiangolo)) will review it thoroughly and get back to you.

## Public Discussions

Please restrain from publicly discussing a potential security vulnerability. 🙊

It's better to discuss privately and try to find a solution first, to limit the potential impact as much as possible.

---

Thanks for your help!

The community and I thank you for that. 🙇
