# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in LovensePy, please report it responsibly.

**Please do not report security vulnerabilities through public GitHub issues, discussions, or pull requests.**

Instead, please report by:

1. **Opening a private security advisory**: Go to the [Security](https://github.com/koval01/lovensepy/security/advisories/new) tab → "Report a vulnerability", or
2. **Contacting the maintainer**: Use the contact information in the repository owner's GitHub profile.

Please include as much of the following as possible:

- Type of issue (e.g., credential exposure, injection, insecure connection)
- Full paths of affected source file(s)
- Location of affected code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce
- Step-by-step instructions to reproduce
- Proof-of-concept or exploit code (if possible)
- Impact and how an attacker might exploit the issue
- Suggested fix (if any)

We will acknowledge your report within a reasonable time and keep you updated. We ask that you allow us time to address the issue before public disclosure. We will credit you in the security advisory unless you prefer to remain anonymous.

## Security Considerations

- **Tokens and credentials**: Never commit developer tokens, UIDs, or other credentials. Use environment variables or secure configuration.
- **HTTPS**: The library uses certificate fingerprint verification for local HTTPS (e.g. port **30011** when `use_https=True`) when `verify_ssl=False`.
- **Network**: LovensePy communicates with Lovense devices and cloud services. Ensure your network setup is appropriate for your use case.

Thank you for helping keep LovensePy and its users safe.
