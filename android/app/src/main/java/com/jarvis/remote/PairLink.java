package com.jarvis.remote;

import android.net.Uri;

import java.net.URL;
import java.util.regex.Pattern;

/** Разбор ссылок сопряжения: jarvis://pair и http(s)://…?token=… */
final class PairLink {

    static final int URL = 0;
    static final int TOKEN = 1;
    static final int FALLBACK = 2;
    static final int RDV_URL = 3;
    static final int RDV_TOPIC = 4;

    private static final String SCHEME = "jarvis";
    private static final String HOST = "pair";
    private static final Pattern TOPIC = Pattern.compile(
            "[A-Za-z0-9._-]{4,96}");

    private PairLink() {
    }

    static String normalizeBase(String value) {
        String url = value == null ? "" : value.trim();
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        return url;
    }

    static String hostOf(String url) {
        try {
            return new URL(url).getHost();
        } catch (Exception error) {
            return url;
        }
    }

    private static boolean isHttpUrl(String value) {
        return value.startsWith("http://") || value.startsWith("https://");
    }

    static String[] parse(Uri data) {
        if (data == null
                || !SCHEME.equals(data.getScheme())
                || !HOST.equals(data.getHost())) {
            return null;
        }
        String url = normalizeBase(data.getQueryParameter("url"));
        String token = data.getQueryParameter("token");
        token = token == null ? "" : token.trim();
        if (url.isEmpty() || token.isEmpty() || !isHttpUrl(url)) {
            return null;
        }
        String fallback = normalizeBase(data.getQueryParameter("lan"));
        if (!isHttpUrl(fallback) || fallback.equals(url)) {
            fallback = "";
        }
        String rdvUrl = normalizeBase(data.getQueryParameter("rdvu"));
        String rdvTopic = data.getQueryParameter("rdvt");
        rdvTopic = rdvTopic == null ? "" : rdvTopic.trim();
        if (!isHttpUrl(rdvUrl)
                || !TOPIC.matcher(rdvTopic).matches()) {
            rdvUrl = "";
            rdvTopic = "";
        }
        return new String[]{url, token, fallback, rdvUrl, rdvTopic};
    }

    /**
     * Разбирает ссылку jarvis://pair или веб-ссылку с ?token=
     * (например, из буфера обмена или QR-кода).
     */
    static String[] parseText(String text) {
        String raw = text == null ? "" : text.trim();
        if (raw.isEmpty()) {
            return null;
        }
        Uri uri;
        try {
            uri = Uri.parse(raw);
        } catch (Exception error) {
            return null;
        }
        if (SCHEME.equals(uri.getScheme()) && HOST.equals(uri.getHost())) {
            return parse(uri);
        }
        String scheme = uri.getScheme();
        if (("http".equals(scheme) || "https".equals(scheme))
                && uri.getAuthority() != null) {
            String token = uri.getQueryParameter("token");
            token = token == null ? "" : token.trim();
            if (!token.isEmpty()) {
                return new String[]{
                        normalizeBase(
                                scheme + "://" + uri.getAuthority()),
                        token,
                        "",
                        "",
                        "",
                };
            }
        }
        return null;
    }
}
