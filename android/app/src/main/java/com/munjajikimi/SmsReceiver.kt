package com.munjajikimi

import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.provider.Telephony
import java.util.concurrent.Executors
import kotlin.concurrent.thread

class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val now = System.currentTimeMillis()
        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent).orEmpty().filterNotNull()
            .groupBy { it.originatingAddress.orEmpty() }
            .map { (sender, parts) -> Sms(sender, parts.joinToString("") { it.messageBody.orEmpty() }, now) }
        val refused = messages.filterNot { startCheck(context, it) }
        if (refused.isEmpty()) return
        // SMS_RECEIVED is a foreground broadcast, so this fallback gets about 10 s before the system kills it.
        val pending = goAsync()
        thread {
            try {
                refused.forEach { Guard.screen(context, it) }
            } finally {
                pending.finish()
            }
        }
    }

    /** The SMS broadcast grants a temporary allowlist for this start; some OEM battery modes refuse it anyway. */
    private fun startCheck(context: Context, sms: Sms): Boolean = try {
        context.startForegroundService(sms.putInto(Intent(context, CheckService::class.java)))
        true
    } catch (e: IllegalStateException) {
        false
    }
}

/** Holds the process alive while the server thinks, which can outlast a receiver's 10 s window. */
class CheckService : Service() {
    private val worker = Executors.newSingleThreadExecutor()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notification = Guard.progressNotification(this)
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(Guard.PROGRESS_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SHORT_SERVICE)
        } else {
            startForeground(Guard.PROGRESS_ID, notification)
        }
        val sms = intent?.let(Sms::from)
        worker.execute {
            try {
                if (sms != null) Guard.screen(this, sms)
            } finally {
                // Jobs run in start order, so only the newest job's stopSelf actually stops the service.
                stopSelf(startId)
            }
        }
        return START_NOT_STICKY
    }

    override fun onTimeout(startId: Int) = stopSelf()

    override fun onDestroy() {
        worker.shutdown()
        super.onDestroy()
    }
}
