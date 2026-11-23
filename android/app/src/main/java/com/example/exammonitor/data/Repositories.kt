package com.example.exammonitor.data

import com.example.exammonitor.core.*
import com.google.gson.JsonParseException
import com.google.gson.JsonObject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import retrofit2.Response
import java.io.IOException
import java.net.SocketTimeoutException

/** Converts a Retrofit call into an [ApiResult]: HTTP errors, timeouts, offline and malformed bodies never escape as exceptions. */
internal suspend fun <T> apiCall(block: suspend () -> Response<T>): ApiResult<Response<T>> = try {
    val r = block()
    if (r.isSuccessful) ApiResult.Success(r)
    else ApiResult.Failure(DetailExtractor.failure(r.code(), runCatching { r.errorBody()?.string() }.getOrNull(), r.headers()["Retry-After"]))
} catch (e: CancellationException) { throw e }
catch (e: SocketTimeoutException) { ApiResult.Failure(ErrorMapper.network(timeout = true)) }
catch (e: IOException) { ApiResult.Failure(ErrorMapper.network(timeout = false)) }
catch (e: JsonParseException) { ApiResult.Failure(ErrorMapper.invalid("unreadable body")) }
catch (e: IllegalStateException) { ApiResult.Failure(ErrorMapper.invalid("unreadable body")) }

internal inline fun <T, R> ApiResult<Response<T>>.body(transform: (T?) -> R): ApiResult<R> = when (this) {
    is ApiResult.Failure -> this
    is ApiResult.Success -> try { ApiResult.Success(transform(value.body())) }
    catch (e: InvalidResponseException) { ApiResult.Failure(ErrorMapper.invalid(e.message ?: "invalid")) }
}

internal inline fun <T, R> ApiResult<Response<T>>.bodyWithResponse(transform: (T?, Response<T>) -> R): ApiResult<R> = when (this) {
    is ApiResult.Failure -> this
    is ApiResult.Success -> try { ApiResult.Success(transform(value.body(), value)) }
    catch (e: InvalidResponseException) { ApiResult.Failure(ErrorMapper.invalid(e.message ?: "invalid")) }
}

/**
 * Network-first, cache-fallback for safe read-only data. A successful fetch refreshes the cache; a connectivity/server
 * failure falls back to the user's own cached copy and marks it stale. Nothing is cached or served without a signed-in user,
 * and nothing is written if the session changed while the request was in flight.
 */
class ReadThrough(private val session: SessionManager, private val cache: CacheStore, private val clock: () -> Long = System::currentTimeMillis) {
    suspend fun <T> load(name: String, type: java.lang.reflect.Type, fetch: suspend () -> ApiResult<T>): ApiResult<Loaded<T>> {
        val user = session.currentProfile()?.username
        val tokenAtStart = session.token()
        return when (val r = fetch()) {
            is ApiResult.Success -> {
                if (user != null && session.token() == tokenAtStart && session.token() != null) cache.put(CacheKeys.forUser(user, name), r.value)
                ApiResult.Success(Loaded(r.value, clock(), fromCache = false))
            }
            is ApiResult.Failure -> {
                val hit = if (user != null && session.token() != null && ErrorMapper.allowsCacheFallback(r.failure))
                    cache.get<T>(CacheKeys.forUser(user, name), type) else null
                if (hit != null) ApiResult.Success(Loaded(hit.first, hit.second, fromCache = true, staleReason = r.failure)) else r
            }
        }
    }

    /** Instant, offline read for first paint. Returns null when nothing is cached for the signed-in user. */
    fun <T> peek(name: String, type: java.lang.reflect.Type): Loaded<T>? {
        val user = session.currentProfile()?.username ?: return null
        val hit = cache.get<T>(CacheKeys.forUser(user, name), type) ?: return null
        return Loaded(hit.first, hit.second, fromCache = true, staleReason = null)
    }
}

class AuthRepository(private val api: ExamApi, private val session: SessionManager) {
    suspend fun login(username: String, password: String): ApiResult<UserProfile> {
        LoginValidation.problem(username, password)?.let { return ApiResult.Failure(ApiFailure(ErrorKind.VALIDATION, it)) }
        val login = apiCall { api.login(LoginRequest(username.trim(), password)) }
        val token = when (login) {
            is ApiResult.Failure -> return login
            is ApiResult.Success -> login.value.body()?.access_token?.takeIf { it.isNotBlank() }
                ?: return ApiResult.Failure(ErrorMapper.invalid("missing token"))
        }
        val prof = apiCall { api.profileWithToken("Bearer $token") }.body { Mappers.profile(it) }
        return when (prof) {
            is ApiResult.Failure -> prof
            is ApiResult.Success -> {
                if (Role.fromApi(prof.value.role.api) == null)
                    ApiResult.Failure(ApiFailure(ErrorKind.FORBIDDEN, "This account type is not supported in the app."))
                else { session.signIn(token, prof.value); prof }
            }
        }
    }

    /** App start: validate the stored token. Offline start is allowed with the saved profile (cached data only). */
    suspend fun restore() {
        if (!session.hasStoredToken()) { session.markSignedOut(); return }
        when (val r = apiCall { api.profile() }.body { Mappers.profile(it) }) {
            is ApiResult.Success -> session.updateProfile(r.value)
            is ApiResult.Failure -> when (r.failure.kind) {
                ErrorKind.UNAUTHORIZED -> session.signOut("Your session has ended. Please sign in again.")
                ErrorKind.PASSWORD_CHANGE_REQUIRED -> session.storedProfile()?.let { session.updateProfile(it.copy(passwordChangeRequired = true)) }
                    ?: session.signOut("Please sign in again.")
                else -> session.storedProfile()?.let { session.updateProfile(it) } ?: session.signOut("Could not reach the server. Sign in when you are online.")
            }
        }
    }

    /** Ends the server session (best effort), then always forgets everything on this device. Returns true if the server confirmed. */
    suspend fun logout(): Boolean {
        val confirmed = session.token() != null && apiCall { api.logout() } is ApiResult.Success
        session.signOut(null)
        return confirmed
    }

    suspend fun changePassword(current: String, new: String): ApiResult<Unit> {
        val user = session.currentProfile()?.username
        PasswordPolicy.problems(new, user).firstOrNull()?.let { return ApiResult.Failure(ApiFailure(ErrorKind.VALIDATION, it)) }
        if (new == current) return ApiResult.Failure(ApiFailure(ErrorKind.VALIDATION, "The new password must differ from the current one."))
        return when (val r = apiCall { api.changePassword(ChangePasswordRequest(current, new)) }) {
            is ApiResult.Failure -> r
            is ApiResult.Success -> {
                val newToken = r.value.body()?.access_token?.takeIf { it.isNotBlank() }
                    ?: return ApiResult.Failure(ErrorMapper.invalid("missing token"))
                session.updateToken(newToken)     // the old token was revoked by the server
                when (val p = apiCall { api.profile() }.body { Mappers.profile(it) }) {
                    is ApiResult.Success -> { session.updateProfile(p.value); ApiResult.Success(Unit) }
                    is ApiResult.Failure -> p
                }
            }
        }
    }

    suspend fun forgotPassword(identifier: String): ApiResult<String> {
        if (identifier.trim().length < 3) return ApiResult.Failure(ApiFailure(ErrorKind.VALIDATION, "Enter your username or e-mail address."))
        return apiCall { api.forgotPassword(ForgotRequest(identifier.trim())) }.body { it?.detail ?: "If an active account matches, a reset link has been e-mailed." }
    }

    suspend fun resetPassword(tokenOrLink: String, newPassword: String): ApiResult<String> {
        val token = ResetTokenParser.extract(tokenOrLink)
            ?: return ApiResult.Failure(ApiFailure(ErrorKind.VALIDATION, "Paste the reset link (or code) from the e-mail."))
        PasswordPolicy.problems(newPassword).firstOrNull()?.let { return ApiResult.Failure(ApiFailure(ErrorKind.VALIDATION, it)) }
        return apiCall { api.resetPassword(ResetRequest(token, newPassword)) }.body { it?.detail ?: "Password updated. Sign in with the new password." }
    }
}

/** Student-only data. The register number always comes from the signed-in profile, never from a parameter. */
class StudentRepository(private val api: ExamApi, private val session: SessionManager, private val cache: ReadThrough) {
    private fun ownRegister(): String? = session.currentProfile()?.takeIf { it.role == Role.STUDENT }?.registerNumber

    private fun notLinked() = ApiResult.Failure(ApiFailure(ErrorKind.FORBIDDEN,
        "Your account is not linked to a student record yet. Ask the examination office to link it."))

    suspend fun myLookup(): ApiResult<Loaded<StudentLookup>> {
        val reg = ownRegister() ?: return notLinked()
        return cache.load("lookup", CacheStore.typeOf<StudentLookup>()) { apiCall { api.lookup(reg) }.body { Mappers.lookup(it) } }
    }

    suspend fun myResults(): ApiResult<Loaded<List<ResultItem>>> {
        val reg = ownRegister() ?: return notLinked()
        return cache.load("results", CacheStore.typeOf<List<ResultItem>>()) {
            apiCall { api.results(reg) }.body { list -> (list ?: throw InvalidResponseException("results")).map { Mappers.result(it) } }
        }
    }

    fun peekLookup() = cache.peek<StudentLookup>("lookup", CacheStore.typeOf<StudentLookup>())
    fun peekResults() = cache.peek<List<ResultItem>>("results", CacheStore.typeOf<List<ResultItem>>())
}

class ExamRepository(private val api: ExamApi, private val cache: ReadThrough) {
    suspend fun published(): ApiResult<Loaded<List<Exam>>> = cache.load("exams-published", CacheStore.typeOf<List<Exam>>()) {
        apiCall { api.publishedExams() }.body { l -> (l ?: throw InvalidResponseException("exams")).map { Mappers.exam(it) } }
    }

    /** Staff/invigilator list. Cached only for the default (unfiltered, first page) view. */
    suspend fun adminList(query: String, status: String): ApiResult<Loaded<List<Exam>>> {
        val fetch: suspend () -> ApiResult<List<Exam>> = {
            apiCall { api.adminExams(query, status, 100, 0) }.body { l -> (l ?: throw InvalidResponseException("exams")).map { Mappers.exam(it) } }
        }
        return if (query.isBlank() && status.isBlank()) cache.load("exams-admin", CacheStore.typeOf<List<Exam>>(), fetch)
        else when (val r = fetch()) { is ApiResult.Success -> ApiResult.Success(Loaded(r.value, System.currentTimeMillis(), false)); is ApiResult.Failure -> r }
    }

    suspend fun summary(id: Int): ApiResult<ExamSummary> = apiCall { api.examSummary(id) }.body { Mappers.summary(it) }
    suspend fun halls(id: Int): ApiResult<List<HallOccupancy>> =
        apiCall { api.examHalls(id) }.body { l -> (l ?: throw InvalidResponseException("halls")).map { Mappers.hall(it) } }
    suspend fun roster(id: Int, query: String, offset: Int): ApiResult<List<RosterEntry>> =
        apiCall { api.examRoster(id, query, PAGE, offset) }.body { l -> (l ?: throw InvalidResponseException("roster")).map { Mappers.roster(it) } }

    /** Backend validates (past dates, venue conflicts); we never retry automatically. */
    suspend fun setPublished(id: Int, publish: Boolean): ApiResult<Exam> =
        apiCall { if (publish) api.publishExam(id) else api.unpublishExam(id) }.body { Mappers.exam(it) }

    companion object { const val PAGE = 200 }
}

class AnnouncementRepository(private val api: ExamApi, private val cache: ReadThrough) {
    suspend fun list(): ApiResult<Loaded<List<Announcement>>> = cache.load("announcements", CacheStore.typeOf<List<Announcement>>()) {
        apiCall { api.announcements() }.body { l -> (l ?: throw InvalidResponseException("announcements")).map { Mappers.announcement(it) } }
    }
}

class StaffRepository(private val api: ExamApi, private val cache: ReadThrough) {
    suspend fun dashboard(): ApiResult<Loaded<DashboardStats>> = cache.load("dashboard", CacheStore.typeOf<DashboardStats>()) {
        apiCall { api.dashboard() }.body { Mappers.dashboard(it) }
    }

    /** Lookup is never cached: it returns other people's records. */
    suspend fun studentSeats(query: String): ApiResult<List<StaffStudentSeats>> {
        val q = query.trim()
        if (q.length < 2) return ApiResult.Failure(ApiFailure(ErrorKind.VALIDATION, "Type at least 2 characters of a register number or name."))
        return apiCall { api.studentSeats(q) }.body { l -> (l ?: throw InvalidResponseException("students")).map { Mappers.staffStudent(it) } }
    }
}

class NotificationRepository(private val api: ExamApi) {
    private val _unread = MutableStateFlow(0)
    val unread: StateFlow<Int> = _unread.asStateFlow()

    /** Notifications are per-user live data and are deliberately not cached to disk. */
    suspend fun page(unreadOnly: Boolean, offset: Int, limit: Int = PAGE): ApiResult<NotificationPage> =
        apiCall { api.notifications(if (unreadOnly) "unread" else "inbox", limit, offset) }.bodyWithResponse { l, resp ->
            val items = (l ?: throw InvalidResponseException("notifications")).map { Mappers.notification(it) }
            val total = resp.headers()["X-Total-Count"]?.toIntOrNull() ?: (offset + items.size)
            NotificationPage(items, total)
        }

    suspend fun refreshUnread(): ApiResult<Int> = apiCall { api.unreadCount() }.body { (it?.unread ?: throw InvalidResponseException("unread")) }
        .also { if (it is ApiResult.Success) _unread.value = it.value }

    suspend fun get(id: Int): ApiResult<AppNotification> = apiCall { api.notification(id) }.body { Mappers.notification(it) }

    suspend fun markRead(id: Int) = update { api.markRead(id) }
    suspend fun markUnread(id: Int) = update { api.markUnread(id) }
    suspend fun archive(id: Int) = update { api.archive(id) }

    private suspend fun update(call: suspend () -> Response<NotificationDto>): ApiResult<AppNotification> =
        apiCall { call() }.body { d ->
            Mappers.notification(d).also { d?.unread?.let { n -> _unread.value = n.coerceAtLeast(0) } }
        }

    suspend fun markAllRead(): ApiResult<Int> = apiCall { api.readAll() }.body { (it?.unread ?: 0) }
        .also { if (it is ApiResult.Success) _unread.value = it.value }

    suspend fun preferences(): ApiResult<Preferences> = apiCall { api.preferences() }.body { Mappers.preferences(it) }
    suspend fun savePreferences(items: List<PreferenceItem>): ApiResult<Preferences> =
        apiCall { api.updatePreferences(PreferencesUpdateRequest(items.map { PreferenceUpdate(it.category, it.inApp, it.email) })) }
            .body { Mappers.preferences(it) }

    fun clear() { _unread.value = 0 }
    fun setUnread(n: Int) { _unread.value = n.coerceAtLeast(0) }

    companion object { const val PAGE = 25 }
}


/** Phase 11 cross-module endpoints. Responses stay structured JSON so the app can render
 * newly added aggregate fields without losing compatibility with older server releases. */
class IntegrationRepository(private val api: ExamApi) {
    suspend fun overview(): ApiResult<JsonObject> = apiCall { api.integrationOverview() }.body {
        it ?: throw InvalidResponseException("integration overview")
    }
    suspend fun examReadiness(examId: Int): ApiResult<JsonObject> {
        if (examId <= 0) return ApiResult.Failure(ApiFailure(ErrorKind.VALIDATION, "Choose a valid examination."))
        return apiCall { api.examWorkflowReadiness(examId) }.body { it ?: throw InvalidResponseException("exam workflow") }
    }
    suspend fun myAnalytics(): ApiResult<JsonObject> = apiCall { api.myAnalytics() }.body {
        it ?: throw InvalidResponseException("student analytics")
    }
}
