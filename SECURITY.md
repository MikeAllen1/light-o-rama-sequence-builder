# Security Policy

## Project status and supported versions

Light-O-Rama Sequence Builder is an early-stage project. There are no stable releases or production-supported versions yet. The default branch is the development version.

## Reporting a vulnerability

Please do not report exploitable vulnerabilities, leaked credentials, or private data in a public issue.

For a public repository, use GitHub's **Report a vulnerability** / private vulnerability reporting feature on the repository's Security tab when it is available. If private reporting is not enabled, contact the repository maintainer privately through GitHub before sharing technical details publicly. Include the affected commit or file, impact, and steps to reproduce where safe.

Do not include real credentials, copyrighted media, private display previews, or unredacted sequence files in a report.

## Security expectations

- Never commit passwords, API keys, access tokens, private keys, certificates, or real `.env` files.
- Use environment variables or a local, untracked configuration file for future credentials. Do not add secrets to example configuration files.
- Treat audio, sequence, and preview files as user data. They may contain copyrighted media references, local file paths, GUIDs, names, and display details.
- Keep test fixtures fictional and synthetic, either hand-authored or generated at test time. Do not commit original or sanitized user show files, and do not upload a user's show files to issues or pull requests.
- Parse imported XML as untrusted input. Avoid executing content from sequence files, resolving external entities, or trusting embedded paths.
- Keep dependencies current and review Dependabot and code-scanning alerts.
- Use least-privilege GitHub Actions permissions. Workflows should not receive write permissions unless a specific job requires them.

## Current data handling

The current command-line tools read audio and sequence files from local paths and write analysis or display summaries to local output files. The project does not currently implement cloud upload, remote media processing, or a credential-based integration with Light-O-Rama. Reassess this section if those capabilities are introduced.

## Disclosure

Please allow the maintainer a reasonable opportunity to investigate and fix a report before public disclosure.
