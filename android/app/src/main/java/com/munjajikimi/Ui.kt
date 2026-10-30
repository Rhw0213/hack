package com.munjajikimi

import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.net.Uri
import android.util.TypedValue
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToInt

internal const val WHITE = 0xFFFFFFFF.toInt()
internal const val INK = 0xFF111111.toInt()
internal const val MUTED = 0xFF444444.toInt()
internal const val BLUE = 0xFF0D47A1.toInt()
internal const val RED = 0xFFB71C1C.toInt()

internal fun Context.dp(v: Int): Int = (v * resources.displayMetrics.density).roundToInt()

internal fun Context.label(text: CharSequence, sp: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
    this.text = text
    setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
    setTextColor(color)
    setLineSpacing(0f, 1.2f)
    if (bold) typeface = Typeface.DEFAULT_BOLD
}

/** A transparent [bg] draws an outlined button in [fg]. */
internal fun Context.bigButton(text: String, bg: Int, fg: Int, onClick: () -> Unit) = Button(this).apply {
    this.text = text
    isAllCaps = false
    setTextSize(TypedValue.COMPLEX_UNIT_SP, 22f)
    typeface = Typeface.DEFAULT_BOLD
    setTextColor(fg)
    minHeight = dp(64)
    minimumHeight = dp(64)
    stateListAnimator = null
    val shape = GradientDrawable().apply {
        cornerRadius = dp(16).toFloat()
        setColor(bg)
        if (Color.alpha(bg) == 0) setStroke(dp(3), fg)
    }
    background = RippleDrawable(ColorStateList.valueOf(0x40808080), shape, null)
    setOnClickListener { onClick() }
}

/** Shows a message exactly as received: no autolink, no selection, so a link inside can never be opened. */
internal fun Context.messageBox(text: String) = label(text, 20f, 0xFF333333.toInt()).apply {
    autoLinkMask = 0
    linksClickable = false
    movementMethod = null
    setTextIsSelectable(false)
    setPadding(dp(16), dp(16), dp(16), dp(16))
    background = GradientDrawable().apply {
        cornerRadius = dp(12).toFloat()
        setColor(0xFFF2F2F2.toInt())
    }
}

internal fun Context.column(padding: Int = 24, build: LinearLayout.() -> Unit) = LinearLayout(this).apply {
    orientation = LinearLayout.VERTICAL
    setPadding(dp(padding), dp(padding), dp(padding), dp(padding))
    build()
}

internal fun LinearLayout.add(view: View, top: Int = 12) {
    addView(view, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = context.dp(top) })
}

internal fun Context.scroll(bg: Int, content: View) = ScrollView(this).apply {
    setBackgroundColor(bg)
    isFillViewport = true
    addView(content)
}

internal fun Context.toast(text: String) = Toast.makeText(this, text, Toast.LENGTH_LONG).show()

internal fun clock(millis: Long, pattern: String): String = SimpleDateFormat(pattern, Locale.KOREA).format(Date(millis))

internal fun Activity.open(intent: Intent): Boolean = try {
    startActivity(intent)
    true
} catch (e: ActivityNotFoundException) {
    toast("열 수 있는 앱이 없어요")
    false
}

internal fun Activity.dial(number: String) = open(Intent(Intent.ACTION_DIAL, Uri.parse("tel:$number")))

internal fun Activity.browse(url: String) = open(Intent(Intent.ACTION_VIEW, Uri.parse(url)))

internal fun Activity.confirm(message: String, yes: String, onYes: () -> Unit) {
    AlertDialog.Builder(this)
        .setMessage(message)
        .setPositiveButton(yes) { _, _ -> onYes() }
        .setNegativeButton("취소", null)
        .show()
        .enlarge()
}

internal fun Activity.sheet(title: String, content: View) {
    AlertDialog.Builder(this)
        .setTitle(title)
        .setView(ScrollView(this).apply { addView(content) })
        .setNegativeButton("닫기", null)
        .show()
        .enlarge()
}

/** Framework dialogs default to small type; this app's readers need it large. */
private fun AlertDialog.enlarge() {
    findViewById<TextView>(android.R.id.message)?.textSize = 24f
    getButton(AlertDialog.BUTTON_POSITIVE)?.textSize = 22f
    getButton(AlertDialog.BUTTON_NEGATIVE)?.textSize = 22f
}
