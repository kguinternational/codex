# Tech Unfiltered AGI — Production Suite & AI Editor

This directory contains the production assets, Premiere Pro templates, audio assets, and YouTube release metadata for the **Tech Unfiltered AGI** channel, powered by **KGU International**.

## Structure

- `edit-template/`: Adobe Premiere Pro project files (`.prproj`), autosaves, SFX, and brand assets.
  - `place holder assets (replace)/`: Logo and background music (`CrystalClear_artwork.png`, `CG3EHPS-in-to-hip-hop.mp3`).
  - `Whip Woosh Swish SFX.mp3`, `Whip Woosh Swish SFX.mp4`: Audio and visual transition assets.
- `exports/`: Production exports and thumbnails.
  - `TEC_Trailer.mp3`: Master soundtrack export.
  - `frame_5s.jpg`, `frame_25s.jpg`, `frame_50s.jpg`: High-res studio capture frames with the neon "TECH UNFILTERED AGI - POWERED BY KGU INTERNATIONAL" display.
- `YOUTUBE_METADATA.md`: Ready-to-publish YouTube titles, description, timestamps, tags, and thumbnail strategy.

## AI Video Editing Integration (OpenCode & Editor V1)

This project is integrated with **OpenCode** (installed globally at `v1.19.4`) using the free open model `opencode/glm-5.3-flash-free` along with FFmpeg and audio processing pipelines.

To run automated edits:
```bash
opencode run -m opencode/glm-5.3-flash-free "edit this video with editor v1"
```
