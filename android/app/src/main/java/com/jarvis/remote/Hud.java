package com.jarvis.remote;

import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;

/** Цвета и формы HUD, общие для экрана камеры. */
final class Hud {

    static final int BG = Color.parseColor("#03060d");
    static final int PANEL = Color.parseColor("#0a1420");
    static final int PANEL_ALT = Color.parseColor("#0f2238");
    static final int BORDER = Color.parseColor("#1b3a5c");
    static final int TEXT = Color.parseColor("#cfe8ff");
    static final int MUTED = Color.parseColor("#6f8ca8");
    static final int ACCENT = Color.parseColor("#2ee6ff");
    static final int BLUE = Color.parseColor("#1f6feb");
    static final int GREEN = Color.parseColor("#3ddc84");
    static final int RED = Color.parseColor("#ff5c5c");
    static final int WARN = Color.parseColor("#ffb020");

    private Hud() {
    }

    static int dp(Context context, int value) {
        return Math.round(
                value * context.getResources().getDisplayMetrics().density);
    }

    static GradientDrawable rounded(Context context, int color,
                                    int radiusDp) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(context, radiusDp));
        return shape;
    }

    static GradientDrawable outlined(Context context, int color, int stroke,
                                     int radiusDp) {
        GradientDrawable shape = rounded(context, color, radiusDp);
        shape.setStroke(dp(context, 1), stroke);
        return shape;
    }
}
