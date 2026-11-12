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

## How the local engine is protected

The workspace and the desktop app run a small engine on this computer that the page talks to. It is built so that nothing else can use it:

- It listens only on this computer (127.0.0.1), never on the network.
- It answers only requests addressed to this computer (`127.0.0.1` or `localhost` with its port), which stops DNS rebinding, and refuses any request whose `Origin` or `Sec-Fetch-Site` says it came from another site. Every request that changes anything is a POST with a JSON, audio or XML body that a cross-site form cannot send.
- Each New show has an unguessable session token; tokens never reach the log.
- Pages are served with a strict Content-Security-Policy (no scripts but its own, no framing), `nosniff`, no referrer, and same-origin resource and opener policies. Folders are never listed.
- Uploads are size-capped (previews 20 MB, songs 200 MB, JSON requests small); deeply nested JSON is refused.
- Preview and sequence XML is parsed with defusedxml (no entities, no external references). Songs are decoded by FFmpeg with the container format chosen from the file's own bytes and only local file access allowed, so a song cannot make FFmpeg fetch anything.
- Song names become file names only after removing folder parts, characters Windows forbids and reserved device names.
- Generated reports and plan pictures escape every name, and are shown in a sandboxed frame with scripts off.
- At most two song analyses or show builds run at once; the rest wait their turn.
- The only outside requests are the optional update check (GitHub's public release list) and, when the user sets a key, translating typed requirements.

## Current data handling

The current command-line tools read audio and sequence files from local paths and write analysis or display summaries to local output files. The project does not currently implement cloud upload, remote media processing, or a credential-based integration with Light-O-Rama. Reassess this section if those capabilities are introduced.

## Disclosure

Please allow the maintainer a reasonable opportunity to investigate and fix a report before public disclosure.
