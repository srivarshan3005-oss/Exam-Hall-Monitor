package com.example.exammonitor

import com.example.exammonitor.core.*
import com.example.exammonitor.data.*
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.Assert.*
import org.junit.Test
import retrofit2.Response
import java.io.IOException
import java.lang.reflect.Proxy

/** Fake ExamApi: [handlers] maps method name -> response. Unlisted calls fail the test (no hidden network). */
private fun fakeApi(calls: MutableList<String> = mutableListOf(), vararg handlers: Pair<String, (Array<Any?>) -> Any?>): ExamApi {
    val map = handlers.toMap()
    return Proxy.newProxyInstance(ExamApi::class.java.classLoader, arrayOf(ExamApi::class.java)) { _, m, args ->
        calls += m.name + (args?.dropLast(1)?.joinToString(prefix = "(", postfix = ")") ?: "()")
        (map[m.name] ?: throw AssertionError("unexpected call ${m.name}"))(args ?: emptyArray())
    } as ExamApi
}

private fun err(code: Int, json: String) = Response.error<Any>(code, okhttp3.ResponseBody.create(null, json))
private fun studentProfile(reg: String? = "990025106001") = ProfileDto("stud1", "student", "Student", null, null, false, reg, "S One")

class SessionAndCacheTest {
    private fun newSession(): Triple<SessionManager, CacheStore, InMemoryStore> {
        val secure = InMemoryStore(); val cache = CacheStore(InMemoryStore())
        return Triple(SessionManager(secure, cache), cache, secure)
    }
    private fun prof(name: String) = UserProfile(name, Role.STUDENT, "Student", null, null, false, "990025106001", null)

    @Test fun signInStoresTokenOnlyEncryptedStoreAndNeverPassword() {
        val (s, _, secure) = newSession()
        s.signIn("tok123", prof("alice"))
        assertEquals("tok123", s.token()); assertTrue(s.state.value is SessionState.SignedIn)
        assertTrue(secure.keys().none { it.contains("password", true) }); assertTrue(secure.keys().all { secure.get(it)?.contains("pass") != true })
    }
    @Test fun signOutClearsTokenProfileAndCache() {
        val (s, cache, secure) = newSession()
        s.signIn("tok", prof("alice")); cache.put(CacheKeys.forUser("alice", "lookup"), listOf("secret"))
        s.signOut()
        assertNull(s.token()); assertNull(s.storedProfile()); assertTrue(secure.keys().isEmpty())
        assertNull(cache.get<List<String>>(CacheKeys.forUser("alice", "lookup"), CacheStore.typeOf<List<String>>()))
        assertTrue(s.state.value is SessionState.SignedOut)
    }
    @Test fun switchingAccountWipesPreviousUsersCache() {
        val (s, cache, _) = newSession()
        s.signIn("t1", prof("alice")); cache.put(CacheKeys.forUser("alice", "results"), listOf("A grade"))
        s.signIn("t2", prof("bob"))
        assertNull(cache.get<List<String>>(CacheKeys.forUser("alice", "results"), CacheStore.typeOf<List<String>>()))
    }
    @Test fun expiryWithStaleTokenIsIgnoredButCurrentTokenEndsSession() {
        val (s, _, _) = newSession()
        s.signIn("new", prof("alice"))
        s.expire("old-token"); assertTrue(s.state.value is SessionState.SignedIn)
        s.expire("new"); val st = s.state.value
        assertTrue(st is SessionState.SignedOut && st.notice != null); assertNull(s.token())
    }
    @Test fun cacheRoundTripAndPerUserSeparation() {
        val c = CacheStore(InMemoryStore(), clock = { 1234L })
        c.put(CacheKeys.forUser("alice", "x"), listOf(1, 2))
        assertEquals(listOf(1, 2) to 1234L, c.get<List<Int>>(CacheKeys.forUser("alice", "x"), CacheStore.typeOf<List<Int>>()))
        assertNull(c.get<List<Int>>(CacheKeys.forUser("bob", "x"), CacheStore.typeOf<List<Int>>()))
        c.clearForOtherUsers("bob"); assertNull(c.get<List<Int>>(CacheKeys.forUser("alice", "x"), CacheStore.typeOf<List<Int>>()))
    }
}

class ReadThroughTest {
    private val type = CacheStore.typeOf<List<String>>()
    private fun setup(): Triple<SessionManager, CacheStore, ReadThrough> {
        val cache = CacheStore(InMemoryStore()); val s = SessionManager(InMemoryStore(), cache)
        s.signIn("t", UserProfile("alice", Role.STUDENT, "Student", null, null, false, null, null))
        return Triple(s, cache, ReadThrough(s, cache))
    }
    @Test fun successCachesThenOfflineServesStaleCopy() = runBlocking {
        val (_, _, rt) = setup()
        val ok = rt.load("n", type) { ApiResult.Success(listOf("a")) } as ApiResult.Success
        assertFalse(ok.value.fromCache)
        val off = rt.load<List<String>>("n", type) { ApiResult.Failure(ErrorMapper.network(false)) } as ApiResult.Success
        assertTrue(off.value.isStale); assertEquals(listOf("a"), off.value.data)
    }
    @Test fun authAndPermissionErrorsNeverFallBackToCache() = runBlocking {
        val (_, _, rt) = setup()
        rt.load("n", type) { ApiResult.Success(listOf("a")) }
        assertTrue(rt.load<List<String>>("n", type) { ApiResult.Failure(ErrorMapper.fromHttp(401, null)) } is ApiResult.Failure)
        assertTrue(rt.load<List<String>>("n", type) { ApiResult.Failure(ErrorMapper.fromHttp(403, null)) } is ApiResult.Failure)
    }
    @Test fun nothingServedOrWrittenAfterLogout() = runBlocking {
        val (s, _, rt) = setup()
        rt.load("n", type) { ApiResult.Success(listOf("a")) }
        s.signOut()
        assertNull(rt.peek<List<String>>("n", type))
        assertTrue(rt.load<List<String>>("n", type) { ApiResult.Failure(ErrorMapper.network(false)) } is ApiResult.Failure)
    }
    @Test fun responseArrivingAfterLogoutIsNotCached() = runBlocking {
        val (s, _, rt) = setup()
        rt.load("n", type) { s.signOut(); ApiResult.Success(listOf("late")) }
        assertNull(rt.peek<List<String>>("n", type))
    }
}

class RepositoryTest {
    private fun signedInStudent(api: ExamApi, reg: String? = "990025106001"): Triple<SessionManager, ReadThrough, CacheStore> {
        val cache = CacheStore(InMemoryStore()); val s = SessionManager(InMemoryStore(), cache)
        s.signIn("t", UserProfile("stud1", Role.STUDENT, "Student", null, null, false, reg, null))
        return Triple(s, ReadThrough(s, cache), cache)
    }

    @Test fun loginStoresSessionAndRoleComesFromServerProfile() = runBlocking {
        val calls = mutableListOf<String>()
        val api = fakeApi(calls, "login" to { _ -> Response.success(LoginResponseDto("TOKEN", "bearer", "student", "stud1", "Student", false, 3600)) },
            "profileWithToken" to { a -> assertEquals("Bearer TOKEN", a[0]); Response.success(studentProfile()) })
        val s = SessionManager(InMemoryStore(), CacheStore(InMemoryStore()))
        val r = AuthRepository(api, s).login("stud1", "Sturdy-Pass-2026-xyz")
        assertTrue(r is ApiResult.Success); assertEquals("TOKEN", s.token()); assertEquals(Role.STUDENT, s.currentProfile()?.role)
    }
    @Test fun wrongPasswordDoesNotCreateASession() = runBlocking {
        val api = fakeApi(mutableListOf(), "login" to { _ -> err(401, """{"detail":"Incorrect username or password"}""") })
        val s = SessionManager(InMemoryStore(), CacheStore(InMemoryStore()))
        val r = AuthRepository(api, s).login("stud1", "nope") as ApiResult.Failure
        assertEquals(ErrorKind.UNAUTHORIZED, r.failure.kind); assertEquals("Incorrect username or password", r.failure.message); assertNull(s.token())
    }
    @Test fun emptyCredentialsNeverReachTheNetwork() = runBlocking {
        val s = SessionManager(InMemoryStore(), CacheStore(InMemoryStore()))
        assertTrue(AuthRepository(fakeApi(), s).login("", "x") is ApiResult.Failure)
    }
    @Test fun logoutClearsLocallyEvenWhenServerUnreachable() = runBlocking {
        val api = fakeApi(mutableListOf(), "logout" to { _ -> throw IOException("offline") })
        val (s, _, _) = signedInStudent(api)
        assertFalse(AuthRepository(api, s).logout()); assertNull(s.token()); assertTrue(s.state.value is SessionState.SignedOut)
    }
    @Test fun studentLookupUsesOnlyTheSignedInRegisterNumber() = runBlocking {
        val calls = mutableListOf<String>()
        val api = fakeApi(calls, "lookup" to { a -> Response.success(LookupDto(StudentCardDto(a[0] as String, "ECE", 2), emptyList())) })
        val (s, rt, _) = signedInStudent(api)
        val r = StudentRepository(api, s, rt).myLookup()
        assertTrue(r is ApiResult.Success); assertEquals(listOf("lookup(990025106001)"), calls)
    }
    @Test fun unlinkedStudentMakesNoRequests() = runBlocking {
        val calls = mutableListOf<String>(); val api = fakeApi(calls)
        val (s, rt, _) = signedInStudent(api, reg = null)
        val r = StudentRepository(api, s, rt).myResults() as ApiResult.Failure
        assertEquals(ErrorKind.FORBIDDEN, r.failure.kind); assertTrue(calls.isEmpty())
    }
    @Test fun staffAccountCannotUseStudentRepository() = runBlocking {
        val cache = CacheStore(InMemoryStore()); val s = SessionManager(InMemoryStore(), cache)
        s.signIn("t", UserProfile("adm", Role.ADMIN, "Admin", null, null, false, "990025106001", null))
        val api = fakeApi()
        assertTrue(StudentRepository(api, s, ReadThrough(s, cache)).myLookup() is ApiResult.Failure)
    }
    @Test fun malformedServerDataBecomesInvalidResponseNotACrash() = runBlocking {
        val api = fakeApi(mutableListOf(), "lookup" to { _ -> Response.success(LookupDto(null, null)) })
        val (s, rt, _) = signedInStudent(api)
        val r = StudentRepository(api, s, rt).myLookup() as ApiResult.Failure
        assertEquals(ErrorKind.INVALID_RESPONSE, r.failure.kind)
    }
    @Test fun notificationReadUpdatesUnreadBadgeFromServerCount() = runBlocking {
        val api = fakeApi(mutableListOf(),
            "markRead" to { _ -> Response.success(NotificationDto(5, "exam", "Examinations", "normal", "T", "B", null, "2026-11-14T07:00:00+00:00", true, false, unread = 2)) },
            "unreadCount" to { _ -> Response.success(UnreadDto(4)) })
        val repo = NotificationRepository(api)
        repo.refreshUnread(); assertEquals(4, repo.unread.value)
        val r = repo.markRead(5); assertTrue(r is ApiResult.Success && (r.value.read)); assertEquals(2, repo.unread.value)
        repo.clear(); assertEquals(0, repo.unread.value)
    }
    @Test fun notificationPagingReadsTotalHeader() = runBlocking {
        val api = fakeApi(mutableListOf(), "notifications" to { _ ->
            Response.success(listOf(NotificationDto(1, "exam", "E", "normal", "T", "B", null, "x", false, false)),
                okhttp3.Headers.headersOf("X-Total-Count", "40")) })
        val p = NotificationRepository(api).page(false, 0) as ApiResult.Success
        assertEquals(40, p.value.total); assertEquals(1, p.value.items.size)
    }
    @Test fun forcedPasswordChangeSwapsTokenAndClearsFlag() = runBlocking {
        var n = 0
        val api = fakeApi(mutableListOf(), "changePassword" to { _ -> Response.success(ChangePasswordResponseDto("NEWTOKEN", "ok")) },
            "profile" to { _ -> n++; Response.success(studentProfile()) })
        val (s, _, _) = signedInStudent(api)
        val r = AuthRepository(api, s).changePassword("Old-Password-2026x", "Brand-New-Pass-2027")
        assertTrue(r is ApiResult.Success); assertEquals("NEWTOKEN", s.token()); assertEquals(1, n)
    }
    @Test fun weakNewPasswordIsRejectedLocallyWithoutARequest() = runBlocking {
        val calls = mutableListOf<String>(); val api = fakeApi(calls)
        val (s, _, _) = signedInStudent(api)
        assertTrue(AuthRepository(api, s).changePassword("Old-Password-2026x", "short") is ApiResult.Failure); assertTrue(calls.isEmpty())
    }
}

class InterceptorTest {
    private fun client(token: String? = "TKN", onUnauth: (String?) -> Unit = {}) = OkHttpClient.Builder()
        .addInterceptor(AuthInterceptor { token }).addInterceptor(GetRetryInterceptor(2) { }).addInterceptor(UnauthorizedInterceptor(onUnauth)).build()

    @Test fun loginRequestNeverCarriesATokenButOthersDo() {
        MockWebServer().use { srv ->
            srv.enqueue(MockResponse().setBody("{}")); srv.enqueue(MockResponse().setBody("{}"))
            client().newCall(okhttp3.Request.Builder().url(srv.url("/api/auth/login")).post(okhttp3.RequestBody.create(null, "{}")).build()).execute().close()
            client().newCall(okhttp3.Request.Builder().url(srv.url("/api/exams")).build()).execute().close()
            assertNull(srv.takeRequest().getHeader("Authorization")); assertEquals("Bearer TKN", srv.takeRequest().getHeader("Authorization"))
        }
    }
    @Test fun getIsRetriedAfterConnectionDropButPostIsNot() {
        MockWebServer().use { srv ->
            srv.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START)); srv.enqueue(MockResponse().setBody("ok"))
            val ok = client().newCall(okhttp3.Request.Builder().url(srv.url("/api/exams")).build()).execute()
            assertEquals(200, ok.code); ok.close(); assertEquals(2, srv.requestCount)
        }
        MockWebServer().use { srv ->
            srv.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START)); srv.enqueue(MockResponse().setBody("ok"))
            val c = OkHttpClient.Builder().retryOnConnectionFailure(false).addInterceptor(GetRetryInterceptor(2) { }).build()
            try { c.newCall(okhttp3.Request.Builder().url(srv.url("/api/x")).post(okhttp3.RequestBody.create(null, "{}")).build()).execute(); fail("expected IOException") } catch (e: IOException) { }
            assertEquals(1, srv.requestCount)
        }
    }
    @Test fun a401OnAnAuthenticatedCallReportsTheUsedToken() {
        MockWebServer().use { srv ->
            srv.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Session timed out. Sign in again."}"""))
            var seen: String? = null
            client(onUnauth = { seen = it }).newCall(okhttp3.Request.Builder().url(srv.url("/api/notifications")).build()).execute().close()
            assertEquals("TKN", seen)
        }
    }
    @Test fun a401OnLoginDoesNotExpireTheSession() {
        MockWebServer().use { srv ->
            srv.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Incorrect username or password"}"""))
            var called = false
            client(onUnauth = { called = true }).newCall(okhttp3.Request.Builder().url(srv.url("/api/auth/login")).post(okhttp3.RequestBody.create(null, "{}")).build()).execute().close()
            assertFalse(called)
        }
    }
    @Test fun detailExtractorHandlesFastApiShapes() {
        assertEquals("plain", DetailExtractor.fromBody("""{"detail":"plain"}"""))
        assertEquals("a; b", DetailExtractor.fromBody("""{"detail":[{"msg":"a"},{"msg":"b"}]}"""))
        assertEquals("m", DetailExtractor.fromBody("""{"detail":{"message":"m"}}"""))
        assertNull(DetailExtractor.fromBody("<html>")); assertNull(DetailExtractor.fromBody(null))
    }
}
