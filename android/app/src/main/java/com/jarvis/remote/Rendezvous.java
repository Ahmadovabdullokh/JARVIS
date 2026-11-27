package com.jarvis.remote;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;

import org.json.JSONObject;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * Rendezvous: телефон узнаёт актуальный публичный адрес ПК из ntfy-топика.
 *
 * JARVIS публикует туда AES-GCM-зашифрованный URL (ключ = SHA-256 от
 * токена доступа). Quick tunnel Cloudflare меняет адрес при каждом
 * запуске, поэтому без rendezvous телефон не смог бы переподключиться
 * сам, когда ПК и телефон в разных городах.
 */
final class Rendezvous {

    private static final String PREFS = "jarvis_remote";
    private static final String KEY_URL = "server_url";
    private static final String KEY_TOKEN = "server_token";
    private static final String KEY_RDV_URL = "rdv_url";
    private static final String KEY_RDV_TOPIC = "rdv_topic";
    private static final String DEFAULT_BASE = "https://ntfy.sh";
    private static final String PREFIX = "v1.";
    private static final int NONCE_BYTES = 12;
    private static final int TAG_BITS = 128;

    private Rendezvous() {
    }

    /**
     * Запрашивает последний адрес из топика и сохраняет его в настройки.
     * Возвращает новый URL или пустую строку.
     */
    static String refresh(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(
                PREFS, Context.MODE_PRIVATE);
        String token = prefs.getString(KEY_TOKEN, "").trim();
        String base = prefs.getString(KEY_RDV_URL, "").trim();
        String topic = prefs.getString(KEY_RDV_TOPIC, "").trim();
        if (base.isEmpty()) {
            base = DEFAULT_BASE;
        }
        while (base.endsWith("/")) {
            base = base.substring(0, base.length() - 1);
        }
        if (token.isEmpty() || topic.isEmpty()
                || !(base.startsWith("http://")
                || base.startsWith("https://"))) {
            return "";
        }

        String body = fetch(base, topic);
        if (body.isEmpty()) {
            return "";
        }
        String found = "";
        for (String line : body.split("\n")) {
            String text = line.trim();
            if (text.isEmpty()) {
                continue;
            }
            try {
                JSONObject message = new JSONObject(text);
                if (!"message".equals(message.optString("event", ""))) {
                    continue;
                }
                String payload = message.optString("message", "");
                String url = decrypt(payload, token);
                if (!url.isEmpty()) {
                    found = url;
                }
            } catch (Exception ignored) {
                // Строка не JSON или чужое сообщение — пропускаем.
            }
        }
        if (found.isEmpty()) {
            return "";
        }
        if (!found.equals(prefs.getString(KEY_URL, ""))) {
            prefs.edit().putString(KEY_URL, found).apply();
        }
        return found;
    }

    private static String fetch(String base, String topic) {
        HttpURLConnection conn = null;
        try {
            String target = base + "/"
                    + URLEncoder.encode(topic, "UTF-8")
                    + "/json?poll=1&since=all";
            conn = (HttpURLConnection) new URL(target).openConnection();
            conn.setConnectTimeout(8000);
            conn.setReadTimeout(10000);
            conn.setRequestMethod("GET");
            conn.setRequestProperty("Accept", "application/x-ndjson");
            conn.setRequestProperty("User-Agent", "JARVIS-Android");
            int code = conn.getResponseCode();
            if (code != 200) {
                return "";
            }
            InputStream stream = conn.getInputStream();
            return stream == null ? "" : readAll(stream);
        } catch (Exception error) {
            return "";
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private static String readAll(InputStream stream) throws Exception {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        try (InputStream in = stream) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) > 0) {
                out.write(buffer, 0, read);
            }
        }
        return out.toString("UTF-8");
    }

    /** Расшифровывает ``v1.`` + base64url(nonce + ciphertext + tag). */
    static String decrypt(String payload, String token) {
        String text = payload == null ? "" : payload.trim();
        if (!text.startsWith(PREFIX) || token == null || token.isEmpty()) {
            return "";
        }
        try {
            byte[] raw = Base64.decode(
                    text.substring(PREFIX.length()),
                    Base64.URL_SAFE | Base64.NO_WRAP);
            if (raw.length <= NONCE_BYTES) {
                return "";
            }
            byte[] nonce = new byte[NONCE_BYTES];
            System.arraycopy(raw, 0, nonce, 0, NONCE_BYTES);
            byte[] encrypted = new byte[raw.length - NONCE_BYTES];
            System.arraycopy(
                    raw, NONCE_BYTES, encrypted, 0, encrypted.length);

            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] key = digest.digest(
                    token.getBytes(StandardCharsets.UTF_8));
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE,
                    new SecretKeySpec(key, "AES"),
                    new GCMParameterSpec(TAG_BITS, nonce));
            String url = new String(
                    cipher.doFinal(encrypted), StandardCharsets.UTF_8).trim();
            if (!(url.startsWith("http://") || url.startsWith("https://"))) {
                return "";
            }
            while (url.endsWith("/")) {
                url = url.substring(0, url.length() - 1);
            }
            return url;
        } catch (Exception error) {
            return "";
        }
    }
}
