# KeirstinLink Android Client

A lightweight Android WebView wrapper around the KeirstinLink web UI. It connects to the KeirstinLink backend running on a PC/master device over your local Wi-Fi / LAN.

## How it works

- The Android app bundles the same `index.html` / `main.js` / `styles.css` frontend as the desktop Tauri app.
- The frontend detects whether it is running under Tauri or Android and either uses Tauri invocations or plain HTTP calls to the backend.
- The Android Java bridge exposes:
  - `AndroidBridge.pickFile()` — opens the system file picker and returns base64-encoded file data to JS.
  - `AndroidBridge.getBackendHost()` / `getBackendPort()` — returns the currently configured master backend address.
  - `AndroidBridge.showToast(msg)` — shows a short toast.
- The top bar lets you enter the master PC's IP address (e.g. `192.168.1.42:3710`).

## Build requirements

- Android Studio or command-line Gradle + Android SDK
- SDK platform `android-34` (or newer)
- Build tools 34.0.0+
- `compileSdk = 34`, `minSdk = 26`, `targetSdk = 34`

## Build APK from command line

Open a terminal in `KeirstinLink/android-client/` and run:

```bash
./gradlew assembleDebug
```

The debug APK will be at:

```
app/build/outputs/apk/debug/app-debug.apk
```

For release:

```bash
./gradlew assembleRelease
```

You will need to create a signing keystore for release builds (Android Studio can do this, or use `keytool`).

## Install on phone

```bash
adb install app/build/outputs/apk/debug/app-debug.apk
```

Or copy the APK to your phone and install it directly.

## First run

1. Make sure the KeirstinLink backend is running on the master PC (Windows app installed, or Python backend started with `start.sh` / `start-backend.bat`).
2. Enter the PC's LAN IP + port (`3710`) in the top bar and tap **Connect**.
3. Use the UI to add the phone as a client device, set sync roots, and propose files.

## Syncing files from phone to PC

1. On the PC master, add the phone as a device.
2. On the phone, enter the PC backend IP and tap **Connect**.
3. In the phone UI, find the PC device card and tap **Propose** to scan local files and send proposals to the PC.
4. Approve proposals on the PC master UI. The files are then written into the PC's `KeirstinLinkSync` folder.

## Notes

- `android:usesCleartextTraffic="true"` is enabled because the PC backend currently uses plain HTTP over LAN. For non-home networks you should add TLS.
- The WebView loads assets from `https://appassets.androidplatform.net/assets/` via `WebViewAssetLoader`; no internet access is required for the UI.
