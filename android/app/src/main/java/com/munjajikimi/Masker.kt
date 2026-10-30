package com.munjajikimi

data class Masked(val text: String, val links: List<String>)

/** Hides personal data on the phone so raw message text never reaches the server. */
object Masker {
    private const val HOLD = ''
    private const val URL_CHAR = """[^\s<>"'()\[\]{}가-힣ㄱ-ㅎㅏ-ㅣ]"""
    private const val TLD = "co\\.kr|or\\.kr|go\\.kr|com|net|kr|top|xyz|shop|site|icu|cc|me|ly|gl|do|la|io"

    private val URL = Regex(
        listOf(
            "https?://$URL_CHAR+",
            """(?<![\w.@-])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?:/$URL_CHAR*)?""",
            """(?<![\w.@-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:$TLD)(?![\w-])(?::\d{1,5})?(?:/$URL_CHAR*)?""",
        ).joinToString("|"),
        RegexOption.IGNORE_CASE,
    )
    private val TRAILING = charArrayOf('.', ',', '!', '?', ';', ':', '~')

    // Titles, family words and institutions that sit before 님 or 고객님 but are not names.
    private val NOT_NAME_SUFFIX = listOf(
        "고객", "회원", "기사", "선생", "사장", "교수", "선배", "후배", "담당자", "관리자", "사모",
        "언니", "누나", "오빠", "부모", "아버", "어머", "할머", "할아버", "주인",
        "이용자", "사용자", "가입자", "보호자", "신청자", "구매자", "주문자", "수령인", "수취인",
        "대표", "원장", "실장", "팀장", "부장", "과장", "차장", "소장", "회장", "점장", "대리", "주임",
        "기자", "작가", "목사", "신부", "수녀", "의사", "약사", "간호사", "변호사", "세무사",
        "은행", "카드", "택배", "통운", "우체국", "증권", "보험", "생명", "화재", "캐피탈", "저축", "금고",
        "공단", "공사", "법원", "센터", "마트", "페이", "뱅크", "텔레콤", "통신", "농협", "수협", "신협",
        "쿠팡", "네이버", "카카오", "토스", "당근",
    )
    // Matched whole, because as suffixes they would swallow common names (김하나, 박준형).
    private val NOT_NAME_EXACT = setOf("형", "하나", "하느", "부처", "아드", "따", "손")

    private val RULES: List<Pair<Regex, (MatchResult) -> String>> = listOf(
        Regex("""(?<!\d)\d{6}-?[1-4]\d{6}(?!\d)""") to { _ -> "[주민번호]" },
        Regex("""(?<!\d)\d{4}([- ]?)\d{4}\1\d{4}\1\d{4}(?!\d)""") to { _ -> "[카드번호]" },
        Regex("""(?<!\d)(?:01[016789][-. ]?\d{3,4}[-. ]?\d{4}|0\d{1,2}-\d{3,4}-\d{4})(?!\d)""") to { _ -> "[전화번호]" },
        Regex("""(?<!\d)(?<!\d-)\d+(?:-\d+)*(?!-?\d)""") to { m ->
            if (m.value.count(Char::isDigit) in 10..14) "[계좌번호]" else m.value
        },
        Regex("""(인증번호|승인번호|인증코드)(\s*(?:는|은)?\s*[:：]?\s*)[\[(【<]?\d{4,8}[\])】>]?(?!\d)""") to { m ->
            m.groupValues[1] + m.groupValues[2] + "[인증번호]"
        },
        Regex("""(?<![가-힣])[가-힣]{2,4}(?=\s?(?:고객)?님)""") to { m ->
            val word = m.value
            if (word in NOT_NAME_EXACT || NOT_NAME_SUFFIX.any(word::endsWith)) word else "[이름]"
        },
    )

    fun mask(raw: String): Masked {
        val links = mutableListOf<String>()
        // URLs are swapped for a placeholder first so no rule below can eat a digit inside one.
        var text = URL.replace(raw.replace(HOLD.toString(), "")) { m ->
            val url = m.value.trimEnd(*TRAILING)
            links += url
            HOLD + m.value.substring(url.length)
        }
        for ((rule, replace) in RULES) text = rule.replace(text, replace)
        val restore = links.iterator()
        return Masked(text.replace(Regex(HOLD.toString())) { restore.next() }, links)
    }
}
