<div align="center">

<img src="viewatlas_assets/viewatlas_mark.png" alt="ViewAtlas logo" width="190" />

# ViewAtlas
**Free camera bookmarks & viewport screenshot tool for Adobe Substance 3D Painter**

[English](README.md) · [한국어](README_KO.md) · [Free Gumroad download](https://9870424699986.gumroad.com/l/vbncosi)

</div>

ViewAtlas is a free, no-activation-required Python plugin that helps 3D artists save camera angles and capture consistent presentation screenshots inside Substance 3D Painter.

## What it does

- Save and restore up to **10 camera bookmarks**.
- Preview saved viewpoints as thumbnails.
- Capture a selected viewport region to an image file.
- Batch-capture saved camera views and combine them into layouts.
- Choose capture filename, output folder, and supported image formats.
- Export/import camera bookmark data as JSON.
- Multilingual user interface and a compact three-tab layout.
- Global and per-view display-mode preferences (automatic channel switching is experimental).

## Screenshots

See [actual ViewAtlas interface screenshots and capture examples on Gumroad](https://9870424699986.gumroad.com/l/vbncosi).

## Installation (Windows)

1. Download the files from this repository (Code → Download ZIP) or from [Gumroad](https://9870424699986.gumroad.com/l/vbncosi).
2. Copy **`viewatlas_v15.py`** and the entire **`viewatlas_assets`** folder into the Substance 3D Painter Python plugins directory, usually:

   ```text
   C:\Users\<your-username>\Documents\Adobe\Adobe Substance 3D Painter\python\plugins
   ```

3. Keep the `.py` file and `viewatlas_assets` folder side by side.
4. Restart Substance 3D Painter and open ViewAtlas from the application's **Window** menu (the menu location may vary with your Painter version).

> If you are upgrading, first move old ViewAtlas `.py` versions out of your plugins directory so they do not load simultaneously. Your existing bookmarks are stored with your project; make a project backup before switching.

## Compatibility & limitations

- **Painter 9.0:** Camera-bookmark APIs needed by the plugin are not available.
- **Painter 9.1–10.0:** PySide2/Qt5 compatibility path is included but not verified in those Painter builds.
- **Painter 10.1–12.x:** PySide6/Qt6 compatibility path is included; full real-world version-by-version testing has not been completed.
- **Automatic display-channel switching is experimental.** It may behave differently depending on the Painter version, keyboard shortcuts, and texture-set configuration.
- Capture uses visible viewport pixels at **native on-screen resolution**; ViewAtlas does not automate higher-resolution Iray rendering.
- Image file types depend on the formats supported by the installed Qt image plugins.

## Download & feedback

Free download: **[ViewAtlas on Gumroad](https://9870424699986.gumroad.com/l/vbncosi)**.

Bug report? Open an issue and include your Painter version, operating system, what you clicked, and the error message. Please remove personal file paths and account details from screenshots.

## Notes

ViewAtlas is an independent third-party plugin, not affiliated with or endorsed by Adobe.

**Free to download and use.** No source-code redistribution/modification license has been specified; if you plan to reuse the code, ask the author for permission.