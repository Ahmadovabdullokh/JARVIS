package com.jarvis.remote;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

/**
 * Минимальный RPC-клиент JARVIS для foreground-службы и экрана камеры.
 * Основной экран чата пользуется своим транспортом и не зависит от него.
 */
final class JarvisApi {

    private static final String PREFS = "jarvis_remote";
    private static final String KEY_URL = "server_url";
    private static final String KEY_TOKEN = "server_token";

    private JarvisApi() {
    }

    static String base(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(
                PREFS, Context.MODE_PRIVATE);
        String url = prefs.getString(KEY_URL, "").trim();
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        return url;
    }

    static String token(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString(KEY_TOKEN, "").trim();
    }

    static boolean configured(Context context) {
        return !base(context).isEmpty() && !token(context).isEmpty();
    }

    static JSONObject rpc(Context context, String method, JSONObject payload)
            throws IOException {
        String server = base(context);
        String auth = token(context);
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
            conn.setRequestProperty(
                    "Content-Type", "application/json; charset=utf-8");
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
                throw new IOException("доступ запрещён");
            }
            JSONObject response;
            try {
                response = new JSONObject(text);
            } catch (Exception error) {
                throw new IOException("некорректный ответ сервера");
            }
            if (!response.optBoolean("ok")) {
                throw new IOException(response.optString(
                        "error", "ошибка JARVIS"));
            }
            JSONObject result = response.optJSONObject("data");
            return result == null ? new JSONObject() : result;
        } catch (org.json.JSONException error) {
            throw new IOException("не удалось собрать запрос");
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    static String readAll(InputStream stream) throws IOException {
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
}
