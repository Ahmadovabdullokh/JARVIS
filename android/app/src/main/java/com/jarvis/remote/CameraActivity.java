package com.jarvis.remote;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.Lifecycle;
import androidx.lifecycle.LifecycleOwner;
import androidx.lifecycle.LifecycleRegistry;

import com.google.common.util.concurrent.ListenableFuture;

import org.json.JSONObject;

import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Экран камеры телефона: превью, объектив, фонарик, качество и запуск
 * трансляции на ПК через {@link CameraStreamService}.
 */
public class CameraActivity extends Activity implements LifecycleOwner {

    private static final int REQ_CAMERA = 2001;
    private static final int[][] RESOLUTIONS = {
            {640, 480},
            {1280, 720},
            {1920, 1080},
    };
    private static final int[] FPS_VALUES = {5, 10, 15, 20, 30};

    private final LifecycleRegistry lifecycle = new LifecycleRegistry(this);
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();

    private LinearLayout root;
    private android.widget.ScrollView scroll;
    private PreviewView previewView;
    private TextView previewHint;
    private TextView liveChip;
    private TextView pcStatus;
    private TextView uploadStatus;
    private TextView lensChip;
    private TextView torchChip;
    private TextView resChip;
    private TextView fpsChip;
    private TextView startButton;

    private ProcessCameraProvider provider;
    private Preview preview;
    private Camera boundCamera;
    private int boundLens = -1;

    private int lens = CameraStreamService.LENS_BACK;
    private int fps = 30;
    private int resolutionIndex = 0;
    private boolean torch = false;
    private boolean alive = true;
    private long lastPcPoll = 0L;
    private long lensSwitchAt = 0L;

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (!alive) {
                return;
            }
            refreshLocalState();
            syncLens();
            pollPc();
            ui.postDelayed(this, 700L);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        buildLayout();
        setContentView(scroll);
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_CREATE);
        lens = CameraStreamService.isRunning()
                ? CameraStreamService.getLens() : lens;
        if (hasCameraPermission()) {
            ensurePreview();
        } else {
            requestPermissions(
                    new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_START);
    }

    @Override
    protected void onResume() {
        super.onResume();
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_RESUME);
        alive = true;
        ui.post(tick);
    }

    @Override
    protected void onPause() {
        alive = false;
        ui.removeCallbacks(tick);
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_PAUSE);
        super.onPause();
    }

    @Override
    protected void onStop() {
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_STOP);
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        alive = false;
        ui.removeCallbacksAndMessages(null);
        io.shutdownNow();
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY);
        getWindow().clearFlags(
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        super.onDestroy();
    }

    @Override
    public Lifecycle getLifecycle() {
        return lifecycle;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode,
                                           String[] permissions,
                                           int[] grantResults) {
        super.onRequestPermissionsResult(
                requestCode, permissions, grantResults);
        if (requestCode != REQ_CAMERA) {
            return;
        }
        if (grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            ensurePreview();
        } else {
            showPreviewHint("Нет доступа к камере");
        }
    }

    // ------------------------------------------------------------------
    // Интерфейс
    // ------------------------------------------------------------------

    private void buildLayout() {
        scroll = new android.widget.ScrollView(this);
        scroll.setBackgroundColor(Hud.BG);
        scroll.setFillViewport(true);
        scroll.setFitsSystemWindows(true);

        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Hud.BG);
        scroll.addView(root, new android.widget.FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.setPadding(Hud.dp(this, 10), Hud.dp(this, 12),
                Hud.dp(this, 14), Hud.dp(this, 10));
        top.setBackgroundColor(Hud.PANEL);

        TextView back = new TextView(this);
        back.setText("‹");
        back.setTextSize(26);
        back.setTextColor(Hud.TEXT);
        back.setGravity(Gravity.CENTER);
        back.setOnClickListener(v -> finish());
        top.addView(back, new LinearLayout.LayoutParams(
                Hud.dp(this, 40), Hud.dp(this, 40)));

        TextView title = new TextView(this);
        title.setText("КАМЕРА");
        title.setTextColor(Hud.ACCENT);
        title.setTextSize(16);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setLetterSpacing(0.14f);
        title.setPadding(Hud.dp(this, 6), 0, 0, 0);
        top.addView(title, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        liveChip = new TextView(this);
        liveChip.setText("OFF");
        liveChip.setTextSize(11);
        liveChip.setTypeface(Typeface.DEFAULT_BOLD);
        liveChip.setTextColor(Hud.MUTED);
        liveChip.setGravity(Gravity.CENTER);
        liveChip.setPadding(Hud.dp(this, 10), Hud.dp(this, 5),
                Hud.dp(this, 10), Hud.dp(this, 5));
        liveChip.setBackground(Hud.outlined(this, Hud.BG, Hud.BORDER, 8));
        top.addView(liveChip);

        root.addView(top, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        previewView = new PreviewView(this);
        previewView.setScaleType(PreviewView.ScaleType.FILL_CENTER);
        previewView.setBackgroundColor(Hud.PANEL);

        previewHint = new TextView(this);
        previewHint.setText("Превью запускается…");
        previewHint.setTextColor(Hud.MUTED);
        previewHint.setTextSize(13);
        previewHint.setGravity(Gravity.CENTER);
        previewHint.setPadding(Hud.dp(this, 20), Hud.dp(this, 20),
                Hud.dp(this, 20), Hud.dp(this, 20));

        android.widget.FrameLayout frame = new android.widget.FrameLayout(this);
        frame.setBackgroundColor(Hud.PANEL);
        frame.addView(previewView, new android.widget.FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        frame.addView(previewHint, new android.widget.FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        int frameHeight = Math.min(
                Math.round(
                        getResources().getDisplayMetrics().widthPixels
                                * 4f / 3f),
                Math.round(
                        getResources().getDisplayMetrics().heightPixels
                                * 0.72f));
        root.addView(frame, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, frameHeight));

        LinearLayout info = new LinearLayout(this);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(Hud.dp(this, 16), Hud.dp(this, 10),
                Hud.dp(this, 16), Hud.dp(this, 4));

        pcStatus = new TextView(this);
        pcStatus.setText("ПК: проверка…");
        pcStatus.setTextColor(Hud.MUTED);
        pcStatus.setTextSize(12);
        info.addView(pcStatus);

        uploadStatus = new TextView(this);
        uploadStatus.setText("Отправлено 0 · ошибок 0");
        uploadStatus.setTextColor(Hud.MUTED);
        uploadStatus.setTextSize(11);
        uploadStatus.setPadding(0, Hud.dp(this, 3), 0, 0);
        info.addView(uploadStatus);
        root.addView(info);

        LinearLayout controls = new LinearLayout(this);
        controls.setOrientation(LinearLayout.VERTICAL);
        controls.setPadding(Hud.dp(this, 16), Hud.dp(this, 6),
                Hud.dp(this, 16), Hud.dp(this, 16));

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);

        lensChip = chip("ОБЪЕКТИВ: ОСНОВНАЯ");
        lensChip.setOnClickListener(v -> switchLens());
        row.addView(lensChip, weightParams());

        torchChip = chip("ФОНАРИК");
        torchChip.setOnClickListener(v -> toggleTorch());
        row.addView(torchChip, weightParams());
        controls.addView(row);

        LinearLayout row2 = new LinearLayout(this);
        row2.setOrientation(LinearLayout.HORIZONTAL);
        row2.setPadding(0, Hud.dp(this, 8), 0, 0);

        resChip = chip("480p");
        resChip.setOnClickListener(v -> cycleResolution());
        row2.addView(resChip, weightParams());

        fpsChip = chip("10 FPS");
        fpsChip.setOnClickListener(v -> cycleFps());
        row2.addView(fpsChip, weightParams());
        controls.addView(row2);

        LinearLayout row3 = new LinearLayout(this);
        row3.setOrientation(LinearLayout.HORIZONTAL);
        row3.setPadding(0, Hud.dp(this, 8), 0, 0);
        TextView visionChip = chip("ЧТО ВИДНО?");
        visionChip.setOnClickListener(v -> askCamera());
        row3.addView(visionChip, weightParams());
        controls.addView(row3);

        startButton = new TextView(this);
        startButton.setText("Начать трансляцию");
        startButton.setTextSize(15);
        startButton.setTypeface(Typeface.DEFAULT_BOLD);
        startButton.setTextColor(Hud.BG);
        startButton.setGravity(Gravity.CENTER);
        startButton.setBackground(Hud.rounded(this, Hud.ACCENT, 14));
        startButton.setOnClickListener(v -> toggleStreaming());
        LinearLayout.LayoutParams startParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Hud.dp(this, 52));
        startParams.topMargin = Hud.dp(this, 12);
        controls.addView(startButton, startParams);

        TextView hint = new TextView(this);
        hint.setText("Кадры идут на ПК: HUD, жесты и «что видно камере». "
                + "Экран можно выключить — служба продолжит работу.");
        hint.setTextColor(Hud.MUTED);
        hint.setTextSize(10);
        hint.setPadding(0, Hud.dp(this, 10), 0, 0);
        controls.addView(hint);

        root.addView(controls, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        updateChips();
    }

    private TextView chip(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(11);
        view.setTypeface(Typeface.DEFAULT_BOLD);
        view.setTextColor(Hud.ACCENT);
        view.setGravity(Gravity.CENTER);
        view.setPadding(Hud.dp(this, 8), Hud.dp(this, 9),
                Hud.dp(this, 8), Hud.dp(this, 9));
        view.setBackground(Hud.outlined(this, Hud.PANEL_ALT, Hud.BORDER, 10));
        return view;
    }

    private LinearLayout.LayoutParams weightParams() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        params.setMargins(Hud.dp(this, 3), 0, Hud.dp(this, 3), 0);
        return params;
    }

    private void updateChips() {
        lensChip.setText(lens == CameraStreamService.LENS_FRONT
                ? "ОБЪЕКТИВ: ФРОНТ" : "ОБЪЕКТИВ: ОСНОВНАЯ");
        torchChip.setText(torch ? "ФОНАРИК: ВКЛ" : "ФОНАРИК");
        torchChip.setTextColor(torch ? Hud.WARN : Hud.ACCENT);
        int[] size = RESOLUTIONS[resolutionIndex];
        resChip.setText(
                size[1] >= 1080 ? "1080p"
                        : size[1] >= 720 ? "720p" : "480p");
        fpsChip.setText(fps + " FPS");
    }

    private void showPreviewHint(String text) {
        if (previewHint == null) {
            return;
        }
        previewHint.setText(text);
        previewHint.setVisibility(View.VISIBLE);
    }

    // ------------------------------------------------------------------
    // CameraX: превью в активити
    // ------------------------------------------------------------------

    private boolean hasCameraPermission() {
        return checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void ensurePreview() {
        ListenableFuture<ProcessCameraProvider> future =
                ProcessCameraProvider.getInstance(this);
        future.addListener(() -> {
            try {
                provider = future.get();
                bindPreview();
            } catch (Exception error) {
                showPreviewHint(
                        "Камера недоступна: " + error.getMessage());
            }
        }, ContextCompat.getMainExecutor(this));
    }

    private void bindPreview() {
        if (provider == null || !hasCameraPermission()) {
            return;
        }
        int wanted = CameraStreamService.isRunning()
                ? CameraStreamService.getLens() : lens;
        if (preview != null && boundLens == wanted) {
            return;
        }
        if (preview != null) {
            try {
                provider.unbind(preview);
            } catch (Exception ignored) {
                /* превью уже отвязано */
            }
            preview = null;
        }
        CameraSelector selector = wanted == CameraStreamService.LENS_FRONT
                ? CameraSelector.DEFAULT_FRONT_CAMERA
                : CameraSelector.DEFAULT_BACK_CAMERA;
        try {
            Preview nextPreview = new Preview.Builder().build();
            nextPreview.setSurfaceProvider(
                    previewView.getSurfaceProvider());
            boundCamera = provider.bindToLifecycle(
                    this, selector, nextPreview);
            preview = nextPreview;
            boundLens = wanted;
            lens = wanted;
            updateChips();
            previewHint.setVisibility(View.GONE);
            updateTorchAvailability();
        } catch (Exception error) {
            showPreviewHint("Превью: " + error.getMessage());
        }
    }

    private void unbindPreview() {
        if (provider != null && preview != null) {
            try {
                provider.unbind(preview);
            } catch (Exception ignored) {
                /* уже отвязано */
            }
        }
        preview = null;
        boundCamera = null;
        boundLens = -1;
    }

    private void updateTorchAvailability() {
        boolean available = boundCamera != null
                && boundCamera.getCameraInfo().hasFlashUnit();
        torchChip.setEnabled(available);
        torchChip.setAlpha(available ? 1f : 0.45f);
    }

    private void toggleTorch() {
        if (boundCamera == null
                || !boundCamera.getCameraInfo().hasFlashUnit()) {
            Toast.makeText(this, "Фонарик недоступен",
                    Toast.LENGTH_SHORT).show();
            return;
        }
        torch = !torch;
        try {
            boundCamera.getCameraControl().enableTorch(torch);
        } catch (Exception error) {
            torch = false;
            Toast.makeText(this, "Фонарик: " + error.getMessage(),
                    Toast.LENGTH_SHORT).show();
        }
        updateChips();
    }

    private void switchLens() {
        lens = lens == CameraStreamService.LENS_BACK
                ? CameraStreamService.LENS_FRONT
                : CameraStreamService.LENS_BACK;
        torch = false;
        updateChips();
        lensSwitchAt = SystemClock.elapsedRealtime();
        if (CameraStreamService.isRunning()) {
            // Сначала снимаем превью, иначе CameraX держит два объектива.
            unbindPreview();
            Intent intent = new Intent(this, CameraStreamService.class)
                    .setAction(CameraStreamService.ACTION_SWITCH_LENS);
            startService(intent);
            ui.postDelayed(this::bindPreview, 900L);
        } else {
            bindPreview();
        }
    }

    private void cycleResolution() {
        resolutionIndex = (resolutionIndex + 1) % RESOLUTIONS.length;
        updateChips();
        restartIfRunning();
    }

    private void cycleFps() {
        int index = 0;
        for (int i = 0; i < FPS_VALUES.length; i++) {
            if (FPS_VALUES[i] == fps) {
                index = i;
                break;
            }
        }
        fps = FPS_VALUES[(index + 1) % FPS_VALUES.length];
        updateChips();
        restartIfRunning();
    }

    // ------------------------------------------------------------------
    // Трансляция
    // ------------------------------------------------------------------

    private void toggleStreaming() {
        if (CameraStreamService.isRunning()) {
            Intent intent = new Intent(this, CameraStreamService.class)
                    .setAction(CameraStreamService.ACTION_STOP);
            startService(intent);
            ui.postDelayed(this::refreshLocalState, 300L);
            return;
        }
        if (!hasCameraPermission()) {
            requestPermissions(
                    new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
            return;
        }
        if (!JarvisApi.configured(this)) {
            Toast.makeText(this,
                    "Сначала укажите адрес и токен в настройках",
                    Toast.LENGTH_LONG).show();
            return;
        }
        startStreaming();
    }

    private void startStreaming() {
        int[] size = RESOLUTIONS[resolutionIndex];
        Intent intent = new Intent(this, CameraStreamService.class)
                .setAction(CameraStreamService.ACTION_START)
                .putExtra(CameraStreamService.EXTRA_LENS, lens)
                .putExtra(CameraStreamService.EXTRA_FPS, fps)
                .putExtra(CameraStreamService.EXTRA_WIDTH, size[0])
                .putExtra(CameraStreamService.EXTRA_HEIGHT, size[1]);
        ContextCompat.startForegroundService(this, intent);
        ui.postDelayed(this::refreshLocalState, 500L);
    }

    private void restartIfRunning() {
        if (CameraStreamService.isRunning()) {
            startStreaming();
        }
    }

    private void refreshLocalState() {
        boolean running = CameraStreamService.isRunning();
        liveChip.setText(running ? "LIVE" : "OFF");
        liveChip.setTextColor(running ? Hud.GREEN : Hud.MUTED);
        startButton.setText(running
                ? "Остановить трансляцию" : "Начать трансляцию");
        startButton.setTextColor(running ? Hud.TEXT : Hud.BG);
        startButton.setBackground(Hud.rounded(
                this, running ? Hud.RED : Hud.ACCENT, 14));

        int sent = CameraStreamService.getSentFrames();
        int failed = CameraStreamService.getFailedFrames();
        int delay = CameraStreamService.getLastPostMs();
        float measured = CameraStreamService.getFps();
        String text = String.format(
                Locale.US,
                "Отправлено %d · ошибок %d · %.0f fps · %d мс",
                sent, failed, measured, delay);
        String error = CameraStreamService.getLastError();
        if (!error.isEmpty()) {
            text += "\n" + error;
            uploadStatus.setTextColor(Hud.WARN);
        } else {
            uploadStatus.setTextColor(Hud.MUTED);
        }
        uploadStatus.setText(text);
    }

    private void syncLens() {
        if (!CameraStreamService.isRunning()) {
            return;
        }
        if (SystemClock.elapsedRealtime() - lensSwitchAt < 1200L) {
            return;
        }
        int serviceLens = CameraStreamService.getLens();
        if (serviceLens != lens) {
            lens = serviceLens;
            updateChips();
            unbindPreview();
            bindPreview();
        }
    }

    private void askCamera() {
        Toast.makeText(this, "Смотрю кадр…", Toast.LENGTH_SHORT).show();
        io.execute(() -> {
            try {
                JSONObject data = JarvisApi.rpc(
                        this, "camera_look", new JSONObject());
                String text = data.optString("text", "").trim();
                if (text.isEmpty()) {
                    text = "JARVIS не вернул описание.";
                }
                final String answer = text;
                ui.post(() -> {
                    if (!alive) {
                        return;
                    }
                    new AlertDialog.Builder(this)
                            .setTitle("Что видно в камере")
                            .setMessage(answer)
                            .setPositiveButton("Закрыть", null)
                            .show();
                });
            } catch (Exception error) {
                ui.post(() -> {
                    if (!alive) {
                        return;
                    }
                    Toast.makeText(
                            this,
                            "Vision: " + error.getMessage(),
                            Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    private void pollPc() {
        long now = SystemClock.elapsedRealtime();
        if (now - lastPcPoll < 2000L) {
            return;
        }
        lastPcPoll = now;
        io.execute(() -> {
            try {
                JSONObject data = JarvisApi.rpc(
                        this, "get_camera", new JSONObject());
                JSONObject camera = data.optJSONObject("camera");
                ui.post(() -> applyPcState(camera));
            } catch (Exception error) {
                ui.post(() -> {
                    if (!alive) {
                        return;
                    }
                    pcStatus.setText("ПК: нет связи");
                    pcStatus.setTextColor(Hud.RED);
                });
            }
        });
    }

    private void applyPcState(JSONObject camera) {
        if (!alive || camera == null) {
            return;
        }
        String source = camera.optString("source", "");
        boolean running = camera.optBoolean("running");
        String state = camera.optString("phone_state", "");
        if (!running || !"phone".equals(source)) {
            pcStatus.setText("ПК: камера не переключена на телефон");
            pcStatus.setTextColor(Hud.WARN);
            return;
        }
        if ("live".equals(state)) {
            String size = camera.optInt("width", 0) > 0
                    ? camera.optInt("width") + "x" + camera.optInt("height")
                    : "—";
            int cameraFps = Math.round((float) camera.optDouble("fps", 0));
            String device = camera.optString("phone_device", "");
            pcStatus.setText("ПК: LIVE · " + size + " · " + cameraFps
                    + " fps" + (device.isEmpty() ? "" : " · " + device));
            pcStatus.setTextColor(Hud.GREEN);
        } else if ("stale".equals(state)) {
            pcStatus.setText("ПК: кадры не доходят");
            pcStatus.setTextColor(Hud.RED);
        } else {
            pcStatus.setText("ПК: ожидание кадров");
            pcStatus.setTextColor(Hud.WARN);
        }
    }
}
