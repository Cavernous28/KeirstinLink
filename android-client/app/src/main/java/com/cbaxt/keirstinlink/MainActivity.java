package com.cbaxt.keirstinlink;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Base64;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;
import androidx.webkit.WebViewAssetLoader;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public class MainActivity extends AppCompatActivity {
    private static final int REQUEST_READ_STORAGE = 1001;
    private static final int PICK_FILES_REQUEST = 1002;
    private WebView webView;
    private EditText serverInput;
    private String baseUrl = "https://appassets.androidplatform.net/assets/";
    private String backendHost = "";
    private int backendPort = 3710;

    private final ActivityResultLauncher<String[]> permissionLauncher = registerForActivityResult(
            new ActivityResultContracts.RequestMultiplePermissions(), result -> {
                // storage permissions handled if needed
            });

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        Thread.setDefaultUncaughtExceptionHandler((thread, throwable) -> {
            try {
                String msg = android.util.Log.getStackTraceString(throwable);
                android.util.Log.e("KeirstinLinkCrash", msg);
                saveCrashLog(msg);
                postCrash(msg);
            } catch (Exception ignored) {}
            android.os.Process.killProcess(android.os.Process.myPid());
            System.exit(1);
        });

        requestStoragePermissions();

        serverInput = findViewById(R.id.serverInput);
        Button btnConnect = findViewById(R.id.btnConnect);
        webView = findViewById(R.id.webview);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        WebViewAssetLoader assetLoader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        webView.setWebViewClient(new LocalContentWebViewClient(assetLoader));
        webView.addJavascriptInterface(new AndroidBridge(), "AndroidBridge");

        // Load bundled frontend from app assets
        webView.loadUrl(baseUrl + "index.html");

        btnConnect.setOnClickListener(v -> connectToBackend());
        serverInput.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_DONE) {
                connectToBackend();
                return true;
            }
            return false;
        });
    }

    private void connectToBackend() {
        String raw = serverInput.getText().toString().trim();
        if (raw.isEmpty()) {
            Toast.makeText(this, "Enter master IP:port", Toast.LENGTH_SHORT).show();
            return;
        }
        backendHost = raw;
        backendPort = 3710;
        if (raw.contains(":")) {
            String[] parts = raw.split(":");
            backendHost = parts[0];
            try {
                backendPort = Integer.parseInt(parts[1]);
            } catch (NumberFormatException ignored) {
            }
        }
        final String jsHost = escapeJs(backendHost);
        String url = "http://" + backendHost + ":" + backendPort + "/health";
        webView.evaluateJavascript(
                "(function(){ if(window.KeirstinLinkBackend){ window.KeirstinLinkBackend.connect('" + jsHost + "', " + backendPort + "); return 'ok';} return 'no backend object'; })()",
                null);
        Toast.makeText(this, "Connecting to " + backendHost + ":" + backendPort, Toast.LENGTH_SHORT).show();
    }

    private void requestStoragePermissions() {
        List<String> perms = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            perms.add(Manifest.permission.READ_MEDIA_IMAGES);
            perms.add(Manifest.permission.READ_MEDIA_VIDEO);
            perms.add(Manifest.permission.READ_MEDIA_AUDIO);
        } else {
            perms.add(Manifest.permission.READ_EXTERNAL_STORAGE);
        }
        permissionLauncher.launch(perms.toArray(new String[0]));
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, @Nullable Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == PICK_FILES_REQUEST && resultCode == Activity.RESULT_OK && data != null) {
            Uri uri = data.getData();
            if (uri != null) {
                String encoded = readUriAsBase64(uri);
                String name = getFileName(uri);
                webView.evaluateJavascript(
                        "window.KeirstinLinkBridge.onFilesPicked([{name:'" + escapeJs(name) + "',data:'" + encoded + "'}])",
                        null);
            }
        }
    }

    private String readUriAsBase64(Uri uri) {
        try (InputStream in = getContentResolver().openInputStream(uri);
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            if (in == null) return "";
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
            return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP);
        } catch (IOException e) {
            return "";
        }
    }

    @SuppressLint("Range")
    private String getFileName(Uri uri) {
        String result = null;
        if (uri.getScheme() != null && uri.getScheme().equals("content")) {
            try (android.database.Cursor cursor = getContentResolver().query(uri, null, null, null, null)) {
                if (cursor != null && cursor.moveToFirst()) {
                    result = cursor.getString(cursor.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME));
                }
            }
        }
        if (result == null) {
            result = uri.getLastPathSegment();
        }
        return result != null ? result : "unknown";
    }

    private String escapeJs(String s) {
        return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "");
    }

    public class AndroidBridge {
        @JavascriptInterface
        public void showToast(String message) {
            runOnUiThread(() -> Toast.makeText(MainActivity.this, message, Toast.LENGTH_SHORT).show());
        }

        @JavascriptInterface
        public void pickFile() {
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("*/*");
            startActivityForResult(intent, PICK_FILES_REQUEST);
        }

        @JavascriptInterface
        public String getBackendHost() {
            return backendHost;
        }

        @JavascriptInterface
        public int getBackendPort() {
            return backendPort;
        }
    }


    private void saveCrashLog(String trace) {
        try {
            java.io.File dir = getFilesDir();
            java.io.File log = new java.io.File(dir, "keirstinlink_crash.log");
            try (java.io.FileWriter fw = new java.io.FileWriter(log, true)) {
                fw.write(new java.util.Date().toString() + "\n" + trace + "\n\n");
            }
        } catch (Exception ignored) {}
    }
    private void postCrash(String trace) {
        new Thread(() -> {
            try {
                String host = backendHost.isEmpty() ? "192.168.1.42" : backendHost;
                URL url = new URL("http://" + host + ":" + backendPort + "/android-crash");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setDoOutput(true);
                conn.setConnectTimeout(3000);
                conn.setReadTimeout(3000);
                String body = "trace=" + urlEncode(trace);
                try (OutputStream out = conn.getOutputStream()) {
                    out.write(body.getBytes(StandardCharsets.UTF_8));
                }
                conn.getResponseCode();
            } catch (Exception ignored) {}
        }).start();
    }

    private String urlEncode(String s) {
        try {
            return java.net.URLEncoder.encode(s, "UTF-8");
        } catch (Exception e) {
            return s;
        }
    }
}
