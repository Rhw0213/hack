package com.munjajikimi

import android.Manifest
import android.app.Activity
import android.app.NotificationManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.telephony.SmsManager
import android.view.Gravity
import kotlin.concurrent.thread

class WarningActivity : Activity() {
    private lateinit var sms: Sms
    private lateinit var verdict: Verdict

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sms = Sms.from(intent)
        verdict = Verdict.parse(intent.getStringExtra(Guard.EXTRA_VERDICT)!!)
        getSystemService(NotificationManager::class.java).cancel(intent.getIntExtra(Guard.EXTRA_NOTIFICATION, 0))
        val level = verdict.level
        setContentView(scroll(level.bg, column {
            add(label(level.emoji, 72f, level.fg).apply { gravity = Gravity.CENTER }, 8)
            add(label(verdict.title, 36f, level.fg, bold = true).apply { gravity = Gravity.CENTER })
            if (level.suspicious) add(label("이 문자의 링크를 누르지 마세요.", 26f, level.fg, bold = true), 24)
            if (verdict.reasons.isNotEmpty()) {
                add(label(if (level.suspicious) "왜 위험한가요?" else "왜 안전한가요?", 24f, level.fg, bold = true), 28)
                verdict.reasons.forEach { add(label("· $it", 22f, level.fg), 8) }
            }
            if (verdict.explanation.isNotBlank()) add(label(verdict.explanation, 22f, level.fg), 20)
            add(label("받은 문자 · ${sms.sender.ifBlank { "번호 없음" }} · ${clock(sms.receivedAt, "a h:mm")}", 20f, level.fg, bold = true), 28)
            add(messageBox(sms.body), 8)
            add(bigButton("신고하기", level.fg, level.bg) { report() }, 28)
            if (level.suspicious) add(bigButton("가족에게 알리기", level.fg, level.bg) { alertFamily() })
            add(bigButton("괜찮아요", Color.TRANSPARENT, level.fg) { finish() })
        }))
    }

    private fun report() = confirm("이 문자를 신고할까요?", "신고하기") {
        val masked = Masker.mask(sms.body).text
        toast("신고하고 있어요")
        thread {
            val sent = runCatching { Api(this).report(masked) }.isSuccess
            runOnUiThread { if (!isDestroyed) showReportSheet(sent) }
        }
    }

    private fun showReportSheet(sent: Boolean) {
        val report = listOf(
            "수신 시각: ${clock(sms.receivedAt, "yyyy-MM-dd HH:mm")}",
            "발신 번호: ${sms.sender.ifBlank { "알 수 없음" }}",
            "내용: ${sms.body}",
            "링크: ${Masker.mask(sms.body).links.joinToString(", ").ifEmpty { "없음" }}",
        ).joinToString("\n")
        val status = if (sent) "신고했어요. 비슷한 문자를 더 잘 찾아낼게요." else "서버에 신고하지 못했어요. 아래 방법으로 직접 신고할 수 있어요."
        sheet("신고 내용", column(20) {
            add(label(status, 22f, INK, bold = true), 0)
            add(messageBox(report))
            add(bigButton("신고 내용 복사", BLUE, WHITE) { copy(report) }, 20)
            add(bigButton("118 상담 전화", BLUE, WHITE) { dial("118") })
            add(bigButton("불법스팸대응센터 열기", BLUE, WHITE) { browse("https://spam.kisa.or.kr") })
            add(bigButton("문자 앱에서 스팸 신고", BLUE, WHITE) { openMessagingApp() })
            add(bigButton("이미 눌렀거나 송금했어요", RED, WHITE) { showAftercare() }, 24)
        })
    }

    private fun showAftercare() = sheet("이미 눌렀거나 송금했다면", column(20) {
        add(label("지금 바로 이렇게 하세요.", 24f, INK, bold = true), 0)
        add(bigButton("112 경찰에 전화", RED, WHITE) { dial("112") }, 20)
        add(bigButton("사이버범죄 신고하기", BLUE, WHITE) { browse("https://ecrm.police.go.kr") })
        add(label("· 돈을 보냈다면 바로 은행 고객센터에 전화해 지급정지를 요청하세요.", 22f, INK), 20)
        add(bigButton("금융감독원 1332", BLUE, WHITE) { dial("1332") })
        add(label("· 모르는 앱을 설치했다면 삭제하고, 비행기 모드를 켜 주세요.", 22f, INK), 20)
    })

    private fun copy(report: String) {
        getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("신고 내용", report))
        toast("신고 내용을 복사했어요")
    }

    private fun openMessagingApp() {
        val messaging = Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_MESSAGING)
        if (open(messaging.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))) toast("이 문자를 길게 누르고 '스팸 신고'를 눌러 주세요")
    }

    private fun alertFamily() {
        val prefs = Prefs(this)
        if (prefs.family.isBlank()) {
            toast("첫 화면에서 가족 전화번호를 먼저 입력해 주세요")
            return
        }
        if (checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.SEND_SMS), 0)
            return
        }
        // A summary only: the suspicious message itself never leaves this phone.
        val text = "[문자 지킴이] ${prefs.honorific} 휴대폰에 사기 의심 문자가 왔어요. " +
            "(${verdict.category} 사칭 의심) 링크는 누르지 않도록 안내했어요. ${clock(sms.receivedAt, "HH:mm")}"
        confirm("${prefs.family} 번호로 이렇게 보낼까요?\n\n$text", "보내기") { send(prefs.family, text) }
    }

    private fun send(number: String, text: String) {
        if (checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) return
        val manager = if (Build.VERSION.SDK_INT >= 31) {
            getSystemService(SmsManager::class.java)
        } else {
            @Suppress("DEPRECATION") SmsManager.getDefault()
        }
        try {
            manager.sendMultipartTextMessage(number, null, manager.divideMessage(text), null, null)
            toast("가족에게 알렸어요")
        } catch (e: RuntimeException) {
            toast("문자를 보내지 못했어요")
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) alertFamily()
    }
}
