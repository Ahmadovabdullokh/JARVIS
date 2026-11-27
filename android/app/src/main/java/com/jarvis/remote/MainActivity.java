package com.jarvis.remote;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaRecorder;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.PopupMenu;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {

    private static final String PREFS = "jarvis_remote";
    private static final String KEY_URL = "server_url";
    private static final String KEY_TOKEN = "server_token";
    private static final String KEY_FALLBACK = "server_fallback";
    private static final String KEY_RDV_URL = "rdv_url";
    private static final String KEY_RDV_TOPIC = "rdv_topic";
    private static final String KEY_MODE = "chat_mode";
    static final String EXTRA_SCAN_TEXT = "com.jarvis.remote.SCAN_TEXT";
    private static final int REQ_PERMS = 1001;
    private static final int REQ_SCAN = 1002;
    private static final long POLL_MS = 1500L;
    private static final long POLL_SLOW_MS = 5000L;
    private static final long RDV_RETRY_MS = 30_000L;
    private static final String[] MODES = {"chat", "tasks", "code"};

    private static final int BG = Color.parseColor("#03060d");
    private static final int PANEL = Color.parseColor("#0a1420");
    private static final int PANEL_ALT = Color.parseColor("#0f2238");
    private static final int BORDER = Color.parseColor("#1b3a5c");
    private static final int TEXT = Color.parseColor("#cfe8ff");
    private static final int MUTED = Color.parseColor("#6f8ca8");
    private static final int ACCENT = Color.parseColor("#2ee6ff");
    private static final int BLUE = Color.parseColor("#1f6feb");
    private static final int GREEN = Color.parseColor("#3ddc84");
    private static final int RED = Color.parseColor("#ff5c5c");
    private static final int WARN = Color.parseColor("#ffb020");

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final List<Message> messages = new ArrayList<>();

    private LinearLayout root;
    private LinearLayout banner;
    private TextView bannerText;
    private TextView statusDot;
    private TextView statusText;
    private TextView modeChip;
    private TextView typing;
    private TextView micButton;
    private EditText input;
    private ListView listView;
    private ChatAdapter adapter;
    private AlertDialog settingsDialog;
    private ConnectivityManager.NetworkCallback networkCallback;

    private volatile boolean alive = true;
    private volatile boolean online = false;
    private volatile boolean polling = false;
    private volatile int generation = 0;
    private volatile long pollDelay = POLL_MS;
    private volatile long lastRdvAttempt = 0L;

    private volatile String base = "";
    private volatile String fallbackBase = "";
    private volatile String token = "";
    private String mode = "tasks";
    private JSONArray tasks = new JSONArray();
    private int partialIndex = -1;
    private String statusLabel = "OFFLINE";

    private boolean recording = false;
    private MediaRecorder recorder;
    private File recordingFile;

    private final Runnable hideTyping = () -> typing.setVisibility(View.GONE);

    private final Runnable pollRunnable = new Runnable() {
        @Override
        public void run() {
            if (!alive || !polling) {
                return;
            }
            final int gen = generation;
            io.execute(() -> {
                if (gen != generation) {
                    return;
                }
                try {
                    JSONObject data = rpc("poll", new JSONObject());
                    final JSONArray events = data.optJSONArray("events");
                    final JSONObject snapshot = data.optJSONObject("snapshot");
                    ui.post(() -> {
                        if (gen != generation) {
                            return;
                        }
                        setOnline(true, "");
                        if (events != null) {
                            for (int i = 0; i < events.length(); i++) {
                                JSONObject event = events.optJSONObject(i);
                                if (event != null) {
                                    handleEvent(event);
                                }
                            }
                        }
                        applySnapshot(snapshot);
                    });
                    pollDelay = POLL_MS;
                } catch (Exception error) {
                    pollDelay = POLL_SLOW_MS;
                    String rdv = "";
                    if (!(error instanceof UnauthorizedException)) {
                        rdv = maybeRefreshRendezvous();
                    }
                    final boolean switched =
                            !rdv.isEmpty() && !rdv.equals(base);
                    if (switched) {
                        base = rdv;
                        prefs().edit().putString(KEY_URL, rdv).apply();
                    }
                    ui.post(() -> {
                        if (gen == generation) {
                            setOnline(false, friendly(error));
                            if (switched) {
                                connect();
                            }
                        }
                    });
                } finally {
                    if (alive && polling && gen == generation) {
                        ui.postDelayed(MainActivity.this.pollRunnable, pollDelay);
                    }
                }
            });
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        mode = prefs().getString(KEY_MODE, "tasks");
        buildLayout();
        setContentView(root);

        requestPermissions();
        startService(new Intent(this, RemoteService.class));
        registerNetworkCallback();

        base = PairLink.normalizeBase(prefs().getString(KEY_URL, ""));
        fallbackBase = PairLink.normalizeBase(
                prefs().getString(KEY_FALLBACK, ""));
        token = prefs().getString(KEY_TOKEN, "").trim();
        if (handlePairLink(getIntent())) {
            return;
        }
        if (handleScannedText(getIntent().getStringExtra(EXTRA_SCAN_TEXT))) {
            return;
        }
        if (base.isEmpty() || token.isEmpty()) {
            ui.post(this::showSettings);
        } else {
            connect();
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        String scanned = intent.getStringExtra(EXTRA_SCAN_TEXT);
        if (!handlePairLink(intent)
                && !(scanned != null && handleScannedText(scanned))
                && !base.isEmpty() && !token.isEmpty()) {
            connect();
        }
    }

    private boolean handlePairLink(Intent intent) {
        if (intent == null || !Intent.ACTION_VIEW.equals(intent.getAction())) {
            return false;
        }
        Uri data = intent.getData();
        final String[] pair = PairLink.parse(data);
        if (pair == null) {
            if (data != null && "jarvis".equals(data.getScheme())) {
                Toast.makeText(this,
                        "Ссылка подключения неполная: нужны url и token",
                        Toast.LENGTH_LONG).show();
            }
            return false;
        }
        confirmPair(pair);
        return true;
    }

    private boolean handleScannedText(String text) {
        String raw = text == null ? "" : text.trim();
        if (raw.isEmpty()) {
            return false;
        }
        String[] pair = PairLink.parseText(raw);
        if (pair == null) {
            Toast.makeText(this,
                    "QR-код не содержит ссылку подключения JARVIS",
                    Toast.LENGTH_LONG).show();
            return false;
        }
        confirmPair(pair);
        return true;
    }

    private void confirmPair(final String[] pair) {
        if (settingsDialog != null) {
            settingsDialog.dismiss();
            settingsDialog = null;
        }
        String message = "Адрес: " + PairLink.hostOf(pair[PairLink.URL]);
        if (!pair[PairLink.FALLBACK].isEmpty()) {
            message += "\nДомашняя сеть: "
                    + PairLink.hostOf(pair[PairLink.FALLBACK]);
        }
        if (!pair[PairLink.RDV_TOPIC].isEmpty()) {
            message += "\nАвтообновление адреса: включено";
        }
        message += "\n\nБудут сохранены новый адрес и токен доступа.";
        new AlertDialog.Builder(this)
                .setTitle("Подключиться к JARVIS?")
                .setMessage(message)
                .setPositiveButton("Подключиться", (dialog, which) -> {
                    prefs().edit()
                            .putString(KEY_URL, pair[PairLink.URL])
                            .putString(KEY_TOKEN, pair[PairLink.TOKEN])
                            .putString(KEY_FALLBACK, pair[PairLink.FALLBACK])
                            .putString(KEY_RDV_URL, pair[PairLink.RDV_URL])
                            .putString(KEY_RDV_TOPIC, pair[PairLink.RDV_TOPIC])
                            .apply();
                    ui.post(this::connect);
                })
                .setNegativeButton("Отмена", (dialog, which) -> {
                    if (base.isEmpty() || token.isEmpty()) {
                        ui.post(this::showSettings);
                    }
                })
                .setCancelable(false)
                .show();
    }

    private String clipboardText() {
        android.content.ClipboardManager clipboard =
                (android.content.ClipboardManager) getSystemService(
                        Context.CLIPBOARD_SERVICE);
        if (clipboard == null || !clipboard.hasPrimaryClip()) {
            return "";
        }
        android.content.ClipData clip = clipboard.getPrimaryClip();
        if (clip == null || clip.getItemCount() == 0) {
            return "";
        }
        CharSequence text = clip.getItemAt(0).coerceToText(this);
        return text == null ? "" : text.toString();
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private GradientDrawable rounded(int color, int radiusDp) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(radiusDp));
        return shape;
    }

    private GradientDrawable outlined(int color, int stroke, int radiusDp) {
        GradientDrawable shape = rounded(color, radiusDp);
        shape.setStroke(dp(1), stroke);
        return shape;
    }

    private void buildLayout() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.setFitsSystemWindows(true);

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.setPadding(dp(14), dp(14), dp(8), dp(12));
        top.setBackgroundColor(PANEL);

        LinearLayout titleBox = new LinearLayout(this);
        titleBox.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams titleParams = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        titleBox.setLayoutParams(titleParams);

        TextView title = new TextView(this);
        title.setText("J.A.R.V.I.S.");
        title.setTextColor(ACCENT);
        title.setTextSize(18);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setLetterSpacing(0.12f);
        titleBox.addView(title);

        LinearLayout statusRow = new LinearLayout(this);
        statusRow.setOrientation(LinearLayout.HORIZONTAL);
        statusRow.setGravity(Gravity.CENTER_VERTICAL);
        statusRow.setPadding(0, dp(2), 0, 0);

        statusDot = new TextView(this);
        statusDot.setText("●");
        statusDot.setTextSize(12);
        statusDot.setTextColor(MUTED);
        statusRow.addView(statusDot);

        statusText = new TextView(this);
        statusText.setText("ПОДКЛЮЧЕНИЕ…");
        statusText.setTextColor(MUTED);
        statusText.setTextSize(11);
        statusText.setPadding(dp(4), 0, 0, 0);
        statusRow.addView(statusText);
        titleBox.addView(statusRow);
        top.addView(titleBox);

        modeChip = new TextView(this);
        modeChip.setTextSize(11);
        modeChip.setTextColor(ACCENT);
        modeChip.setTypeface(Typeface.DEFAULT_BOLD);
        modeChip.setPadding(dp(10), dp(6), dp(10), dp(6));
        modeChip.setBackground(outlined(BG, BORDER, 8));
        modeChip.setOnClickListener(v -> cycleMode());
        LinearLayout.LayoutParams chipParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        chipParams.setMargins(0, 0, dp(8), 0);
        top.addView(modeChip, chipParams);

        TextView menuButton = new TextView(this);
        menuButton.setText("⋮");
        menuButton.setTextSize(22);
        menuButton.setTextColor(TEXT);
        menuButton.setGravity(Gravity.CENTER);
        menuButton.setBackground(rounded(PANEL_ALT, 8));
        menuButton.setOnClickListener(this::showMenu);
        top.addView(menuButton, new LinearLayout.LayoutParams(dp(40), dp(40)));

        root.addView(top, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        banner = new LinearLayout(this);
        banner.setOrientation(LinearLayout.HORIZONTAL);
        banner.setGravity(Gravity.CENTER_VERTICAL);
        banner.setPadding(dp(12), dp(8), dp(12), dp(8));
        banner.setBackgroundColor(Color.parseColor("#2a1018"));
        banner.setVisibility(View.GONE);
        banner.setOnClickListener(v -> connect());

        bannerText = new TextView(this);
        bannerText.setTextColor(Color.parseColor("#ffb0b0"));
        bannerText.setTextSize(12);
        bannerText.setMaxLines(2);
        banner.addView(bannerText);

        root.addView(banner, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        listView = new ListView(this);
        listView.setBackgroundColor(BG);
        listView.setDivider(null);
        listView.setDividerHeight(0);
        listView.setPadding(0, dp(6), 0, dp(6));
        listView.setClipToPadding(false);
        adapter = new ChatAdapter();
        listView.setAdapter(adapter);
        listView.setOnItemLongClickListener((parent, view, position, id) -> {
            Message message = messages.get(position);
            copyMessage(message.text);
            return true;
        });
        root.addView(listView, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        typing = new TextView(this);
        typing.setText("JARVIS печатает…");
        typing.setTextColor(MUTED);
        typing.setTextSize(11);
        typing.setPadding(dp(16), 0, dp(16), dp(6));
        typing.setVisibility(View.GONE);
        root.addView(typing);

        LinearLayout inputRow = new LinearLayout(this);
        inputRow.setOrientation(LinearLayout.HORIZONTAL);
        inputRow.setGravity(Gravity.CENTER_VERTICAL);
        inputRow.setPadding(dp(10), dp(8), dp(10), dp(12));
        inputRow.setBackgroundColor(PANEL);

        input = new EditText(this);
        input.setHint("Сообщение JARVIS…");
        input.setHintTextColor(MUTED);
        input.setTextColor(TEXT);
        input.setTextSize(15);
        input.setMaxLines(5);
        input.setBackground(rounded(PANEL_ALT, 14));
        input.setPadding(dp(14), dp(10), dp(14), dp(10));
        input.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
                | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        input.setImeOptions(EditorInfo.IME_ACTION_SEND);
        input.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendMessage();
                return true;
            }
            return false;
        });
        inputRow.addView(input, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        micButton = new TextView(this);
        micButton.setText("🎤");
        micButton.setTextSize(20);
        micButton.setGravity(Gravity.CENTER);
        micButton.setBackground(rounded(PANEL_ALT, 14));
        micButton.setOnClickListener(v -> toggleRecording());
        LinearLayout.LayoutParams micParams = new LinearLayout.LayoutParams(
                dp(48), dp(48));
        micParams.setMargins(dp(6), 0, 0, 0);
        inputRow.addView(micButton, micParams);

        TextView send = new TextView(this);
        send.setText("➤");
        send.setTextSize(20);
        send.setTextColor(Color.WHITE);
        send.setGravity(Gravity.CENTER);
        send.setBackground(rounded(BLUE, 14));
        send.setOnClickListener(v -> sendMessage());
        LinearLayout.LayoutParams sendParams = new LinearLayout.LayoutParams(
                dp(48), dp(48));
        sendParams.setMargins(dp(6), 0, 0, 0);
        inputRow.addView(send, sendParams);

        root.addView(inputRow, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        updateModeChip();
        updateStatus("ПОДКЛЮЧЕНИЕ…", WARN);
    }

    private void showMenu(View anchor) {
        PopupMenu popup = new PopupMenu(this, anchor);
        popup.getMenu().add(0, 1, 0, "Задачи");
        popup.getMenu().add(0, 2, 1, "Журнал");
        popup.getMenu().add(0, 3, 2, "Диагностика");
        popup.getMenu().add(0, 4, 3, "Настройки подключения");
        popup.getMenu().add(0, 5, 4, "Переподключить");
        popup.getMenu().add(0, 6, 5, "Камера");
        popup.getMenu().add(0, 7, 6, "Сканировать QR");
        popup.setOnMenuItemClickListener(item -> {
            switch (item.getItemId()) {
                case 1:
                    showTasks();
                    return true;
                case 2:
                    showJournal();
                    return true;
                case 3:
                    runDoctor();
                    return true;
                case 4:
                    showSettings();
                    return true;
                case 5:
                    connect();
                    return true;
                case 6:
                    startActivity(new Intent(
                            this, CameraActivity.class));
                    return true;
                case 7:
                    startActivityForResult(new Intent(
                            this, QrScanActivity.class), REQ_SCAN);
                    return true;
                default:
                    return false;
            }
        });
        popup.show();
    }

    private void requestPermissions() {
        List<String> wanted = new ArrayList<>();
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            wanted.add(Manifest.permission.RECORD_AUDIO);
        }
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                != PackageManager.PERMISSION_GRANTED) {
            wanted.add("android.permission.POST_NOTIFICATIONS");
        }
        if (!wanted.isEmpty()) {
            requestPermissions(wanted.toArray(new String[0]), REQ_PERMS);
        }
    }

    private void registerNetworkCallback() {
        try {
            ConnectivityManager manager =
                    (ConnectivityManager) getSystemService(
                            Context.CONNECTIVITY_SERVICE);
            if (manager == null) {
                return;
            }
            networkCallback = new ConnectivityManager.NetworkCallback() {
                @Override
                public void onAvailable(Network network) {
                    if (!online && !base.isEmpty() && !token.isEmpty()) {
                        ui.post(() -> {
                            if (alive && !online) {
                                connect();
                            }
                        });
                    }
                }
            };
            manager.registerDefaultNetworkCallback(networkCallback);
        } catch (Exception ignored) {
            networkCallback = null;
        }
    }

    private void connect() {
        base = PairLink.normalizeBase(prefs().getString(KEY_URL, ""));
        fallbackBase = PairLink.normalizeBase(
                prefs().getString(KEY_FALLBACK, ""));
        token = prefs().getString(KEY_TOKEN, "").trim();
        if (base.isEmpty() || token.isEmpty()) {
            showSettings();
            return;
        }
        generation++;
        polling = false;
        final int gen = generation;
        ui.removeCallbacks(pollRunnable);
        banner.setVisibility(View.GONE);
        updateStatus("ПОДКЛЮЧЕНИЕ…", WARN);
        io.execute(() -> {
            final String primary = base;
            final String fallback = fallbackBase;
            try {
                JSONObject boot = rpc("bootstrap", new JSONObject());
                ui.post(() -> {
                    if (gen != generation) {
                        return;
                    }
                    applyBootstrap(boot);
                    startPolling();
                });
            } catch (Exception error) {
                if (!(error instanceof UnauthorizedException)
                        && !fallback.isEmpty()
                        && !fallback.equals(primary)) {
                    try {
                        final JSONObject boot = rpcAt(
                                fallback, "bootstrap", new JSONObject());
                        ui.post(() -> {
                            if (gen != generation) {
                                return;
                            }
                            // Меняем адреса местами: следующий запуск
                            // снова попробует публичный туннель первым.
                            prefs().edit()
                                    .putString(KEY_URL, fallback)
                                    .putString(KEY_FALLBACK, primary)
                                    .apply();
                            base = fallback;
                            fallbackBase = primary;
                            applyBootstrap(boot);
                            startPolling();
                        });
                        return;
                    } catch (Exception ignored) {
                        // Покажем ошибку основного адреса.
                    }
                }
                if (!(error instanceof UnauthorizedException)) {
                    // Quick tunnel мог перезапуститься с новым адресом:
                    // берём актуальный URL из rendezvous и пробуем снова.
                    String rdv = Rendezvous.refresh(
                            getApplicationContext());
                    if (!rdv.isEmpty()
                            && !rdv.equals(primary)
                            && !rdv.equals(fallback)) {
                        try {
                            final JSONObject boot = rpcAt(
                                    rdv, "bootstrap", new JSONObject());
                            ui.post(() -> {
                                if (gen != generation) {
                                    return;
                                }
                                prefs().edit()
                                        .putString(KEY_URL, rdv)
                                        .apply();
                                base = rdv;
                                applyBootstrap(boot);
                                startPolling();
                            });
                            return;
                        } catch (Exception ignored) {
                            // Rendezvous-адрес тоже не ответил.
                        }
                    }
                }
                ui.post(() -> {
                    if (gen != generation) {
                        return;
                    }
                    setOnline(false, friendly(error));
                    if (error instanceof UnauthorizedException) {
                        showSettings();
                    } else if (alive) {
                        // ПК мог ещё не поднять туннель: пробуем снова,
                        // когда JARVIS допишет актуальный адрес.
                        ui.postDelayed(() -> {
                            if (alive && !online
                                    && gen == generation) {
                                connect();
                            }
                        }, 15_000L);
                    }
                });
            }
        });
    }

    private String maybeRefreshRendezvous() {
        long now = SystemClock.elapsedRealtime();
        if (now - lastRdvAttempt < RDV_RETRY_MS) {
            return "";
        }
        lastRdvAttempt = now;
        return Rendezvous.refresh(getApplicationContext());
    }

    private void startPolling() {
        if (polling) {
            return;
        }
        polling = true;
        pollDelay = POLL_MS;
        ui.post(pollRunnable);
    }

    private void applyBootstrap(JSONObject boot) {
        String serverMode = boot.optString("chat_mode", "");
        if (!serverMode.isEmpty()) {
            setMode(serverMode, false);
        }
        JSONObject status = boot.optJSONObject("status");
        applyStatus(status);
        JSONArray serverTasks = boot.optJSONArray("tasks");
        if (serverTasks != null) {
            tasks = serverTasks;
        }
        if (messages.isEmpty()) {
            String greeting = boot.optString("greeting", "");
            if (!greeting.isEmpty()) {
                append("assistant", greeting);
            }
        }
        setOnline(true, "");
    }

    private void applySnapshot(JSONObject snapshot) {
        if (snapshot == null) {
            return;
        }
        applyStatus(snapshot.optJSONObject("status"));
        String serverMode = snapshot.optString("chat_mode", "");
        if (!serverMode.isEmpty() && !serverMode.equals(mode)) {
            setMode(serverMode, false);
        }
        JSONArray serverTasks = snapshot.optJSONArray("tasks");
        if (serverTasks != null) {
            tasks = serverTasks;
        }
    }

    private void applyStatus(JSONObject status) {
        if (status == null) {
            return;
        }
        String label = status.optString("label", "").toUpperCase(Locale.US);
        String name = status.optString("name", "").toLowerCase(Locale.US);
        if (label.isEmpty()) {
            label = name.isEmpty() ? "ONLINE" : name.toUpperCase(Locale.US);
        }
        statusLabel = label;
        int color = ACCENT;
        if (label.contains("ONLINE") || name.equals("listening")
                || name.equals("ready")) {
            color = GREEN;
        } else if (label.contains("ERROR") || name.equals("error")) {
            color = RED;
        } else if (label.contains("STOP") || name.equals("stopped")) {
            color = MUTED;
        } else if (label.contains("START") || label.contains("BUSY")) {
            color = WARN;
        }
        updateStatus(label, color);
    }

    private void updateStatus(String label, int color) {
        statusDot.setTextColor(color);
        statusText.setText(label);
    }

    private void setOnline(boolean value, String detail) {
        online = value;
        if (value) {
            banner.setVisibility(View.GONE);
            if (statusLabel.isEmpty() || "OFFLINE".equals(statusLabel)) {
                updateStatus("ONLINE", GREEN);
            }
        } else {
            if (detail != null && !detail.isEmpty()) {
                bannerText.setText("Нет связи: " + detail
                        + "\nНажмите, чтобы повторить.");
            } else {
                bannerText.setText("Нет связи. Нажмите, чтобы повторить.");
            }
            banner.setVisibility(View.VISIBLE);
            updateStatus("OFFLINE", RED);
        }
    }

    private String friendly(Exception error) {
        String text = error.getMessage();
        if (text == null || text.isEmpty()) {
            text = error.getClass().getSimpleName();
        }
        if (error instanceof java.net.SocketTimeoutException) {
            return "сервер не ответил";
        }
        if (error instanceof java.net.ConnectException) {
            return "сервер недоступен (туннель запущен?)";
        }
        if (error instanceof UnauthorizedException) {
            return "неверный токен";
        }
        return text;
    }

    private void handleEvent(JSONObject event) {
        String type = event.optString("type", "");
        Object payload = event.opt("payload");
        String text = payloadText(payload);
        switch (type) {
            case "user":
                finalizePartial();
                append("user", text);
                showTyping(true);
                break;
            case "assistant":
                showTyping(false);
                finalizePartialWith(text);
                break;
            case "assistant_partial":
                applyPartial(text);
                break;
            case "error":
                showTyping(false);
                append("error", text);
                break;
            case "system":
                append("system", text);
                break;
            case "transcript_preview":
                if (!text.isEmpty()) {
                    flashActivity("🎙 " + text);
                }
                break;
            case "llm_tool_call":
                flashActivity("🔧 " + toolName(payload));
                break;
            default:
                break;
        }
    }

    private String toolName(Object payload) {
        if (payload instanceof JSONObject) {
            JSONObject object = (JSONObject) payload;
            String name = object.optString("name", "");
            if (name.isEmpty()) {
                JSONObject function = object.optJSONObject("function");
                if (function != null) {
                    name = function.optString("name", "");
                }
            }
            return name.isEmpty() ? "инструмент" : name;
        }
        return "инструмент";
    }

    private String payloadText(Object payload) {
        if (payload == null || payload == JSONObject.NULL) {
            return "";
        }
        if (payload instanceof String) {
            return ((String) payload).trim();
        }
        return String.valueOf(payload).trim();
    }

    private void showTyping(boolean show) {
        ui.removeCallbacks(hideTyping);
        typing.setText("JARVIS печатает…");
        typing.setVisibility(show ? View.VISIBLE : View.GONE);
        if (show) {
            ui.postDelayed(hideTyping, 90_000L);
        }
    }

    private void flashActivity(String text) {
        ui.removeCallbacks(hideTyping);
        typing.setText(text);
        typing.setVisibility(View.VISIBLE);
        ui.postDelayed(hideTyping, 2500L);
    }

    private void append(String role, String text) {
        if (text == null || text.trim().isEmpty()) {
            return;
        }
        messages.add(new Message(role, text.trim(), false));
        if (messages.size() > 300) {
            messages.remove(0);
            if (partialIndex >= 0) {
                partialIndex--;
            }
        }
        adapter.notifyDataSetChanged();
        scrollToBottom();
    }

    private void applyPartial(String text) {
        if (text == null || text.isEmpty()) {
            return;
        }
        if (partialIndex < 0 || partialIndex >= messages.size()) {
            messages.add(new Message("assistant", text, true));
            partialIndex = messages.size() - 1;
        } else {
            Message message = messages.get(partialIndex);
            message.text = text;
            message.partial = true;
        }
        adapter.notifyDataSetChanged();
        scrollToBottom();
    }

    private void finalizePartial() {
        if (partialIndex >= 0 && partialIndex < messages.size()) {
            messages.get(partialIndex).partial = false;
        }
        partialIndex = -1;
    }

    private void finalizePartialWith(String text) {
        if (partialIndex >= 0 && partialIndex < messages.size()
                && text != null && !text.isEmpty()) {
            Message message = messages.get(partialIndex);
            message.text = text;
            message.partial = false;
            partialIndex = -1;
            adapter.notifyDataSetChanged();
            scrollToBottom();
            return;
        }
        finalizePartial();
        append("assistant", text);
    }

    private void scrollToBottom() {
        listView.post(() -> listView.setSelection(adapter.getCount() - 1));
    }

    private void copyMessage(String text) {
        android.content.ClipboardManager clipboard =
                (android.content.ClipboardManager) getSystemService(
                        Context.CLIPBOARD_SERVICE);
        if (clipboard != null) {
            clipboard.setPrimaryClip(
                    android.content.ClipData.newPlainText("JARVIS", text));
            Toast.makeText(this, "Скопировано", Toast.LENGTH_SHORT).show();
        }
    }

    private void sendMessage() {
        String text = input.getText().toString().trim();
        if (text.isEmpty()) {
            return;
        }
        if (!online) {
            Toast.makeText(this, "Нет связи с JARVIS", Toast.LENGTH_SHORT).show();
            connect();
            return;
        }
        input.setText("");
        showTyping(true);
        JSONObject payload = new JSONObject();
        try {
            payload.put("text", text);
            payload.put("mode", mode);
        } catch (Exception ignored) {
            return;
        }
        io.execute(() -> {
            try {
                rpc("send_message", payload);
            } catch (Exception error) {
                ui.post(() -> {
                    showTyping(false);
                    input.setText(text);
                    append("error", "Не отправлено: " + friendly(error));
                });
            }
        });
    }

    private void cycleMode() {
        int index = 0;
        for (int i = 0; i < MODES.length; i++) {
            if (MODES[i].equals(mode)) {
                index = i;
                break;
            }
        }
        String next = MODES[(index + 1) % MODES.length];
        setMode(next, true);
        io.execute(() -> {
            try {
                JSONObject payload = new JSONObject();
                payload.put("mode", next);
                rpc("set_mode", payload);
            } catch (Exception ignored) {
                /* режим применится при следующем poll */
            }
        });
    }

    private void setMode(String value, boolean persist) {
        String candidate = value == null ? "" : value.toLowerCase(Locale.US);
        for (String allowed : MODES) {
            if (allowed.equals(candidate)) {
                mode = candidate;
                break;
            }
        }
        updateModeChip();
        if (persist) {
            prefs().edit().putString(KEY_MODE, mode).apply();
        }
    }

    private void updateModeChip() {
        modeChip.setText(mode.toUpperCase(Locale.US));
    }

    private void showTasks() {
        if (tasks == null || tasks.length() == 0) {
            Toast.makeText(this, "Задач нет", Toast.LENGTH_SHORT).show();
            return;
        }
        final CharSequence[] labels = new CharSequence[tasks.length()];
        for (int i = 0; i < tasks.length(); i++) {
            JSONObject task = tasks.optJSONObject(i);
            if (task == null) {
                labels[i] = "?";
                continue;
            }
            String status = task.optString("status", "?");
            String icon = "done".equals(status) ? "✅"
                    : "failed".equals(status) ? "❌"
                    : "running".equals(status) ? "⚙"
                    : "pending".equals(status) ? "⏳" : "•";
            labels[i] = icon + " " + task.optString("title", "Задача")
                    + " · " + status;
        }
        new AlertDialog.Builder(this)
                .setTitle("Задачи")
                .setItems(labels, (dialog, which) -> {
                    JSONObject task = tasks.optJSONObject(which);
                    if (task != null) {
                        showTaskDetails(task);
                    }
                })
                .setNegativeButton("Закрыть", null)
                .show();
    }

    private void showTaskDetails(JSONObject task) {
        String status = task.optString("status", "");
        StringBuilder body = new StringBuilder();
        body.append("Статус: ").append(status).append("\n");
        String result = task.optString("result", "");
        String error = task.optString("error", "");
        if (!result.isEmpty()) {
            body.append("\n").append(result);
        }
        if (!error.isEmpty()) {
            body.append("\nОшибка: ").append(error);
        }
        boolean active = "pending".equals(status) || "running".equals(status);
        AlertDialog.Builder builder = new AlertDialog.Builder(this)
                .setTitle(task.optString("title", "Задача"))
                .setMessage(body.toString())
                .setNegativeButton("Закрыть", null);
        if (active) {
            builder.setPositiveButton("Отменить", (dialog, which) ->
                    cancelTask(task.optString("id", "")));
        }
        builder.show();
    }

    private void cancelTask(String id) {
        if (id.isEmpty()) {
            return;
        }
        io.execute(() -> {
            try {
                JSONObject payload = new JSONObject();
                payload.put("id", id);
                rpc("cancel_task", payload);
                ui.post(() -> Toast.makeText(this, "Задача отменена",
                        Toast.LENGTH_SHORT).show());
            } catch (Exception error) {
                ui.post(() -> Toast.makeText(this,
                        "Не удалось отменить: " + friendly(error),
                        Toast.LENGTH_LONG).show());
            }
        });
    }

    private void showJournal() {
        io.execute(() -> {
            try {
                JSONObject payload = new JSONObject();
                payload.put("lines", 300);
                JSONObject data = rpc("get_journal", payload);
                String text = data.optString("text", "Журнал пуст.");
                ui.post(() -> showTextDialog("Журнал", text));
            } catch (Exception error) {
                ui.post(() -> Toast.makeText(this,
                        friendly(error), Toast.LENGTH_LONG).show());
            }
        });
    }

    private void showTextDialog(String title, String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(11);
        view.setTextColor(TEXT);
        view.setTypeface(Typeface.MONOSPACE);
        view.setTextIsSelectable(true);
        view.setPadding(dp(14), dp(12), dp(14), dp(12));
        ScrollView scroll = new ScrollView(this);
        scroll.addView(view);
        new AlertDialog.Builder(this)
                .setTitle(title)
                .setView(scroll)
                .setPositiveButton("Закрыть", null)
                .show();
    }

    private void runDoctor() {
        io.execute(() -> {
            try {
                rpc("run_doctor", new JSONObject());
                ui.post(() -> Toast.makeText(this,
                        "Диагностика запущена — отчёт придёт в чат",
                        Toast.LENGTH_LONG).show());
            } catch (Exception error) {
                ui.post(() -> Toast.makeText(this,
                        friendly(error), Toast.LENGTH_LONG).show());
            }
        });
    }

    private void showSettings() {
        if (settingsDialog != null) {
            settingsDialog.dismiss();
            settingsDialog = null;
        }
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(20);
        layout.setPadding(pad, pad, pad, 0);

        TextView hint = new TextView(this);
        hint.setText("Отсканируйте QR камерой телефона "
                + "(JARVIS на ПК → Настройки → Показать QR для телефона) "
                + "или укажите адрес и токен вручную. Подходит адрес "
                + "туннеля (https://…) или ПК в домашней Wi-Fi.");
        hint.setTextSize(12);
        hint.setTextColor(MUTED);
        layout.addView(hint);

        TextView scanLink = new TextView(this);
        scanLink.setText("📷 Сканировать QR камерой");
        scanLink.setTextColor(ACCENT);
        scanLink.setTextSize(14);
        scanLink.setTypeface(Typeface.DEFAULT_BOLD);
        scanLink.setPadding(0, dp(16), 0, dp(4));
        scanLink.setOnClickListener(v -> {
            if (settingsDialog != null) {
                settingsDialog.dismiss();
                settingsDialog = null;
            }
            startActivityForResult(
                    new Intent(this, QrScanActivity.class), REQ_SCAN);
        });
        layout.addView(scanLink);

        EditText urlInput = new EditText(this);
        urlInput.setHint("https://abc.trycloudflare.com");
        urlInput.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        urlInput.setText(prefs().getString(KEY_URL, ""));
        layout.addView(urlInput);

        EditText tokenInput = new EditText(this);
        tokenInput.setHint("Токен доступа");
        tokenInput.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        tokenInput.setText(prefs().getString(KEY_TOKEN, ""));
        layout.addView(tokenInput);

        TextView pasteLink = new TextView(this);
        pasteLink.setText("Вставить ссылку подключения");
        pasteLink.setTextColor(ACCENT);
        pasteLink.setTextSize(13);
        pasteLink.setPadding(0, dp(14), 0, dp(4));
        pasteLink.setOnClickListener(v -> {
            String[] pair = PairLink.parseText(clipboardText());
            if (pair == null) {
                Toast.makeText(this,
                        "В буфере нет ссылки jarvis://pair?… "
                                + "или адреса с ?token=",
                        Toast.LENGTH_LONG).show();
                return;
            }
            urlInput.setText(pair[0]);
            tokenInput.setText(pair[1]);
            Toast.makeText(this, "Ссылка подставлена — нажмите «Подключить»",
                    Toast.LENGTH_SHORT).show();
        });
        layout.addView(pasteLink);

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("JARVIS Remote — подключение")
                .setView(layout)
                .setPositiveButton("Подключить", (which, what) -> {
                    String rawUrl = urlInput.getText().toString().trim();
                    String value = tokenInput.getText().toString().trim();
                    // Пользователь мог вставить в поле адреса всю ссылку
                    // jarvis://pair?… — разбираем её целиком, включая
                    // запасной адрес и rendezvous.
                    String fallback = "";
                    String rdvUrl = "";
                    String rdvTopic = "";
                    String[] pasted = PairLink.parseText(rawUrl);
                    if (pasted != null) {
                        rawUrl = pasted[PairLink.URL];
                        value = pasted[PairLink.TOKEN];
                        fallback = pasted[PairLink.FALLBACK];
                        rdvUrl = pasted[PairLink.RDV_URL];
                        rdvTopic = pasted[PairLink.RDV_TOPIC];
                    }
                    String url = PairLink.normalizeBase(rawUrl);
                    if (url.isEmpty() || value.isEmpty()) {
                        Toast.makeText(this, "Введите адрес и токен",
                                Toast.LENGTH_SHORT).show();
                        return;
                    }
                    if (url.startsWith("http://")) {
                        Toast.makeText(this,
                                "HTTP без шифрования. Используйте только "
                                        + "в доверенной домашней Wi-Fi сети.",
                                Toast.LENGTH_LONG).show();
                    }
                    android.content.SharedPreferences.Editor editor =
                            prefs().edit()
                                    .putString(KEY_URL, url)
                                    .putString(KEY_TOKEN, value);
                    if (pasted != null) {
                        editor.putString(KEY_FALLBACK, fallback)
                                .putString(KEY_RDV_URL, rdvUrl)
                                .putString(KEY_RDV_TOPIC, rdvTopic);
                    } else {
                        editor.remove(KEY_FALLBACK)
                                .remove(KEY_RDV_URL)
                                .remove(KEY_RDV_TOPIC);
                    }
                    editor.apply();
                    fallbackBase = PairLink.normalizeBase(fallback);
                    connect();
                })
                .setNegativeButton("Отмена", null)
                .create();
        settingsDialog = dialog;
        dialog.show();
    }

    @Override
    protected void onActivityResult(
            int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_SCAN || resultCode != RESULT_OK
                || data == null) {
            return;
        }
        handleScannedText(data.getStringExtra(EXTRA_SCAN_TEXT));
    }

    private void toggleRecording() {
        if (recording) {
            stopRecording();
        } else {
            startRecording();
        }
    }

    private void startRecording() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions();
            return;
        }
        try {
            recordingFile = new File(getCacheDir(), "voice.m4a");
            if (recordingFile.exists() && !recordingFile.delete()) {
                return;
            }
            if (Build.VERSION.SDK_INT >= 31) {
                recorder = new MediaRecorder(this);
            } else {
                recorder = new MediaRecorder();
            }
            recorder.setAudioSource(MediaRecorder.AudioSource.MIC);
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
            recorder.setAudioSamplingRate(16000);
            recorder.setAudioChannels(1);
            recorder.setAudioEncodingBitRate(32000);
            recorder.setOutputFile(recordingFile.getAbsolutePath());
            recorder.prepare();
            recorder.start();
            recording = true;
            micButton.setText("■");
            micButton.setTextColor(RED);
            flashActivity("🎙 Запись… нажмите ■ чтобы отправить");
        } catch (Exception error) {
            releaseRecorder();
            Toast.makeText(this, "Микрофон: " + error.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    private void stopRecording() {
        try {
            recorder.stop();
        } catch (RuntimeException error) {
            releaseRecorder();
            Toast.makeText(this, "Слишком короткая запись",
                    Toast.LENGTH_SHORT).show();
            return;
        }
        releaseRecorder();
        if (recordingFile != null && recordingFile.length() > 1000) {
            uploadVoice(recordingFile);
        } else {
            Toast.makeText(this, "Запись пустая", Toast.LENGTH_SHORT).show();
        }
    }

    private void releaseRecorder() {
        recording = false;
        micButton.setText("🎤");
        micButton.setTextColor(TEXT);
        if (recorder != null) {
            try {
                recorder.reset();
            } catch (Exception ignored) {
                /* уже остановлен */
            }
            try {
                recorder.release();
            } catch (Exception ignored) {
                /* уже освобождён */
            }
            recorder = null;
        }
    }

    private void uploadVoice(File file) {
        flashActivity("🎙 Распознавание…");
        io.execute(() -> {
            HttpURLConnection conn = null;
            try {
                byte[] audio = readFile(file);
                conn = (HttpURLConnection) new URL(base + "/stt")
                        .openConnection();
                conn.setConnectTimeout(10000);
                conn.setReadTimeout(60000);
                conn.setRequestMethod("POST");
                conn.setDoOutput(true);
                conn.setFixedLengthStreamingMode(audio.length);
                conn.setRequestProperty("Content-Type", "audio/mp4");
                conn.setRequestProperty("Authorization", "Bearer " + token);
                try (OutputStream out = conn.getOutputStream()) {
                    out.write(audio);
                }
                int code = conn.getResponseCode();
                InputStream stream = code >= 400
                        ? conn.getErrorStream() : conn.getInputStream();
                String body = readAll(stream);
                JSONObject data = new JSONObject(body);
                if (code >= 400 || !data.optBoolean("ok")) {
                    throw new IOException(data.optString("error",
                            "STT недоступен"));
                }
                String text = data.optString("text", "").trim();
                ui.post(() -> {
                    if (text.isEmpty()) {
                        Toast.makeText(this, "Речь не распознана",
                                Toast.LENGTH_SHORT).show();
                        return;
                    }
                    input.setText(text);
                    input.setSelection(text.length());
                    Toast.makeText(this, "Распознано — можно отправить",
                            Toast.LENGTH_SHORT).show();
                });
            } catch (Exception error) {
                ui.post(() -> Toast.makeText(this,
                        "STT: " + friendly(error), Toast.LENGTH_LONG).show());
            } finally {
                if (conn != null) {
                    conn.disconnect();
                }
                ui.postDelayed(hideTyping, 800L);
            }
        });
    }

    private byte[] readFile(File file) throws IOException {
        try (FileInputStream in = new FileInputStream(file);
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) > 0) {
                out.write(buffer, 0, read);
            }
            return out.toByteArray();
        }
    }

    private String readAll(InputStream stream) throws IOException {
        if (stream == null) {
            return "";
        }
        try (InputStream in = stream;
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) > 0) {
                out.write(buffer, 0, read);
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private JSONObject rpc(String method, JSONObject payload) throws Exception {
        return rpcAt(base, method, payload);
    }

    private JSONObject rpcAt(
            String server, String method, JSONObject payload)
            throws Exception {
        server = PairLink.normalizeBase(server);
        String auth = token;
        if (server.isEmpty() || auth.isEmpty()) {
            throw new IOException("не задан адрес или токен");
        }
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(server + "/rpc")
                    .openConnection();
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(60000);
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type",
                    "application/json; charset=utf-8");
            conn.setRequestProperty("Authorization", "Bearer " + auth);

            JSONObject body = new JSONObject();
            body.put("type", "jarvis_request");
            body.put("id", UUID.randomUUID().toString());
            body.put("method", method);
            body.put("payload", payload == null ? new JSONObject() : payload);

            byte[] data = body.toString().getBytes(StandardCharsets.UTF_8);
            conn.setFixedLengthStreamingMode(data.length);
            try (OutputStream out = conn.getOutputStream()) {
                out.write(data);
            }

            int code = conn.getResponseCode();
            InputStream stream = code >= 400
                    ? conn.getErrorStream() : conn.getInputStream();
            String text = readAll(stream);
            if (code == 401 || code == 403) {
                throw new UnauthorizedException("доступ запрещён");
            }
            JSONObject response;
            try {
                response = new JSONObject(text);
            } catch (Exception error) {
                throw new IOException("некорректный ответ сервера");
            }
            if (!response.optBoolean("ok")) {
                throw new IOException(response.optString("error",
                        "ошибка JARVIS"));
            }
            JSONObject result = response.optJSONObject("data");
            return result == null ? new JSONObject() : result;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    @Override
    public void onBackPressed() {
        if (recording) {
            stopRecording();
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        alive = false;
        polling = false;
        generation++;
        ui.removeCallbacksAndMessages(null);
        io.shutdownNow();
        if (recording) {
            releaseRecorder();
        }
        if (networkCallback != null) {
            try {
                ConnectivityManager manager =
                        (ConnectivityManager) getSystemService(
                                Context.CONNECTIVITY_SERVICE);
                if (manager != null) {
                    manager.unregisterNetworkCallback(networkCallback);
                }
            } catch (Exception ignored) {
                // Служба связи уже перезапущена системой.
            }
            networkCallback = null;
        }
        super.onDestroy();
    }

    private static class Message {
        String role;
        String text;
        boolean partial;

        Message(String role, String text, boolean partial) {
            this.role = role;
            this.text = text;
            this.partial = partial;
        }
    }

    private static class UnauthorizedException extends IOException {
        UnauthorizedException(String message) {
            super(message);
        }
    }

    private class ChatAdapter extends BaseAdapter {

        @Override
        public int getCount() {
            return messages.size();
        }

        @Override
        public Object getItem(int position) {
            return messages.get(position);
        }

        @Override
        public long getItemId(int position) {
            return position;
        }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            Message message = messages.get(position);
            LinearLayout row = new LinearLayout(MainActivity.this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setPadding(dp(10), dp(4), dp(10), dp(4));

            TextView bubble = new TextView(MainActivity.this);
            bubble.setText(message.text);
            bubble.setTextIsSelectable(true);
            bubble.setLineSpacing(dp(2), 1f);
            int maxWidth = (int) (getResources().getDisplayMetrics()
                    .widthPixels * 0.84f);

            if ("user".equals(message.role)) {
                row.setGravity(Gravity.END);
                bubble.setTextColor(Color.WHITE);
                bubble.setTextSize(15);
                bubble.setBackground(rounded(BLUE, 16));
                bubble.setPadding(dp(14), dp(9), dp(14), dp(9));
                bubble.setMaxWidth(maxWidth);
            } else if ("assistant".equals(message.role)) {
                row.setGravity(Gravity.START);
                bubble.setTextColor(TEXT);
                bubble.setTextSize(15);
                bubble.setBackground(outlined(PANEL_ALT, BORDER, 16));
                bubble.setPadding(dp(14), dp(9), dp(14), dp(9));
                bubble.setMaxWidth(maxWidth);
                if (message.partial) {
                    bubble.setAlpha(0.85f);
                }
            } else if ("error".equals(message.role)) {
                row.setGravity(Gravity.START);
                bubble.setTextColor(Color.parseColor("#ffb0b0"));
                bubble.setTextSize(13);
                bubble.setBackground(outlined(Color.parseColor("#2a1018"),
                        RED, 12));
                bubble.setPadding(dp(12), dp(8), dp(12), dp(8));
                bubble.setMaxWidth(maxWidth);
            } else {
                row.setGravity(Gravity.CENTER);
                bubble.setTextColor(MUTED);
                bubble.setTextSize(12);
                bubble.setGravity(Gravity.CENTER);
                bubble.setBackgroundColor(Color.TRANSPARENT);
                bubble.setPadding(dp(14), dp(6), dp(14), dp(6));
                bubble.setMaxWidth((int) (getResources()
                        .getDisplayMetrics().widthPixels * 0.94f));
            }

            row.addView(bubble);
            return row;
        }
    }
}
