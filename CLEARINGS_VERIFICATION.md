<!-- SPDX-License-Identifier: MPL-2.0 -->
# Clearings 0.4.4 verification boundary

This release adds a Windows tray icon for the running local helper. It shows the version and loopback address, opens Clearings, and offers Stop helper with a save-edits reminder. Icon lifetime follows helper lifetime. Windows may place it in the overflow area. No automatic startup or login registration is added. The implementation uses Windows APIs via ctypes and adds no package dependency.

Native tray checks use a temporary icon and Windows Shell_NotifyIconGetRect to verify registration, recovery after removing that fixture registration, and removal on shutdown. They do not restart Explorer or read the owner's workspace. Callback checks cover opening, cancelled stopping and stopping once. Helper checks cover tray creation/cleanup, startup failure, and explicit headless opt-out. This is not a screenshot-based verification of each display scale or a human click-through of the owner's taskbar.

The four-platform build checks source and bundles each helper. Windows additionally installs the exact checksummed 0.4.3 release, saves fictional handoff data, upgrades to 0.4.4 while running, reinstalls 0.4.4, then uninstalls; saved data must remain byte-identical. CI uses --no-tray for headless helper checks; native tray evidence comes from the separate Windows desktop fixture. The installer replaces bundled files; automatic update discovery, downgrade prevention and general removal of obsolete bundle files remain outside this release. No previous program paths are removed by 0.4.4.

Clearings retains its 0.4.3 collaboration and schema contracts: document 2 with optional attribution, workspace 1, index 4. The tray does not save browser drafts or migrate browser profiles. Working and installed origins remain separate. It coordinates authorized assistants but does not launch them. Names and receipts are local attribution, not authentication or cryptographic signatures.

Windows builds remain unsigned; Mac builds are ad-hoc signed and not notarized. The owner's Firefox profile, Safari, interactive Mac/Linux installation, accessibility tools, and OS security prompts are not certified by the automated checks. Keep this a private review release until the owner chooses otherwise.

Windows APIs: https://learn.microsoft.com/en-us/windows/win32/shell/notification-area and https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw
