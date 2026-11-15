# Privacy and safety

- **Your files stay on your computer.** Previews, songs and sequences are read only when you choose them, and never uploaded.
- **Your files are never changed.** Every show, test and edited sequence is written as a new file.
- **What goes online:** when the app starts it asks GitHub's public release list whether a newer version is out; that request carries nothing about you or your files. **Stop checking** in the update note (or `LOR_NO_UPDATE_CHECK=1`) turns it off.
- **Optional extras:** requirements typed in your own words go to Anthropic's API, and only if you set your own `ANTHROPIC_API_KEY`. The vocals and lyrics add-ons download their speech models once.
- **The app's local engine** listens only on your computer (127.0.0.1) and refuses requests from other websites.

Found a security problem? Please report it privately: **Security → Report a vulnerability** on the repository, not in a public issue. See [SECURITY.md](https://github.com/MikeAllen1/light-o-rama-sequence-builder/blob/master/SECURITY.md).
