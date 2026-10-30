package com.munjajikimi

import android.content.Context
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

class Prefs(context: Context) {
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var server: String
        get() = prefs.getString("server", "").orEmpty()
        set(v) = prefs.edit().putString("server", v.trim()).apply()
    var family: String
        get() = prefs.getString("family", "").orEmpty()
        set(v) = prefs.edit().putString("family", v.trim()).apply()
    var honorific: String
        get() = prefs.getString("honorific", "").orEmpty().ifBlank { "어머니" }
        set(v) = prefs.edit().putString("honorific", v.trim()).apply()
}

data class Health(val ok: Boolean, val cases: Int, val ollama: Boolean)
data class Report(val id: String, val added: Boolean, val total: Int)

/** Blocking calls to the 판정 server; run them off the main thread. Every failure surfaces as IOException. */
class Api(context: Context) {
    private val base = Prefs(context).server.trimEnd('/').let {
        if (it.isEmpty() || it.contains("://")) it else "http://$it"
    }

    fun check(maskedText: String, fromContact: Boolean): Verdict =
        call("/check", JSONObject().put("text", maskedText).put("from_contact", fromContact), Verdict::parse)

    fun report(maskedText: String): Report = call("/report", JSONObject().put("text", maskedText)) {
        JSONObject(it).run { Report(getString("id"), getBoolean("added"), getInt("total")) }
    }

    fun health(): Health = call("/health", null) {
        JSONObject(it).run { Health(getBoolean("ok"), optInt("cases"), optBoolean("ollama")) }
    }

    private fun <T> call(path: String, body: JSONObject?, read: (String) -> T): T {
        if (base.isEmpty()) throw IOException("서버 주소가 없어요")
        var conn: HttpURLConnection? = null
        try {
            conn = URL(base + path).openConnection() as HttpURLConnection
            conn.connectTimeout = 5_000
            conn.readTimeout = 30_000
            if (body != null) {
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                conn.outputStream.use { it.write(body.toString().toByteArray()) }
            }
            if (conn.responseCode !in 200..299) throw IOException("HTTP ${conn.responseCode}")
            return read(conn.inputStream.bufferedReader().use { it.readText() })
        } catch (e: JSONException) {
            throw IOException("응답 형식이 달라요", e)
        } catch (e: IllegalArgumentException) {
            throw IOException("서버 주소나 응답 형식이 잘못됐어요", e)
        } finally {
            conn?.disconnect()
        }
    }
}
