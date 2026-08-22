# Goldhand Clinic Blog Codex plugin

Windows recipients can install this plugin from one file. They do not need Git, a ZIP extractor, or a PowerShell command.

## Windows one-file install

**[Download INSTALL-WINDOWS.cmd](https://github.com/seojun03/goldhand-clinic-blog-windows/releases/latest/download/INSTALL-WINDOWS.cmd)**

1. Download the file from the link above.
2. Close ChatGPT completely.
3. Double-click `INSTALL-WINDOWS.cmd`.
4. Wait for `INSTALLATION COMPLETE`, close the window, and reopen ChatGPT.

The installer does not install, update, remove, or modify the ChatGPT app. It verifies Python, installs Node.js LTS only when a working npm is missing, installs and executes the Vercel CLI, verifies a Codex CLI that supports plugins, downloads the latest validated release to a short path, transactionally replaces `%USERPROFILE%\GoldhandBlog`, and connects it as a local marketplace plugin.

No Vercel password or token is bundled in this public package. Vercel account login and connection to the Goldhand image project remain a separate one-time, user-approved setup after installation.

The managed copy checks for a newer validated GitHub Release at Windows sign-in and every six hours. It never installs directly from the unvalidated `main` branch. The previous complete folder is retained until the new plugin is enabled, and a failed update restores the previous folder and connection. Recipient-side edits inside the managed folder are replaced by the next official update.

Direct selector: `goldhand-clinic-blog@goldhand-clinic-windows`

## Source archive fallback

[Download the validated release ZIP](https://github.com/seojun03/goldhand-clinic-blog-windows/releases/latest/download/goldhand-clinic-blog-plugin.zip), extract it, and double-click `INSTALL-WINDOWS.cmd`. If the CMD is accidentally separated from the other files, it downloads the same validated release and continues.

## Verification

The GitHub Actions workflow runs plugin content tests and uses Windows PowerShell 5.1 to verify an actual Vercel CLI installation and version command, complete-archive installation, isolated-CMD recovery, invalid Codex candidate rejection, missing `CODEX_HOME` creation, nonfatal locked cleanup, transactional managed replacement, and enabled local plugin registration.
