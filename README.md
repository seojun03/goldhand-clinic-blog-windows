# Goldhand Clinic Blog Codex plugin

Windows recipients can install this plugin from one file. They do not need Git, a ZIP extractor, or a PowerShell command.

## Windows one-file install

**[Download INSTALL-WINDOWS.cmd](https://github.com/seojun03/goldhand-clinic-blog-windows/releases/latest/download/INSTALL-WINDOWS.cmd)**

1. Download the file from the link above.
2. Close ChatGPT completely.
3. Double-click `INSTALL-WINDOWS.cmd`.
4. If a browser opens, sign in to the recipient's own Vercel account and approve the connection once.
5. Wait for `INSTALLATION COMPLETE`, close the window, and reopen ChatGPT.

The installer does not install, update, remove, or modify the ChatGPT app. It verifies Python, installs Node.js LTS only when a working npm is missing, installs and executes the Vercel CLI, verifies a Codex CLI that supports plugins, downloads the latest validated release to a short path, transactionally replaces `%USERPROFILE%\GoldhandBlog`, and connects it as a local marketplace plugin. After the browser login approval, it creates and links the recipient's own `goldhand-blog-images` project, performs the first production deployment, selects a stable public HTTPS alias, and saves the plugin's `image-host.json` automatically.

No Vercel password or token is bundled in this public package. The recipient only approves their own Vercel login in the browser; project names, folders, URLs, and JSON settings are not entered manually. If login is closed before approval, `Goldhand Image Setup` remains on the Desktop as a one-click retry shortcut.

The managed copy checks for a newer validated GitHub Release at Windows sign-in and every six hours. It never installs directly from the unvalidated `main` branch. The previous complete folder is retained until the new plugin is enabled, and a failed update restores the previous folder and connection. Recipient-side edits inside the managed folder are replaced by the next official update.

Direct selector: `goldhand-clinic-blog@goldhand-clinic-windows`

## Source archive fallback

[Download the validated release ZIP](https://github.com/seojun03/goldhand-clinic-blog-windows/releases/latest/download/goldhand-clinic-blog-plugin.zip), extract it, and double-click `INSTALL-WINDOWS.cmd`. If the CMD is accidentally separated from the other files, it downloads the same validated release and continues.

## Verification

The GitHub Actions workflow runs plugin content tests and uses Windows PowerShell 5.1 to verify an actual Vercel CLI installation and version command, the first-time image-host automation contract, complete-archive installation, isolated-CMD recovery, invalid Codex candidate rejection, missing `CODEX_HOME` creation, nonfatal locked cleanup, transactional managed replacement, and enabled local plugin registration.

## Owner publishing

The canonical plugin's owner refresh command is connected to `scripts/publish_update.py` through the owner-only `publisher.json` state file. A source refresh validates and syncs the complete plugin, commits and pushes `main`, waits for the Windows PowerShell 5.1 workflow, creates a versioned GitHub Release only after CI succeeds, redownloads both public assets to verify SHA-256, and runs the public one-file installation workflow. Recipient machines do not receive GitHub credentials and do not run the owner publisher.
