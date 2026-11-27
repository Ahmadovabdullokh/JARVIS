package com.jarvis.remote;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

/**
 * Поднимает foreground-службу после перезагрузки телефона, чтобы
 * уведомление о связи с JARVIS и автообновление адреса работали без
 * ручного запуска приложения.
 */
public class BootReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent == null ? "" : intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action)
                && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) {
            return;
        }
        if (!JarvisApi.configured(context)) {
            return;
        }
        try {
            Intent service = new Intent(context, RemoteService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(service);
            } else {
                context.startService(service);
            }
        } catch (Exception ignored) {
            // Некоторые прошивки запрещают старт из фона — откроется
            // при запуске приложения вручную.
        }
    }
}
