package com.jarvis.remote;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public class MainActivity extends Activity {

    private static final String PREFS = "jarvis_remote";
    private static final String KEY_URL = "server_url";
    private static final String KEY_TOKEN = "server_token";
    private static final int REQ_MIC = 1001;
    private static final long RECONNECT_DELAY_MS = 10_000L;

    private WebView webView;
    private FrameLayout root;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private String pendingUrl;
    private boolean awaitingReconnect = false;

    private final Runnable reconnect = new Runnable() {
        @Override
        public void run() {
            awaitingReconnect = false;
            if (pendingUrl != null && webView != null) {
                webView.loadUrl(pendingUrl);
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#03060d"));

        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                // Разрешаем WebView доступ к микрофону для голосового ввода.
                for (String resource : request.getResources()) {
                    if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)) {
                        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                                == PackageManager.PERMISSION_GRANTED) {
                            request.grant(new String[]{resource});
                        } else {
                            request.deny();
                        }
                        return;
                    }
                }
                request.deny();
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                // Остаёмся внутри WebView для http(s)-страниц JARVIS.
                String scheme = request.getUrl().getScheme();
                return !("http".equals(scheme) || "https".equals(scheme));
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                if (request.isForMainFrame()) {
                    scheduleReconnect();
                }
            }
        });

        root.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        // Плавающая кнопка настроек (сервер + токен).
        TextView gear = new TextView(this);
        gear.setText("⚙");
        gear.setTextSize(22);
        gear.setTextColor(Color.parseColor("#2ee6ff"));
        gear.setBackgroundColor(Color.parseColor("#0a1420"));
        gear.setPadding(24, 12, 24, 12);
        gear.setOnClickListener(v -> showSettingsDialog());
        FrameLayout.LayoutParams gearParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP | Gravity.END);
        gearParams.setMargins(0, 24, 24, 0);
        root.addView(gear, gearParams);

        setContentView(root);
        startService(new Intent(this, RemoteService.class));
        requestMicPermission();
        loadServer();
    }

    private void requestMicPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                && checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                        != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions,
                                           int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_MIC
                && (grantResults.length == 0
                        || grantResults[0] != PackageManager.PERMISSION_GRANTED)) {
            Toast.makeText(this,
                    "Нет доступа к микрофону — голосовой ввод отключён.",
                    Toast.LENGTH_LONG).show();
        }
    }

    private void scheduleReconnect() {
        if (awaitingReconnect || pendingUrl == null) {
            return;
        }
        awaitingReconnect = true;
        Toast.makeText(this,
                "Нет связи с JARVIS. Переподключение через 10 c…",
                Toast.LENGTH_SHORT).show();
        handler.postDelayed(reconnect, RECONNECT_DELAY_MS);
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private String normalizeBase(String base) {
        String url = base.trim();
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        return url;
    }

    private void loadServer() {
        String url = prefs().getString(KEY_URL, "");
        String token = prefs().getString(KEY_TOKEN, "");
        if (url.isEmpty() || token.isEmpty()) {
            showSettingsDialog();
            return;
        }
        loginAndLoad(normalizeBase(url), token);
    }

    private void loginAndLoad(String base, String token) {
        // Токен больше не уходит в URL: обмениваем его на HttpOnly-cookie
        // через POST /login и передаём cookie в WebView.
        pendingUrl = base;
        CookieManager.getInstance().setAcceptCookie(true);
        new Thread(() -> {
            String cookie = login(base, token);
            runOnUiThread(() -> {
                if (cookie == null) {
                    Toast.makeText(this,
                            "Не удалось войти: проверьте адрес и токен.",
                            Toast.LENGTH_LONG).show();
                    return;
                }
                CookieManager manager = CookieManager.getInstance();
                manager.setCookie(base, cookie);
                manager.flush();
                webView.loadUrl(base);
            });
        }, "jarvis-login").start();
    }

    private String login(String base, String token) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(base + "/login").openConnection();
            conn.setConnectTimeout(8000);
            conn.setReadTimeout(8000);
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json");
            String payload = "{\"token\":\""
                    + token.replace("\\", "\\\\").replace("\"", "\\\"")
                    + "\"}";
            byte[] body = payload.getBytes(StandardCharsets.UTF_8);
            conn.setFixedLengthStreamingMode(body.length);
            try (OutputStream out = conn.getOutputStream()) {
                out.write(body);
            }
            int code = conn.getResponseCode();
            if (code != 200 && code != 204) {
                return null;
            }
            String setCookie = conn.getHeaderField("Set-Cookie");
            if (setCookie == null || setCookie.isEmpty()) {
                return null;
            }
            return setCookie.split(";", 2)[0];
        } catch (Exception error) {
            return null;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private void showSettingsDialog() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        layout.setPadding(pad, pad, pad, 0);

        EditText urlInput = new EditText(this);
        urlInput.setHint("Адрес сервера, напр. https://abc.trycloudflare.com");
        urlInput.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        urlInput.setText(prefs().getString(KEY_URL, ""));
        layout.addView(urlInput);

        EditText tokenInput = new EditText(this);
        tokenInput.setHint("Токен доступа");
        tokenInput.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        tokenInput.setText(prefs().getString(KEY_TOKEN, ""));
        layout.addView(tokenInput);

        new AlertDialog.Builder(this)
                .setTitle("JARVIS Remote — подключение")
                .setView(layout)
                .setPositiveButton("Подключить", (dialog, which) -> {
                    String url = urlInput.getText().toString().trim();
                    String token = tokenInput.getText().toString().trim();
                    if (url.isEmpty() || token.isEmpty()) {
                        Toast.makeText(this, "Введите адрес и токен",
                                Toast.LENGTH_SHORT).show();
                        return;
                    }
                    prefs().edit()
                            .putString(KEY_URL, url)
                            .putString(KEY_TOKEN, token)
                            .apply();
                    loginAndLoad(normalizeBase(url), token);
                })
                .setNegativeButton("Отмена", null)
                .show();
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(reconnect);
        if (webView != null) {
            webView.destroy();
        }
        stopService(new Intent(this, RemoteService.class));
        super.onDestroy();
    }
}
