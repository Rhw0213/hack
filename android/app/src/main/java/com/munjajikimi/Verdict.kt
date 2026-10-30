package com.munjajikimi

import org.json.JSONArray
import org.json.JSONObject

enum class Level(val bg: Int, val fg: Int, val emoji: String, val suspicious: Boolean) {
    DANGER(RED, WHITE, "🔴", true),
    CAUTION(0xFFFFD54F.toInt(), INK, "🟡", true),
    SAFE(0xFF1B5E20.toInt(), WHITE, "🟢", false),
}

/** A /check response. [source] is the JSON it came from, kept so it can ride in an Intent extra. */
data class Verdict(
    val level: Level,
    val score: Int,
    val title: String,
    val reasons: List<String>,
    val explanation: String,
    val category: String,
    val links: List<String>,
    val source: String,
) {
    companion object {
        fun parse(json: String): Verdict {
            val o = JSONObject(json)
            return Verdict(
                level = Level.valueOf(o.getString("level").uppercase()),
                score = o.optInt("score"),
                title = o.getString("title"),
                reasons = o.optJSONArray("reasons").strings(),
                explanation = o.optString("explanation"),
                category = o.optString("category", "기타"),
                links = o.optJSONArray("links").strings(),
                source = json,
            )
        }
    }
}

private fun JSONArray?.strings(): List<String> = if (this == null) emptyList() else List(length()) { getString(it) }
