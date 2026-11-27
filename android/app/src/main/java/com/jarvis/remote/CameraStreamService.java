package com.jarvis.remote;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.graphics.YuvImage;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Size;

import androidx.annotation.Nullable;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.Lifecycle;
import androidx.lifecycle.LifecycleOwner;
import androidx.lifecycle.LifecycleRegistry;

import com.google.common.util.concurrent.ListenableFuture;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.util.Locale;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Foreground-служба камеры: держит CameraX и отправляет JPEG-кадры на ПК.
 *
 * Служба владеет ImageAnalysis (работает и при выключенном экране),
 * а предпросмотр на экране камеры биндится отдельно к lifecycle
 * активити — CameraX поддерживает несколько LifecycleOwner.
 */
public class CameraStreamService extends Service implements LifecycleOwner {

    static final String ACTION_START = "com.jarvis.remote.CAMERA_START";
    static final String ACTION_STOP = "com.jarvis.remote.CAMERA_STOP";
    static final String ACTION_SWITCH_LENS = "com.jarvis.remote.CAMERA_LENS";

    static final String EXTRA_LENS = "lens";
    static final String EXTRA_FPS = "fps";
    static final String EXTRA_WIDTH = "width";
    static final String EXTRA_HEIGHT = "height";

    static final int LENS_BACK = 0;
    static final int LENS_FRONT = 1;

    private static final String CHANNEL = "jarvis_camera";
    private static final int NOTIFICATION_ID = 43;
    private static final long NOTIFY_INTERVAL_MS = 4000L;
    private static final long MIN_INTERVAL_MS = 66L;
    private static final long MAX_INTERVAL_MS = 250L;
    private static final long SOURCE_RETRY_MIN_MS = 3000L;
    private static final long SOURCE_RETRY_MAX_MS = 30000L;
    private static final long SOURCE_FORCE_INTERVAL_MS = 1500L;

    private static volatile CameraStreamService instance;

    private final LifecycleRegistry lifecycle = new LifecycleRegistry(this);
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService cameraExecutor =
            Executors.newSingleThreadExecutor();
    private final BlockingQueue<Frame> queue = new ArrayBlockingQueue<>(2);

    private ProcessCameraProvider provider;
    private ImageAnalysis analysis;

    private volatile Thread uploadThread;
    private volatile boolean streaming = false;
    private volatile boolean uploading = false;
    private volatile int lens = LENS_BACK;
    private volatile int targetFps = 10;
    private volatile int width = 640;
    private volatile int height = 480;
    private volatile long intervalMs = 100L;
    private volatile int sentFrames = 0;
    private volatile int failedFrames = 0;
    private volatile int lastPostMs = 0;
    private volatile float measuredFps = 0f;
    private volatile String lastError = "";
    private volatile String statusText = "Ожидание";

    private String base = "";
    private String token = "";
    private String deviceName = "android";

    private long lastAnalyzed = 0L;
    private long fpsMark = 0L;
    private int fpsCount = 0;
    private long lastSourceAttempt = 0L;
    private volatile boolean sourceReady = false;
    private volatile long sourceRetryMs = SOURCE_RETRY_MIN_MS;

    private final Runnable notifyTick = new Runnable() {
        @Override
        public void run() {
            if (!streaming) {
                return;
            }
            NotificationManager manager =
                    (NotificationManager) getSystemService(
                            NOTIFICATION_SERVICE);
            if (manager != null) {
                manager.notify(NOTIFICATION_ID, buildNotification());
            }
            handler.postDelayed(this, NOTIFY_INTERVAL_MS);
        }
    };

    // ------------------------------------------------------------------
    // Статическое состояние для экрана камеры
    // ------------------------------------------------------------------

    static boolean isRunning() {
        CameraStreamService service = instance;
        return service != null && service.streaming;
    }

    static int getLens() {
        CameraStreamService service = instance;
        return service == null ? LENS_BACK : service.lens;
    }

    static String getLastError() {
        CameraStreamService service = instance;
        return service == null ? "" : service.lastError;
    }

    static String getStatusText() {
        CameraStreamService service = instance;
        return service == null ? "Остановлено" : service.statusText;
    }

    static int getSentFrames() {
        CameraStreamService service = instance;
        return service == null ? 0 : service.sentFrames;
    }

    static int getFailedFrames() {
        CameraStreamService service = instance;
        return service == null ? 0 : service.failedFrames;
    }

    static int getLastPostMs() {
        CameraStreamService service = instance;
        return service == null ? 0 : service.lastPostMs;
    }

    static float getFps() {
        CameraStreamService service = instance;
        return service == null ? 0f : service.measuredFps;
    }

    // ------------------------------------------------------------------
    // Жизненный цикл службы
    // ------------------------------------------------------------------

    @Override
    public void onCreate() {
        super.onCreate();
        instance = this;
        createChannel();
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_CREATE);
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_START);
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_RESUME);
    }

    @Override
    public int onStartCommand(@Nullable Intent intent, int flags, int startId) {
        String action = intent == null
                ? ACTION_START : intent.getAction();
        if (ACTION_STOP.equals(action)) {
            stopStreaming();
            stopSelf();
            return START_NOT_STICKY;
        }
        if (ACTION_SWITCH_LENS.equals(action)) {
            if (streaming) {
                lens = lens == LENS_BACK ? LENS_FRONT : LENS_BACK;
                // Сначала отпускаем старый объектив: экран камеры успеет
                // отвязать превью, и CameraX не откроет два объектива.
                unbindAnalysis();
                handler.postDelayed(this::rebindAnalysis, 1500L);
                // Зеркало зависит от объектива: сообщаем ПК новый режим.
                sourceReady = false;
                new Thread(() -> ensureSource(true),
                        "JARVIS-CameraSource").start();
                NotificationManager manager =
                        (NotificationManager) getSystemService(
                                NOTIFICATION_SERVICE);
                if (manager != null) {
                    manager.notify(NOTIFICATION_ID, buildNotification());
                }
            }
            return START_STICKY;
        }

        if (intent != null) {
            lens = intent.getIntExtra(EXTRA_LENS, lens) == LENS_FRONT
                    ? LENS_FRONT : LENS_BACK;
            targetFps = clamp(intent.getIntExtra(EXTRA_FPS, targetFps),
                    4, 20);
            width = clamp(intent.getIntExtra(EXTRA_WIDTH, width),
                    320, 1920);
            height = clamp(intent.getIntExtra(EXTRA_HEIGHT, height),
                    240, 1080);
        }
        if (!startForegroundSafely()) {
            stopSelf();
            return START_NOT_STICKY;
        }
        if (!streaming) {
            startStreaming();
        } else {
            intervalMs = Math.max(MIN_INTERVAL_MS,
                    1000L / Math.max(4, targetFps));
            rebindAnalysis();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        boolean wasStreaming = streaming;
        streaming = false;
        uploading = false;
        handler.removeCallbacksAndMessages(null);
        Thread thread = uploadThread;
        if (thread != null) {
            thread.interrupt();
            uploadThread = null;
        }
        queue.clear();
        if (provider != null) {
            try {
                provider.unbindAll();
            } catch (Exception ignored) {
                /* камера уже освобождена */
            }
            provider = null;
        }
        analysis = null;
        cameraExecutor.shutdownNow();
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY);
        instance = null;
        if (wasStreaming) {
            new Thread(this::releaseSource, "JARVIS-CameraRelease").start();
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public Lifecycle getLifecycle() {
        return lifecycle;
    }

    // ------------------------------------------------------------------
    // Запуск и остановка
    // ------------------------------------------------------------------

    private void startStreaming() {
        base = JarvisApi.base(this);
        token = JarvisApi.token(this);
        deviceName = sanitize(Build.MODEL);
        streaming = true;
        uploading = true;
        sentFrames = 0;
        failedFrames = 0;
        lastPostMs = 0;
        measuredFps = 0f;
        lastError = "";
        lastAnalyzed = 0L;
        fpsMark = SystemClock.elapsedRealtime();
        fpsCount = 0;
        lastSourceAttempt = 0L;
        sourceReady = false;
        sourceRetryMs = SOURCE_RETRY_MIN_MS;
        intervalMs = Math.max(
                MIN_INTERVAL_MS, 1000L / Math.max(4, targetFps));
        statusText = "Ожидание ПК";
        queue.clear();
        uploadThread = new Thread(this::uploadLoop, "JARVIS-CameraUpload");
        uploadThread.start();
        bindCamera();
        new Thread(() -> ensureSource(true), "JARVIS-CameraSource").start();
        handler.postDelayed(notifyTick, NOTIFY_INTERVAL_MS);
    }

    private void stopStreaming() {
        if (!streaming) {
            return;
        }
        streaming = false;
        uploading = false;
        handler.removeCallbacks(notifyTick);
        Thread thread = uploadThread;
        if (thread != null) {
            thread.interrupt();
            uploadThread = null;
        }
        queue.clear();
        unbindAnalysis();
        statusText = "Остановлено";
        // ПК выключает камеру, но только если трансляцию не включили снова.
        // Отдельный поток переживает stopSelf(), поэтому задержка безопасна.
        Thread release = new Thread(() -> {
            try {
                Thread.sleep(700L);
            } catch (InterruptedException ignored) {
                return;
            }
            if (!streaming) {
                releaseSource();
            }
        }, "JARVIS-CameraRelease");
        release.start();
    }

    private boolean startForegroundSafely() {
        try {
            Notification notification = buildNotification();
            if (Build.VERSION.SDK_INT >= 29) {
                startForeground(
                        NOTIFICATION_ID,
                        notification,
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA);
            } else {
                startForeground(NOTIFICATION_ID, notification);
            }
            return true;
        } catch (Exception error) {
            lastError = "foreground: " + error.getMessage();
            return false;
        }
    }

    private void ensureSource(boolean force) {
        long now = SystemClock.elapsedRealtime();
        long minInterval = force
                ? SOURCE_FORCE_INTERVAL_MS : sourceRetryMs;
        if (now - lastSourceAttempt < minInterval) {
            return;
        }
        lastSourceAttempt = now;
        try {
            JSONObject payload = new JSONObject();
            payload.put("enabled", true);
            payload.put("source", "phone");
            // Фронтальная камера зеркалится, основная — нет.
            payload.put("mirror", lens == LENS_FRONT);
            JarvisApi.rpc(this, "set_camera", payload);
            sourceReady = true;
            sourceRetryMs = SOURCE_RETRY_MIN_MS;
            if (lastError.startsWith("ПК:")) {
                lastError = "";
            }
        } catch (Exception error) {
            sourceReady = false;
            sourceRetryMs = Math.min(
                    SOURCE_RETRY_MAX_MS, sourceRetryMs * 2);
            lastError = "ПК: " + error.getMessage();
        }
    }

    private void releaseSource() {
        try {
            JSONObject payload = new JSONObject();
            payload.put("enabled", false);
            JarvisApi.rpc(this, "set_camera", payload);
        } catch (Exception ignored) {
            /* ПК мог отключиться — остановке это не мешает. */
        }
    }

    // ------------------------------------------------------------------
    // CameraX
    // ------------------------------------------------------------------

    private void bindCamera() {
        ListenableFuture<ProcessCameraProvider> future =
                ProcessCameraProvider.getInstance(this);
        future.addListener(() -> {
            try {
                provider = future.get();
                rebindAnalysis();
            } catch (Exception error) {
                lastError = "камера: " + error.getMessage();
                streaming = false;
                stopSelf();
            }
        }, ContextCompat.getMainExecutor(this));
    }

    private void unbindAnalysis() {
        if (provider != null && analysis != null) {
            try {
                provider.unbind(analysis);
            } catch (Exception ignored) {
                /* уже отвязан */
            }
        }
        analysis = null;
    }

    private void rebindAnalysis() {
        if (provider == null || !streaming) {
            return;
        }
        unbindAnalysis();
        CameraSelector selector = lens == LENS_FRONT
                ? CameraSelector.DEFAULT_FRONT_CAMERA
                : CameraSelector.DEFAULT_BACK_CAMERA;
        try {
            analysis = new ImageAnalysis.Builder()
                    .setBackpressureStrategy(
                            ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setTargetResolution(new Size(width, height))
                    .build();
            analysis.setAnalyzer(cameraExecutor, this::analyze);
            provider.bindToLifecycle(this, selector, analysis);
            statusText = "Трансляция";
        } catch (Exception error) {
            lastError = "камера: " + error.getMessage();
            statusText = "Ошибка камеры";
        }
    }

    private void analyze(ImageProxy image) {
        try {
            if (!streaming) {
                return;
            }
            long now = SystemClock.elapsedRealtime();
            if (now - lastAnalyzed < intervalMs) {
                return;
            }
            lastAnalyzed = now;
            int rotation = image.getImageInfo().getRotationDegrees();
            byte[] jpeg = encodeJpeg(image);
            if (jpeg == null || jpeg.length == 0) {
                return;
            }
            queue.offer(new Frame(jpeg, rotation));
        } catch (Exception error) {
            lastError = "кадр: " + error.getMessage();
        } finally {
            image.close();
        }
    }

    /** YUV_420_888 → NV21 → JPEG (в camera-core 1.3 нет готового JPEG-выхода). */

    private byte[] encodeJpeg(ImageProxy image) {
        int frameWidth = image.getWidth();
        int frameHeight = image.getHeight();
        byte[] nv21 = toNv21(image, frameWidth, frameHeight);
        if (nv21 == null) {
            return null;
        }
        YuvImage yuv = new YuvImage(
                nv21, ImageFormat.NV21, frameWidth, frameHeight, null);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        boolean ok = yuv.compressToJpeg(
                new Rect(0, 0, frameWidth, frameHeight), 78, out);
        return ok ? out.toByteArray() : null;
    }

    private byte[] toNv21(ImageProxy image, int frameWidth, int frameHeight) {
        ImageProxy.PlaneProxy[] planes = image.getPlanes();
        if (planes.length < 3) {
            return null;
        }
        int frameSize = frameWidth * frameHeight;
        byte[] nv21 = new byte[frameSize * 3 / 2];
        ImageProxy.PlaneProxy yPlane = planes[0];
        ImageProxy.PlaneProxy uPlane = planes[1];
        ImageProxy.PlaneProxy vPlane = planes[2];
        ByteBuffer yBuffer = yPlane.getBuffer();
        int yRowStride = yPlane.getRowStride();
        int yPixelStride = yPlane.getPixelStride();
        int position = 0;
        if (yRowStride == frameWidth && yPixelStride == 1) {
            yBuffer.get(nv21, 0, frameSize);
            position = frameSize;
        } else {
            for (int row = 0; row < frameHeight; row++) {
                int rowStart = row * yRowStride;
                for (int col = 0; col < frameWidth; col++) {
                    nv21[position++] = yBuffer.get(
                            rowStart + col * yPixelStride);
                }
            }
        }
        ByteBuffer uBuffer = uPlane.getBuffer();
        ByteBuffer vBuffer = vPlane.getBuffer();
        int uRowStride = uPlane.getRowStride();
        int vRowStride = vPlane.getRowStride();
        int uPixelStride = uPlane.getPixelStride();
        int vPixelStride = vPlane.getPixelStride();
        int uvHeight = frameHeight / 2;
        int uvWidth = frameWidth / 2;
        for (int row = 0; row < uvHeight; row++) {
            int uRowStart = row * uRowStride;
            int vRowStart = row * vRowStride;
            for (int col = 0; col < uvWidth; col++) {
                nv21[position++] = vBuffer.get(
                        vRowStart + col * vPixelStride);
                nv21[position++] = uBuffer.get(
                        uRowStart + col * uPixelStride);
            }
        }
        return nv21;
    }

    // ------------------------------------------------------------------
    // Отправка кадров
    // ------------------------------------------------------------------

    private void uploadLoop() {
        while (uploading) {
            Frame frame;
            try {
                frame = queue.take();
            } catch (InterruptedException stop) {
                return;
            }
            if (!streaming) {
                continue;
            }
            postFrame(frame);
        }
    }

    private void postFrame(Frame frame) {
        long started = SystemClock.elapsedRealtime();
        HttpURLConnection conn = null;
        try {
            URL url = new URL(
                    base + "/camera/frame?rotate=" + frame.rotation
                            + "&mirror=" + (lens == LENS_FRONT ? 1 : 0));
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(15000);
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setFixedLengthStreamingMode(frame.jpeg.length);
            conn.setRequestProperty("Content-Type", "image/jpeg");
            conn.setRequestProperty("Authorization", "Bearer " + token);
            conn.setRequestProperty("X-Jarvis-Device", deviceName);
            try (OutputStream out = conn.getOutputStream()) {
                out.write(frame.jpeg);
            }
            int code = conn.getResponseCode();
            InputStream stream = code >= 400
                    ? conn.getErrorStream() : conn.getInputStream();
            String body = JarvisApi.readAll(stream);
            long elapsed = SystemClock.elapsedRealtime() - started;
            lastPostMs = (int) elapsed;
            if (code >= 400) {
                failedFrames++;
                lastError = "HTTP " + code + ": " + trim(body);
                if (code == 401 || code == 403
                        || code == 409 || code == 503) {
                    // Источник на ПК сбросился (перезапуск, смена
                    // настройки) — повторяем set_camera с backoff.
                    sourceReady = false;
                    ensureSource(false);
                }
            } else {
                sentFrames++;
                if (lastError.startsWith("HTTP") || lastError.startsWith("ПК:")
                        || lastError.startsWith("кадр:")
                        || lastError.startsWith("сеть:")) {
                    lastError = "";
                }
                fpsCount++;
                long span = SystemClock.elapsedRealtime() - fpsMark;
                if (span >= 1000L) {
                    measuredFps = fpsCount * 1000f / span;
                    fpsCount = 0;
                    fpsMark = SystemClock.elapsedRealtime();
                }
            }
            adapt(elapsed);
        } catch (Exception error) {
            failedFrames++;
            sourceReady = false;
            lastError = "сеть: " + error.getClass().getSimpleName()
                    + ": " + error.getMessage();
            ensureSource(false);
        }
    }

    private void adapt(long elapsed) {
        long target = intervalMs;
        if (elapsed > 300L) {
            target = Math.min(MAX_INTERVAL_MS, target + 20L);
        } else if (elapsed < 90L) {
            long floor = Math.max(
                    MIN_INTERVAL_MS, 1000L / Math.max(4, targetFps));
            target = Math.max(floor, target - 10L);
        }
        intervalMs = target;
    }

    // ------------------------------------------------------------------
    // Уведомление
    // ------------------------------------------------------------------

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL,
                "JARVIS камера",
                NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("Трансляция камеры телефона на ПК");
        NotificationManager manager =
                (NotificationManager) getSystemService(
                        NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification() {
        Intent open = new Intent(this, CameraActivity.class);
        PendingIntent content = PendingIntent.getActivity(
                this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE);
        Intent stop = new Intent(this, CameraStreamService.class)
                .setAction(ACTION_STOP);
        PendingIntent stopPending = PendingIntent.getService(
                this, 1, stop,
                PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE);
        Intent switchLens = new Intent(this, CameraStreamService.class)
                .setAction(ACTION_SWITCH_LENS);
        PendingIntent lensPending = PendingIntent.getService(
                this, 2, switchLens,
                PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE);

        Notification.Builder builder =
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                        ? new Notification.Builder(this, CHANNEL)
                        : new Notification.Builder(this);
        return builder
                .setContentTitle("J.A.R.V.I.S. — камера")
                .setContentText(notificationText())
                .setSmallIcon(android.R.drawable.ic_menu_camera)
                .setContentIntent(content)
                .setOngoing(true)
                .addAction(0, "Объектив", lensPending)
                .addAction(0, "Стоп", stopPending)
                .build();
    }

    private String notificationText() {
        if (!lastError.isEmpty()) {
            return "Ошибка: " + trim(lastError);
        }
        return String.format(
                Locale.US,
                "→ ПК · %.0f fps · %s",
                measuredFps,
                lens == LENS_FRONT ? "фронтальная" : "основная");
    }

    private static String sanitize(String value) {
        String text = value == null ? "" : value.trim();
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < text.length() && out.length() < 40; i++) {
            char symbol = text.charAt(i);
            boolean allowed = (symbol >= 'a' && symbol <= 'z')
                    || (symbol >= 'A' && symbol <= 'Z')
                    || (symbol >= '0' && symbol <= '9')
                    || symbol == ' ' || symbol == '.' || symbol == '_'
                    || symbol == '-';
            out.append(allowed ? symbol : '_');
        }
        return out.length() == 0 ? "android" : out.toString();
    }

    private static String trim(String value) {
        String text = value == null ? "" : value.trim();
        return text.length() > 120 ? text.substring(0, 120) : text;
    }

    private static int clamp(int value, int minimum, int maximum) {
        return Math.max(minimum, Math.min(maximum, value));
    }

    private static final class Frame {
        final byte[] jpeg;
        final int rotation;

        Frame(byte[] jpeg, int rotation) {
            this.jpeg = jpeg;
            this.rotation = rotation;
        }
    }
}
