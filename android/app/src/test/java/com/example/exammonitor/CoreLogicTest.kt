package com.example.exammonitor

import com.example.exammonitor.core.*
import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDateTime

class RoleNavigationTest {
    @Test fun studentGetsStudentTabsOnly() {
        val t = Navigation.tabsFor(Role.STUDENT)
        assertEquals(listOf(AppTab.HOME, AppTab.TIMETABLE, AppTab.RESULTS, AppTab.ALERTS, AppTab.PROFILE), t)
        assertFalse(Navigation.canOpen(Role.STUDENT, AppTab.STUDENTS.route))
        assertFalse(Navigation.canOpen(Role.STUDENT, AppTab.EXAMS.route))
    }
    @Test fun staffSideNeverSeesStudentOnlyTabs() {
        for (r in listOf(Role.STAFF, Role.ADMIN, Role.SUPER_ADMIN, Role.INVIGILATOR)) {
            assertFalse(Navigation.canOpen(r, AppTab.TIMETABLE.route)); assertFalse(Navigation.canOpen(r, AppTab.RESULTS.route))
        }
    }
    @Test fun invigilatorCannotSearchStudentsOrPublish() {
        assertFalse(Navigation.canOpen(Role.INVIGILATOR, AppTab.STUDENTS.route))
        assertFalse(Permissions.can(Role.INVIGILATOR, Capability.PUBLISH_EXAMS))
        assertFalse(Permissions.can(Role.INVIGILATOR, Capability.LOOKUP_STUDENT_SEATS))
        assertTrue(Permissions.can(Role.INVIGILATOR, Capability.VIEW_HALL_OCCUPANCY))
    }
    @Test fun studentHasNoStaffCapabilities() {
        for (c in Capability.values().filter { it != Capability.VIEW_OWN_TIMETABLE && it != Capability.VIEW_OWN_RESULTS })
            assertFalse("student must not have $c", Permissions.can(Role.STUDENT, c))
    }
    @Test fun adminAndSuperAdminMayPublish() {
        assertTrue(Permissions.can(Role.ADMIN, Capability.PUBLISH_EXAMS)); assertTrue(Permissions.can(Role.SUPER_ADMIN, Capability.PUBLISH_EXAMS))
        assertTrue(Permissions.can(Role.STAFF, Capability.PUBLISH_EXAMS))
    }
    @Test fun unknownRoleIsRejected() { assertNull(Role.fromApi("root")); assertNull(Role.fromApi(null)) }

    private fun profile(role: Role = Role.STUDENT, pw: Boolean = false) = UserProfile("u", role, role.label, null, null, pw, null, null)
    @Test fun routerFollowsSessionState() {
        assertEquals(Destination.Splash, Router.destinationFor(SessionState.Restoring))
        assertEquals(Destination.Login("bye"), Router.destinationFor(SessionState.SignedOut("bye")))
        assertEquals(Destination.ForcePasswordChange, Router.destinationFor(SessionState.SignedIn(profile(pw = true))))
        assertEquals(Destination.Main(Role.ADMIN), Router.destinationFor(SessionState.SignedIn(profile(Role.ADMIN))))
    }
}

class ErrorAndValidationTest {
    @Test fun httpStatusesMapToKinds() {
        assertEquals(ErrorKind.UNAUTHORIZED, ErrorMapper.fromHttp(401, "Session timed out. Sign in again.").kind)
        assertEquals(ErrorKind.PASSWORD_CHANGE_REQUIRED, ErrorMapper.fromHttp(403, "Password change required before continuing").kind)
        assertEquals(ErrorKind.FORBIDDEN, ErrorMapper.fromHttp(403, "Insufficient permission.").kind)
        assertEquals(ErrorKind.NOT_FOUND, ErrorMapper.fromHttp(404, null).kind)
        assertEquals(ErrorKind.CONFLICT, ErrorMapper.fromHttp(409, "x").kind)
        assertEquals(ErrorKind.VALIDATION, ErrorMapper.fromHttp(422, "x").kind)
        assertEquals(ErrorKind.SERVER, ErrorMapper.fromHttp(503, "<html>secret stack</html>").kind)
    }
    @Test fun serverErrorsNeverLeakBodyText() { assertFalse(ErrorMapper.fromHttp(500, "Traceback ...").message.contains("Traceback")) }
    @Test fun rateLimitCarriesRetryAfter() {
        val f = ErrorMapper.fromHttp(429, "Too many sign-in attempts. Try again later.", "120")
        assertEquals(ErrorKind.RATE_LIMITED, f.kind); assertEquals(120, f.retryAfterSeconds); assertTrue(f.message.contains("2 minutes"))
    }
    @Test fun cacheFallbackOnlyForConnectivityNotPermissions() {
        assertTrue(ErrorMapper.allowsCacheFallback(ErrorMapper.network(false)))
        assertTrue(ErrorMapper.allowsCacheFallback(ErrorMapper.network(true)))
        assertFalse(ErrorMapper.allowsCacheFallback(ErrorMapper.fromHttp(401, null)))
        assertFalse(ErrorMapper.allowsCacheFallback(ErrorMapper.fromHttp(403, null)))
        assertFalse(ErrorMapper.allowsCacheFallback(ErrorMapper.fromHttp(404, null)))
    }
    @Test fun passwordPolicyMirrorsBackend() {
        assertTrue(PasswordPolicy.problems("short1").isNotEmpty())
        assertTrue(PasswordPolicy.problems("onlyletterslongenough").isNotEmpty())
        assertTrue(PasswordPolicy.problems("aaaaaaaaaaaa1").isNotEmpty())
        assertTrue(PasswordPolicy.problems("my-alice-pass-2026", "alice").isNotEmpty())
        assertTrue(PasswordPolicy.problems("Sturdy-Pass-2026-xyz", "alice").isEmpty())
    }
    @Test fun resetTokenFromLinkOrRaw() {
        val tok = "abcdefghij0123456789_-XYZabcdefghij"
        assertEquals(tok, ResetTokenParser.extract("https://x.edu/?reset=$tok"))
        assertEquals(tok, ResetTokenParser.extract("  $tok "))
        assertNull(ResetTokenParser.extract("")); assertNull(ResetTokenParser.extract("short")); assertNull(ResetTokenParser.extract("https://x.edu/?other=1"))
    }
    @Test fun apiUrlRequiresHttpsInRelease() {
        assertTrue(ApiUrl.check("http://10.0.2.2:8000", false) is UrlCheck.Rejected)
        assertEquals(UrlCheck.Ok("http://10.0.2.2:8000/"), ApiUrl.check("http://10.0.2.2:8000", true))
        assertEquals(UrlCheck.Ok("https://exams.edu/"), ApiUrl.check("exams.edu", false))
        assertEquals(UrlCheck.Ok("https://exams.edu/api-root/"), ApiUrl.check("https://exams.edu/api-root", false))
        assertTrue(ApiUrl.check("https://user:pw@exams.edu", false) is UrlCheck.Rejected)
        assertTrue(ApiUrl.check("   ", true) is UrlCheck.Rejected)
        assertTrue(ApiUrl.check("ftp://x", true) is UrlCheck.Rejected)
    }
    @Test fun loginValidation() { assertNotNull(LoginValidation.problem("", "x")); assertNotNull(LoginValidation.problem("a", "")); assertNull(LoginValidation.problem("a", "b")) }
}

class TimetableAndNotificationTest {
    private val now = LocalDateTime.of(2026, 11, 14, 10, 0)
    private fun a(date: String, time: String, name: String = "E") = SeatAllotment(name, "C", date, time, "H1", "5", null)
    @Test fun upcomingPastAndNext() {
        val items = listOf(a("2026-11-20", "09:30", "B"), a("2026-11-10", "09:30", "old"), a("2026-11-16", "14:00", "A"))
        assertEquals(listOf("A", "B"), Timetable.upcoming(items, now).map { it.exam })
        assertEquals(listOf("old"), Timetable.past(items, now).map { it.exam })
        assertEquals("A", Timetable.next(items, now)?.exam)
        assertNull(Timetable.next(emptyList(), now))
    }
    @Test fun countdownLabels() {
        assertEquals("Today", ExamClock.countdown("2026-11-14", "14:00", now)); assertEquals("Tomorrow", ExamClock.countdown("2026-11-15", "09:00", now))
        assertEquals("In 6 days", ExamClock.countdown("2026-11-20", "09:00", now)); assertEquals("Completed", ExamClock.countdown("2026-11-01", "09:00", now))
        assertNull(ExamClock.countdown("garbage", "x", now))
    }
    @Test fun formatting() {
        assertEquals("Fri, 20 Nov 2026", ExamClock.formatDate("2026-11-20")); assertEquals("9:30 AM", ExamClock.formatTime("09:30"))
        assertEquals("not-a-date", ExamClock.formatDate("not-a-date"))
    }
    @Test fun timestampsParseWithAndWithoutZone() {
        assertNotNull(ExamClock.parseInstant("2026-11-14T07:30:00+00:00")); assertNotNull(ExamClock.parseInstant("2026-11-14T07:30:00.123456"))
        assertNull(ExamClock.parseInstant("nope"))
    }
    private fun n(id: Int, read: Boolean = false) = AppNotification(id, "exam", "Examinations", "normal", "t$id", "b", null, "2026-11-14T07:00:00+00:00", read, false)
    @Test fun readUnreadReducers() {
        val l = listOf(n(1), n(2, true), n(3))
        assertEquals(2, NotificationLogic.unreadIn(l))
        assertTrue(NotificationLogic.withRead(l, 1, true)[0].read)
        assertFalse(NotificationLogic.withRead(l, 2, false)[1].read)
        assertEquals(listOf(2, 3), NotificationLogic.without(l, 1).map { it.id })
        assertEquals(0, NotificationLogic.unreadIn(NotificationLogic.allRead(l)))
    }
    @Test fun pagingMergeHasNoDuplicates() { assertEquals(listOf(1, 2, 3), NotificationLogic.merge(listOf(n(1), n(2)), listOf(n(2), n(3))).map { it.id }) }
    @Test fun notificationLinksOnlyOpenAllowedTabs() {
        assertEquals(AppTab.TIMETABLE, NotificationLogic.tabForLink("#/my-exams", Role.STUDENT))
        assertEquals(AppTab.EXAMS, NotificationLogic.tabForLink("#/my-exams", Role.STAFF))
        assertNull(NotificationLogic.tabForLink("#/my-results", Role.STAFF))
        assertNull(NotificationLogic.tabForLink("javascript:alert(1)", Role.STUDENT)); assertNull(NotificationLogic.tabForLink(null, Role.STUDENT))
    }
}

class DataIsolationAndMappingTest {
    @Test fun cacheKeysAreNamespacedPerUser() {
        val k = CacheKeys.forUser("Alice", "lookup")
        assertTrue(CacheKeys.belongsTo(k, "alice")); assertFalse(CacheKeys.belongsTo(k, "bob"))
        assertNotEquals(CacheKeys.forUser("alice", "lookup"), CacheKeys.forUser("bob", "lookup"))
        assertFalse("prefix collision", CacheKeys.belongsTo(CacheKeys.forUser("alice2", "x"), "alice"))
    }
    @Test fun mappersRejectMissingRequiredFields() {
        assertThrows { Mappers.profile(ProfileDto(username = "a", role = "hacker")) }
        assertThrows { Mappers.profile(null) }
        assertThrows { Mappers.allotment(AllotmentDto(exam = "E", date = "2026-11-20", hall = "H")) }   // no seat
        assertThrows { Mappers.notification(NotificationDto(id = 1, title = "")) }
        assertThrows { Mappers.exam(ExamDto(id = 1, title = "T")) }
        assertThrows { Mappers.lookup(LookupDto()) }
    }
    @Test fun mappersAcceptValidPayloads() {
        val p = Mappers.profile(ProfileDto(username = "s1", role = "student", register_number = "990025106001", pw_change_required = false))
        assertEquals(Role.STUDENT, p.role); assertEquals("990025106001", p.registerNumber); assertFalse(p.passwordChangeRequired)
        val a = Mappers.allotment(AllotmentDto("E", "C1", "2026-11-20", "09:30", "H1", "7", HallLocationDto(building = "Main", room = "101")))
        assertEquals("Main / 101", a.location?.describe())
        assertNull(Mappers.allotment(AllotmentDto("E", "C1", "2026-11-20", "09:30", "H1", "7", HallLocationDto())).location)
        assertEquals(3, Mappers.dashboard(DashboardDto(students = 3)).students)
    }
    private fun assertThrows(block: () -> Unit) {
        try { block(); fail("expected InvalidResponseException") } catch (e: InvalidResponseException) { /* ok */ }
    }
}
