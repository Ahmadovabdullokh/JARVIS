package com.jarvis.remote;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Size;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.FocusMeteringAction;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.MeteringPoint;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.Lifecycle;
import androidx.lifecycle.LifecycleOwner;
import androidx.lifecycle.LifecycleRegistry;

import com.google.common.util.concurrent.ListenableFuture;
import com.google.zxing.BarcodeFormat;
import com.google.zxing.BinaryBitmap;
import com.google.zxing.DecodeHintType;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.Result;
import com.google.zxing.common.GlobalHistogramBinarizer;
import com.google.zxing.common.HybridBinarizer;

import java.nio.ByteBuffer;
import java.util.Collections;
import java.util.EnumMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Сканер QR-кода сопряжения: камера телефона читает QR из JARVIS на ПК
 * и возвращает текст ссылки в {@link MainActivity}.
 *
 * Кадры CameraX (YUV_420_888) переводятся в яркость, поворачиваются по
 * ориентации устройства и распознаются ZXing (только QR).
 */
public class QrScanActivity extends Activity implements LifecycleOwner {

    private static final int REQ_CAMERA = 2002;
    private static final long DECODE_INTERVAL_MS = 180L;
    private static final long INVALID_TOAST_MS = 2500L;
    private static final Size TARGET_RESOLUTION =
            new Size(1920, 1080);
    private static final float[] ZOOM_STEPS = {1f, 2f, 3f};

    private static final int BG = Color.parseColor("#03060d");
    private static final int TEXT = Color.parseColor("#cfe8ff");
    private static final int MUTED = Color.parseColor("#6f8ca8");
    private static final int ACCENT = Color.parseColor("#2ee6ff");

    private final LifecycleRegistry lifecycle = new LifecycleRegistry(this);
    private final ExecutorService analysisExecutor =
            Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final MultiFormatReader reader = new MultiFormatReader();
    private final Map<DecodeHintType, Object> hints =
            new EnumMap<>(DecodeHintType.class);

    private PreviewView previewView;
    private TextView hint;
    private TextView torchChip;
    private TextView zoomChip;

    private ProcessCameraProvider provider;
    private Camera camera;
    private ImageAnalysis analysis;
    private boolean torch = false;
    private volatile boolean handled = false;
    private volatile long frames = 0L;
    private volatile long startedAt = 0L;
    private int zoomIndex = 0;
    private long lastDecode = 0L;
    private long lastInvalidToast = 0L;

    private final Runnable statusTick = new Runnable() {
        @Override
        public void run() {
            if (handled) {
                return;
            }
            if (!hasCameraPermission()) {
                ui.postDelayed(this, 1000L);
                return;
            }
            long seen = frames;
            if (seen > 0) {
                hint.setText("Ищу QR… кадров: " + seen
                        + "\nПоднесите телефон ближе; коснитесь экрана, "
                        + "чтобы навести фокус, или увеличьте масштаб.");
            } else if (startedAt > 0 && SystemClock.elapsedRealtime()
                    - startedAt > 4000L) {
                hint.setText("Камера не присылает кадры. Закройте сканер "
                        + "и откройте его снова.");
            }
            ui.postDelayed(this, 1000L);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        hints.put(DecodeHintType.POSSIBLE_FORMATS,
                Collections.singletonList(BarcodeFormat.QR_CODE));
        hints.put(DecodeHintType.TRY_HARDER, Boolean.TRUE);

        buildLayout();
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_CREATE);

        startedAt = SystemClock.elapsedRealtime();
        ui.postDelayed(statusTick, 1000L);

        if (hasCameraPermission()) {
            startCamera();
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
    }

    @Override
    protected void onPause() {
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
        handled = true;
        ui.removeCallbacks(statusTick);
        analysisExecutor.shutdownNow();
        if (provider != null) {
            try {
                provider.unbindAll();
            } catch (Exception ignored) {
                // Камера уже освобождена.
            }
            provider = null;
        }
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY);
        super.onDestroy();
    }

    private void buildLayout() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(BG);

        previewView = new PreviewView(this);
        previewView.setScaleType(PreviewView.ScaleType.FILL_CENTER);
        previewView.setOnTouchListener((view, event) -> {
            if (event.getAction() == MotionEvent.ACTION_UP) {
                focusAt(event.getX(), event.getY());
            }
            return true;
        });
        root.addView(previewView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.setPadding(dp(10), dp(10), dp(10), dp(10));
        top.setBackgroundColor(Color.parseColor("#cc03060d"));

        TextView close = new TextView(this);
        close.setText("✕");
        close.setTextSize(20);
        close.setTextColor(TEXT);
        close.setGravity(Gravity.CENTER);
        close.setOnClickListener(v -> finish());
        top.addView(close, new LinearLayout.LayoutParams(dp(40), dp(40)));

        TextView title = new TextView(this);
        title.setText("QR подключения");
        title.setTextSize(16);
        title.setTextColor(ACCENT);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setGravity(Gravity.CENTER);
        top.addView(title, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        zoomChip = new TextView(this);
        zoomChip.setText("1×");
        zoomChip.setTextSize(15);
        zoomChip.setTextColor(ACCENT);
        zoomChip.setTypeface(Typeface.DEFAULT_BOLD);
        zoomChip.setGravity(Gravity.CENTER);
        zoomChip.setPadding(dp(6), 0, dp(6), 0);
        zoomChip.setOnClickListener(v -> cycleZoom());
        top.addView(zoomChip, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, dp(40)));

        torchChip = new TextView(this);
        torchChip.setText("🔦");
        torchChip.setTextSize(20);
        torchChip.setGravity(Gravity.CENTER);
        torchChip.setOnClickListener(v -> toggleTorch());
        top.addView(torchChip, new LinearLayout.LayoutParams(dp(40), dp(40)));

        root.addView(top, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP));

        LinearLayout bottom = new LinearLayout(this);
        bottom.setOrientation(LinearLayout.VERTICAL);
        bottom.setPadding(dp(16), dp(14), dp(16), dp(24));
        bottom.setBackgroundColor(Color.parseColor("#cc03060d"));

        hint = new TextView(this);
        hint.setText("Наведите камеру на QR-код в JARVIS на ПК.\n"
                + "Настройки → Показать QR для телефона");
        hint.setTextColor(TEXT);
        hint.setTextSize(13);
        hint.setGravity(Gravity.CENTER);
        bottom.addView(hint);

        TextView note = new TextView(this);
        note.setText("QR содержит адрес и токен — никому его не показывайте");
        note.setTextColor(MUTED);
        note.setTextSize(11);
        note.setGravity(Gravity.CENTER);
        note.setPadding(0, dp(6), 0, 0);
        bottom.addView(note);

        root.addView(bottom, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM));

        setContentView(root);
    }

    private void startCamera() {
        ListenableFuture<ProcessCameraProvider> future =
                ProcessCameraProvider.getInstance(this);
        future.addListener(() -> {
            try {
                provider = future.get();
                bindCamera();
            } catch (Exception error) {
                hint.setText("Камера недоступна: " + error.getMessage());
            }
        }, ContextCompat.getMainExecutor(this));
    }

    @SuppressWarnings("deprecation")
    private void bindCamera() {
        if (provider == null || handled) {
            return;
        }
        try {
            Preview preview = new Preview.Builder().build();
            preview.setSurfaceProvider(previewView.getSurfaceProvider());

            analysis = new ImageAnalysis.Builder()
                    .setBackpressureStrategy(
                            ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setTargetResolution(TARGET_RESOLUTION)
                    .build();
            analysis.setAnalyzer(analysisExecutor, this::analyze);

            camera = provider.bindToLifecycle(this,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview, analysis);
            updateTorchChip();
            applyZoom();
            ui.postDelayed(this::focusCenter, 600L);
        } catch (Exception error) {
            hint.setText("Камера недоступна: " + error.getMessage());
        }
    }

    private void toggleTorch() {
        if (camera == null) {
            return;
        }
        try {
            torch = !torch;
            camera.getCameraControl().enableTorch(torch);
            updateTorchChip();
        } catch (Exception error) {
            torch = false;
            updateTorchChip();
        }
    }

    private void updateTorchChip() {
        torchChip.setText(torch ? "🔆" : "🔦");
        torchChip.setAlpha(torch ? 1f : 0.6f);
    }

    private void cycleZoom() {
        zoomIndex = (zoomIndex + 1) % ZOOM_STEPS.length;
        applyZoom();
        focusCenter();
    }

    private void applyZoom() {
        if (camera == null) {
            return;
        }
        float ratio = ZOOM_STEPS[zoomIndex];
        zoomChip.setText(((int) ratio) + "×");
        try {
            camera.getCameraControl().setZoomRatio(ratio);
        } catch (Exception ignored) {
            // Устройство не поддерживает зум — оставляем как есть.
        }
    }

    private void focusCenter() {
        if (camera == null) {
            return;
        }
        try {
            MeteringPoint point = previewView.getMeteringPointFactory()
                    .createPoint(0.5f, 0.5f);
            camera.getCameraControl().startFocusAndMetering(
                    new FocusMeteringAction.Builder(point).build());
        } catch (Exception ignored) {
            // Фокус не поддерживается — камера сама использует AF.
        }
    }

    private void focusAt(float x, float y) {
        if (camera == null) {
            return;
        }
        try {
            MeteringPoint point = previewView.getMeteringPointFactory()
                    .createPoint(x, y);
            camera.getCameraControl().startFocusAndMetering(
                    new FocusMeteringAction.Builder(point).build());
        } catch (Exception ignored) {
            // Фокус не поддерживается — камера сама использует AF.
        }
    }

    private void analyze(ImageProxy image) {
        try {
            if (handled) {
                return;
            }
            frames++;
            long now = SystemClock.elapsedRealtime();
            if (now - lastDecode < DECODE_INTERVAL_MS) {
                return;
            }
            lastDecode = now;

            int degrees = image.getImageInfo().getRotationDegrees();
            Luma luma = luminance(image, degrees);
            if (luma == null) {
                return;
            }
            String text = decode(luma);
            if (text == null) {
                return;
            }
            if (PairLink.parseText(text) == null) {
                showInvalidLink();
                return;
            }
            handled = true;
            ui.post(() -> finishWith(text));
        } finally {
            image.close();
        }
    }

    private String decode(Luma luma) {
        String text = decodeWith(luma, false);
        if (text != null) {
            return text;
        }
        // Гибридный бинаризатор оптимален для камеры, но на экране
        // с бликами иногда помогает глобальный.
        return decodeWith(luma, true);
    }

    private String decodeWith(Luma luma, boolean global) {
        try {
            PlanarYUVLuminanceSource source =
                    new PlanarYUVLuminanceSource(
                            luma.data, luma.width, luma.height,
                            0, 0, luma.width, luma.height, false);
            BinaryBitmap bitmap = new BinaryBitmap(
                    global
                            ? new GlobalHistogramBinarizer(source)
                            : new HybridBinarizer(source));
            Result result = reader.decode(bitmap, hints);
            return result == null ? null : result.getText();
        } catch (Exception error) {
            return null;
        }
    }

    private void showInvalidLink() {
        long now = SystemClock.elapsedRealtime();
        if (now - lastInvalidToast < INVALID_TOAST_MS) {
            return;
        }
        lastInvalidToast = now;
        ui.post(() -> Toast.makeText(this,
                "Это не QR JARVIS. Откройте QR в приложении на ПК.",
                Toast.LENGTH_SHORT).show());
    }

    private void finishWith(String text) {
        Intent out = new Intent();
        out.putExtra(MainActivity.EXTRA_SCAN_TEXT, text);
        setResult(RESULT_OK, out);
        finish();
    }

    // ------------------------------------------------------------------
    // YUV → яркость + поворот
    // ------------------------------------------------------------------

    private static final class Luma {
        final byte[] data;
        final int width;
        final int height;

        Luma(byte[] data, int width, int height) {
            this.data = data;
            this.width = width;
            this.height = height;
        }
    }

    private Luma luminance(ImageProxy image, int degrees) {
        ImageProxy.PlaneProxy[] planes = image.getPlanes();
        if (planes.length == 0) {
            return null;
        }
        int width = image.getWidth();
        int height = image.getHeight();
        if (width <= 0 || height <= 0) {
            return null;
        }
        ImageProxy.PlaneProxy yPlane = planes[0];
        ByteBuffer buffer = yPlane.getBuffer();
        int rowStride = yPlane.getRowStride();
        int pixelStride = yPlane.getPixelStride();

        byte[] gray = new byte[width * height];
        if (rowStride == width && pixelStride == 1) {
            buffer.rewind();
            buffer.get(gray, 0, Math.min(gray.length, buffer.remaining()));
        } else {
            for (int row = 0; row < height; row++) {
                int rowStart = row * rowStride;
                int out = row * width;
                for (int col = 0; col < width; col++) {
                    gray[out + col] = buffer.get(rowStart + col * pixelStride);
                }
            }
        }

        int rotation = ((degrees % 360) + 360) % 360;
        if (rotation == 90 || rotation == 270) {
            return new Luma(rotateQuarter(gray, width, height, rotation),
                    height, width);
        }
        if (rotation == 180) {
            return new Luma(rotateHalf(gray, width, height),
                    width, height);
        }
        return new Luma(gray, width, height);
    }

    private static byte[] rotateQuarter(
            byte[] src, int width, int height, int rotation) {
        byte[] dst = new byte[src.length];
        int newWidth = height;
        if (rotation == 90) {
            // По часовой стрелке.
            for (int y = 0; y < width; y++) {
                for (int x = 0; x < height; x++) {
                    dst[y * newWidth + x] =
                            src[(height - 1 - x) * width + y];
                }
            }
        } else {
            // Против часовой стрелки.
            for (int y = 0; y < width; y++) {
                for (int x = 0; x < height; x++) {
                    dst[y * newWidth + x] =
                            src[x * width + (width - 1 - y)];
                }
            }
        }
        return dst;
    }

    private static byte[] rotateHalf(byte[] src, int width, int height) {
        byte[] dst = new byte[src.length];
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                dst[y * width + x] =
                        src[(height - 1 - y) * width + (width - 1 - x)];
            }
        }
        return dst;
    }

    // ------------------------------------------------------------------
    // Разрешения и утилиты
    // ------------------------------------------------------------------

    private boolean hasCameraPermission() {
        return checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED;
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(
                requestCode, permissions, grantResults);
        if (requestCode != REQ_CAMERA) {
            return;
        }
        if (grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startCamera();
        } else {
            hint.setText("Нет доступа к камере — разрешите его в настройках "
                    + "приложения и откройте сканер снова.");
        }
    }

    @Override
    public void onBackPressed() {
        finish();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    public Lifecycle getLifecycle() {
        return lifecycle;
    }
}
