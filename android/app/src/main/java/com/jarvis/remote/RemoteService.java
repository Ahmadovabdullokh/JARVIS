package com.jarvis.remote;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Foreground-сервис: держит процесс живым, показывает уведомление
 * «JARVIS онлайн» и периодически проверяет /health сервера.
 */
public class RemoteService extends Service {

    private static final String CHANNEL = "jarvis_status";
    private static final int NOTIFICATION_ID = 42;
    private static final long CHECK_INTERVAL_MS = 30_000L;
    private static final long RDV_RETRY_MS = 60_000L;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private volatile boolean online = false;
    private volatile boolean checking = false;
    private volatile long lastRdvAttempt = 0L;

    private final Runnable healthCheck = new Runnable() {
        @Override
        public void run() {
            if (!checking) {
                checking = true;
                new Thread(RemoteService.this::checkHealth,
                        "JARVIS-Health").start();
            }
            handler.postDelayed(this, CHECK_INTERVAL_MS);
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
        startForeground(NOTIFICATION_ID, buildNotification("JARVIS: подключение…"));
        handler.post(healthCheck);
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL,
                    "JARVIS статус",
                    NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("Состояние подключения к JARVIS");
            NotificationManager manager =
                    (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager != null) {
                manager.createNotificationChannel(channel);
            }
        }
    }

    private String serverBase() {
        SharedPreferences prefs = getSharedPreferences("jarvis_remote", Context.MODE_PRIVATE);
        String url = prefs.getString("server_url", "").trim();
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        return url;
    }

    private void checkHealth() {
        try {
            String base = serverBase();
            boolean reachable = ping(base);
            if (!reachable) {
                // Quick tunnel мог подняться с новым адресом: спрашиваем
                // rendezvous (зашифрованный ntfy-топик), но не чаще раза
                // в минуту, чтобы не тратить батарею.
                long now = SystemClock.elapsedRealtime();
                if (now - lastRdvAttempt >= RDV_RETRY_MS) {
                    lastRdvAttempt = now;
                    String updated = Rendezvous.refresh(
                            getApplicationContext());
                    if (!updated.isEmpty() && !updated.equals(base)) {
                        reachable = ping(updated);
                    }
                }
            }
            setOnline(reachable);
        } finally {
            checking = false;
        }
    }

    private boolean ping(String base) {
        if (base == null || base.isEmpty()) {
            return false;
        }
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(base + "/health").openConnection();
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(5000);
            conn.setRequestMethod("GET");
            return conn.getResponseCode() == 200;
        } catch (Exception ignored) {
            return false;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private void setOnline(boolean value) {
        if (value == online) {
            return;
        }
        online = value;
        NotificationManager manager =
                (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.notify(NOTIFICATION_ID,
                    buildNotification(online ? "JARVIS: онлайн" : "JARVIS: нет связи"));
        }
    }

    private Notification buildNotification(String text) {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent pending = PendingIntent.getActivity(
                this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this);
        return builder
                .setContentTitle("J.A.R.V.I.S.")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentIntent(pending)
                .setOngoing(true)
                .build();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacks(healthCheck);
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
