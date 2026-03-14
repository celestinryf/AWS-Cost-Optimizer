# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in AWS Cost Optimizer, **please do not open a public issue.**

Instead, report it privately:

1. **Email:** Send details to the repository owner via GitHub's private contact methods
2. **GitHub Security Advisories:** Use the [Security Advisories](https://github.com/celestinryf/AWS-Cost-Optimizer/security/advisories/new) feature to report privately

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

### Response Timeline

- **Acknowledgment:** Within 48 hours
- **Initial assessment:** Within 1 week
- **Fix or mitigation:** Depends on severity, targeting 2 weeks for critical issues

## Security Architecture

### Credential Handling

- AWS credentials are stored in the OS-native keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- Credentials are never written to disk in plaintext
- Credentials are passed to the backend sidecar as environment variables in the subprocess — they do not traverse a network
- The application has no remote server; all processing happens locally

### Network Security

- The backend listens only on `127.0.0.1:8000` (localhost)
- Tauri's Content Security Policy restricts frontend connections to `http://127.0.0.1:8000` and `self`
- No telemetry, analytics, or external API calls (except to AWS S3 and GitHub for updates)

### Execution Safety

- All execution modes default to `dry_run` (no mutations)
- Destructive actions (`DELETE_STALE_OBJECT`) are blocked by default; require explicit `ALLOW_DESTRUCTIVE_EXECUTION=true`
- IAM permissions are validated before every action
- Pre-change state is captured for rollback capability

### Update Verification

- Desktop updates are distributed via GitHub Releases
- Update artifacts are signed with minisign
- The Tauri updater verifies signatures before applying updates

### Docker

- The containerized backend runs as a non-root user (`app:app`)
- No capabilities or privileged mode required

## Scope

The following are **in scope** for security reports:

- Credential exposure (plaintext storage, logging, transmission)
- Bypassing execution guardrails (destructive actions without opt-in)
- CSP bypass or XSS in the Tauri frontend
- Unauthorized S3 operations beyond what the user configured
- Update mechanism tampering

The following are **out of scope**:

- Vulnerabilities in AWS services themselves
- Issues requiring physical access to the user's machine
- Social engineering attacks
- Denial of service against the local backend (it's localhost-only)
