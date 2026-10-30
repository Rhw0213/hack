package com.munjajikimi

import android.Manifest
import android.app.Activity
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import java.io.IOException
import kotlin.concurrent.thread

class MainActivity : Activity() {
    private lateinit var serverField: EditText
    private lateinit var familyField: EditText
    private lateinit var honorificField: EditText
    private lateinit var bodyField: EditText
    private lateinit var senderField: EditText
    private lateinit var permissionStatus: TextView
    private lateinit var connectionStatus: TextView
    private lateinit var checkButton: Button

    private val needed = buildList {
        add(Manifest.permission.RECEIVE_SMS)
        add(Manifest.permission.READ_CONTACTS)
        add(Manifest.permission.SEND_SMS)
        if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = Prefs(this)
        serverField = field("http://192.168.0.10:8000", prefs.server, InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI)
        familyField = field("010-0000-0000", prefs.family, InputType.TYPE_CLASS_PHONE)
        honorificField = field("어머니", prefs.honorific, InputType.TYPE_CLASS_TEXT)
        bodyField = field("문자 내용 붙여넣기", "", InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE).apply {
            minLines = 4
            gravity = Gravity.TOP or Gravity.START
        }
        senderField = field("발신 번호 (선택)", "", InputType.TYPE_CLASS_PHONE)
        permissionStatus = label("", 20f, MUTED)
        connectionStatus = label("", 20f, MUTED)
        checkButton = bigButton("검사하기", BLUE, WHITE) { test() }

        setContentView(scroll(WHITE, column {
            add(label("문자 지킴이", 34f, INK, bold = true), 0)
            add(label("받은 문자를 AI가 먼저 읽고, 사기 같으면 링크를 누르기 전에 알려 드려요.", 20f, MUTED), 8)
            add(label("설정", 26f, INK, bold = true), 32)
            add(label("서버 주소", 20f, MUTED, bold = true))
            add(serverField, 4)
            add(label("가족 전화번호", 20f, MUTED, bold = true))
            add(familyField, 4)
            add(label("보호받는 분 호칭", 20f, MUTED, bold = true))
            add(honorificField, 4)
            add(bigButton("권한 허용", BLUE, WHITE) { requestAll() }, 24)
            add(permissionStatus, 8)
            add(bigButton("연결 확인", BLUE, WHITE) { checkHealth() }, 16)
            add(connectionStatus, 8)
            add(label("문자 검사해 보기", 26f, INK, bold = true), 32)
            add(bodyField, 8)
            add(senderField)
            add(checkButton, 16)
        }))
    }

    override fun onResume() {
        super.onResume()
        permissionStatus.text = if (missing().isEmpty()) "권한이 모두 허용됐어요." else "권한이 더 필요해요. [권한 허용]을 눌러 주세요."
    }

    override fun onPause() {
        super.onPause()
        save()
    }

    private fun field(hint: String, value: String, type: Int) = EditText(this).apply {
        this.hint = hint
        setText(value)
        inputType = type
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 22f)
        minHeight = dp(64)
    }

    private fun save() = Prefs(this).run {
        server = serverField.text.toString()
        family = familyField.text.toString()
        honorific = honorificField.text.toString()
    }

    private fun missing() = needed.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }

    private fun requestAll() {
        val missing = missing()
        if (missing.isEmpty()) ensureFullScreenIntent() else requestPermissions(missing.toTypedArray(), 0)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        val missing = missing()
        when {
            missing.isEmpty() -> ensureFullScreenIntent()
            missing.none(::shouldShowRequestPermissionRationale) -> {
                toast("설정 화면에서 권한을 직접 허용해 주세요")
                open(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
            }
            else -> toast("권한을 허용해야 문자를 지켜 드릴 수 있어요")
        }
    }

    /** Android 14 makes full-screen alerts a separate switch that a runtime prompt cannot grant. */
    private fun ensureFullScreenIntent() {
        if (Build.VERSION.SDK_INT >= 34 && !getSystemService(NotificationManager::class.java).canUseFullScreenIntent()) {
            toast("'전체 화면 알림'을 켜 주세요")
            open(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:$packageName")))
        } else {
            toast("모든 권한이 허용됐어요")
        }
    }

    private fun checkHealth() {
        save()
        connectionStatus.text = "확인하고 있어요…"
        thread {
            val text = try {
                val health = Api(this).health()
                val server = if (health.ok) "연결됐어요" else "연결됐지만 서버가 준비 중이에요"
                val ai = if (health.ollama) "AI 켜짐" else "AI 꺼짐 (ollama를 확인해 주세요)"
                "$server · 사례 ${health.cases}개 · $ai"
            } catch (e: IOException) {
                "연결하지 못했어요. 같은 와이파이인지, 주소가 맞는지 확인해 주세요. (${e.message})"
            }
            runOnUiThread { connectionStatus.text = text }
        }
    }

    private fun test() {
        val body = bodyField.text.toString().trim()
        if (body.isEmpty()) {
            toast("검사할 문자 내용을 붙여넣어 주세요")
            return
        }
        save()
        val sms = Sms(senderField.text.toString().trim(), body, System.currentTimeMillis())
        checkButton.isEnabled = false
        checkButton.text = "검사하고 있어요…"
        thread {
            val verdict = try {
                Guard.check(this, sms)
            } catch (e: IOException) {
                null
            }
            runOnUiThread {
                checkButton.isEnabled = true
                checkButton.text = "검사하기"
                if (verdict != null) startActivity(Guard.warningIntent(this, sms, verdict)) else toast("검사 서버에 연결하지 못했어요")
            }
        }
    }
}
