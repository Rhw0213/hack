package com.munjajikimi

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.ContactsContract.PhoneLookup
import java.io.IOException

data class Sms(val sender: String, val body: String, val receivedAt: Long) {
    fun putInto(intent: Intent): Intent =
        intent.putExtra(SENDER, sender).putExtra(BODY, body).putExtra(RECEIVED_AT, receivedAt)

    companion object {
        private const val SENDER = "sender"
        private const val BODY = "body"
        private const val RECEIVED_AT = "received_at"

        fun from(intent: Intent) = Sms(
            intent.getStringExtra(SENDER).orEmpty(),
            intent.getStringExtra(BODY).orEmpty(),
            intent.getLongExtra(RECEIVED_AT, System.currentTimeMillis()),
        )
    }
}

/** The one receive → mask → check → route path, shared by SmsReceiver and the test box. */
object Guard {
    const val EXTRA_VERDICT = "verdict"
    const val EXTRA_NOTIFICATION = "notification"
    private const val WARNING_CHANNEL = "warning"
    private const val STATUS_CHANNEL = "status"
    private const val UNREACHABLE_ID = 1
    const val PROGRESS_ID = 2

    /** Blocking. Only the masked text leaves the phone. */
    fun check(context: Context, sms: Sms): Verdict =
        Api(context).check(Masker.mask(sms.body).text, isContact(context, sms.sender))

    /** Blocking. The incoming-SMS route: SAFE stays silent so the phone never cries wolf. */
    fun screen(context: Context, sms: Sms) {
        val verdict = try {
            check(context, sms)
        } catch (e: IOException) {
            notifyUnreachable(context)
            return
        }
        context.getSystemService(NotificationManager::class.java).cancel(UNREACHABLE_ID)
        when (verdict.level) {
            Level.DANGER -> notifyWarning(context, sms, verdict, fullScreen = true)
            Level.CAUTION -> notifyWarning(context, sms, verdict, fullScreen = false)
            Level.SAFE -> Unit
        }
    }

    fun warningIntent(context: Context, sms: Sms, verdict: Verdict, notificationId: Int = 0): Intent =
        sms.putInto(Intent(context, WarningActivity::class.java))
            .putExtra(EXTRA_VERDICT, verdict.source)
            .putExtra(EXTRA_NOTIFICATION, notificationId)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    fun progressNotification(context: Context): Notification =
        Notification.Builder(context, channel(context, STATUS_CHANNEL))
            .setSmallIcon(R.drawable.ic_shield)
            .setContentTitle("받은 문자를 확인하고 있어요")
            .build()

    private fun notifyWarning(context: Context, sms: Sms, verdict: Verdict, fullScreen: Boolean) {
        val id = sms.hashCode()
        val open = PendingIntent.getActivity(
            context, id, warningIntent(context, sms, verdict, id),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val builder = Notification.Builder(context, channel(context, WARNING_CHANNEL))
            .setSmallIcon(R.drawable.ic_shield)
            .setColor(verdict.level.bg)
            .setContentTitle("${verdict.level.emoji} ${verdict.title}")
            .setContentText("이 문자의 링크를 누르지 마세요. 눌러서 자세히 보기")
            .setStyle(Notification.BigTextStyle().bigText(verdict.reasons.joinToString("\n") { "· $it" }))
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setWhen(sms.receivedAt)
            .setShowWhen(true)
            .setContentIntent(open)
            .setAutoCancel(true)
        if (fullScreen) builder.setFullScreenIntent(open, true)
        context.getSystemService(NotificationManager::class.java).notify(id, builder.build())
    }

    private fun notifyUnreachable(context: Context) {
        val open = PendingIntent.getActivity(
            context, UNREACHABLE_ID,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = Notification.Builder(context, channel(context, STATUS_CHANNEL))
            .setSmallIcon(R.drawable.ic_shield)
            .setContentTitle("검사 서버에 연결하지 못했어요")
            .setContentText("문자 지킴이에서 서버 주소를 확인해 주세요")
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        context.getSystemService(NotificationManager::class.java).notify(UNREACHABLE_ID, notification)
    }

    /** Creating channels is idempotent, so every post ensures both exist and returns the one it wants. */
    private fun channel(context: Context, id: String): String {
        context.getSystemService(NotificationManager::class.java).createNotificationChannels(
            listOf(
                NotificationChannel(WARNING_CHANNEL, "사기 의심 문자 경고", NotificationManager.IMPORTANCE_HIGH).apply {
                    lockscreenVisibility = Notification.VISIBILITY_PUBLIC
                    enableVibration(true)
                },
                NotificationChannel(STATUS_CHANNEL, "검사 상태", NotificationManager.IMPORTANCE_LOW),
            ),
        )
        return id
    }

    private fun isContact(context: Context, number: String): Boolean {
        if (number.isBlank()) return false
        if (context.checkSelfPermission(Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) return false
        val uri = Uri.withAppendedPath(PhoneLookup.CONTENT_FILTER_URI, Uri.encode(number))
        return context.contentResolver.query(uri, arrayOf(PhoneLookup._ID), null, null, null)
            ?.use { it.moveToFirst() } ?: false
    }
}
