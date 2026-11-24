# Kinocut renders in Hermes Desktop

Turn on Kinocut under **Capabilities → Plugins**. Open **Kinocut renders** in the right sidebar or choose **Kinocut: Show renders** from the command palette. The status bar opens the workspace during a render or just after it finishes.

| State | What to check |
| --- | --- |
| [Idle](kinocut-idle.png) | The Kinocut mark, name and one instruction tell you where to start. |
| [Running](kinocut-running.png) | The render name and percent sit above a labelled progress bar. The pane estimates time left once it has enough progress data. |
| [Finished](kinocut-finished.png) | The row shows elapsed time and output size. Tab reaches the row and shows a focus outline. |
| [Failed](kinocut-failed.png) | The row names the failure. The missing-source test wrote no output. |
| [Status bar](kinocut-status.png) | The status button names the active render and opens the pane. |

The screenshots use a synthetic test video. The native check called `video_shorts` through the default Hermes tool-discovery path in light and dark themes. It measured a 1080×1920 MP4 and repeated the call with a missing input. It checked the 300-pixel pane for horizontal overflow, progress label and value, visible keyboard focus, and the failure cause with reduced motion enabled. A scripted provider selected the calls. Kinocut and FFmpeg performed the edits.

The pane applies the same hierarchy as [AG4TE](https://github.com/NousResearch/hermes-agent/pull/152832) and [UNBL0CK](https://github.com/NousResearch/hermes-agent/pull/152126). The mark identifies the plugin, the first card shows the current result, and rendered numbers use monospace. The progress bar is the pane's main visual. Full-page chart controls and comparison grids do not fit this sidebar.

In the two tested themes, the failure label measured at least 5.3:1 against its card and the progress fill at least 3.8:1 against its track.

Run `node --test plugins/kinocut/desktop/plugin.test.mjs` to check the event reducer without a Desktop installation.
