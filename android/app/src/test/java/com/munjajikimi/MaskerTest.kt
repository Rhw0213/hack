package com.munjajikimi

import org.junit.Assert.assertEquals
import org.junit.Test

class MaskerTest {
    private fun mask(s: String) = Masker.mask(s).text

    @Test fun urlDigitsSurvive() {
        val text = "앱 설치 http://203.0.113.7:8080/a.apk 지금"
        assertEquals(text, mask(text))
    }

    @Test fun longDigitRunInsideUrlIsNotTakenForAnAccount() {
        assertEquals("조회 https://example.com/track/123456789012 확인", mask("조회 https://example.com/track/123456789012 확인"))
        assertEquals("bit.ly/01012345678 클릭", mask("bit.ly/01012345678 클릭"))
    }

    @Test fun linksAreListedWithoutTrailingPunctuation() {
        val masked = Masker.mask("확인 http://nhis-kr.top/a1. 또는 me2.do/x9 또는 10.0.0.1/p 연락 010-1234-5678")
        assertEquals(listOf("http://nhis-kr.top/a1", "me2.do/x9", "10.0.0.1/p"), masked.links)
        assertEquals("확인 http://nhis-kr.top/a1. 또는 me2.do/x9 또는 10.0.0.1/p 연락 [전화번호]", masked.text)
    }

    @Test fun mobileNumber() {
        assertEquals("연락처 [전화번호] 로", mask("연락처 010-0000-1234 로"))
        assertEquals("[전화번호]", mask("01000001234"))
        assertEquals("[전화번호]로 연락", mask("010 1234 5678로 연락"))
    }

    @Test fun landlineMaskedButRepresentativeNumberKept() {
        assertEquals("[전화번호] 또는 1588-1234", mask("02-123-4567 또는 1588-1234"))
    }

    @Test fun residentNumber() {
        assertEquals("주민번호 [주민번호] 확인", mask("주민번호 123456-1234567 확인"))
    }

    @Test fun cardNumber() {
        assertEquals("카드 [카드번호] 승인", mask("카드 1234-5678-9012-3456 승인"))
    }

    @Test fun verificationCode() {
        assertEquals("인증번호 [인증번호]를 입력하세요", mask("인증번호 [482913]를 입력하세요"))
        assertEquals("승인번호는 [인증번호]입니다", mask("승인번호는 48291377입니다"))
    }

    @Test fun nameBeforeHonorific() {
        assertEquals("[이름]님 건강검진 결과", mask("홍길동님 건강검진 결과"))
        assertEquals("[이름] 고객님 안녕하세요", mask("김철수 고객님 안녕하세요"))
    }

    @Test fun titlesAndInstitutionsAreNotNames() {
        val text = "고객님, 택배기사님, 국민은행 고객님, 어머님, 김하나님"
        assertEquals("고객님, 택배기사님, 국민은행 고객님, 어머님, [이름]님", mask(text))
    }

    @Test fun accountNumbers() {
        assertEquals("입금 계좌 [계좌번호] 로", mask("입금 계좌 123456789012 로"))
        assertEquals("국민 [계좌번호]", mask("국민 110-123-456789"))
    }

    @Test fun shortNumbersAndDatesStay() {
        val text = "2026-10-30 오후 3시, 결제 금액 35,000원, 송장 1234567"
        assertEquals(text, mask(text))
    }
}
