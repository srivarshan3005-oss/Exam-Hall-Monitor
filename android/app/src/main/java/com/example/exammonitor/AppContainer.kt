package com.example.exammonitor

import android.app.Application
import android.content.Context
import com.example.exammonitor.core.ApiUrl
import com.example.exammonitor.core.SessionState
import com.example.exammonitor.core.UrlCheck
import com.example.exammonitor.data.*
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/** Everything that talks to the backend for one server address. Rebuilt only when the address changes (signed out). */
class Services(val api: ExamApi, val auth: AuthRepository, val student: StudentRepository, val exams: ExamRepository,
               val announcements: AnnouncementRepository, val staff: StaffRepository, val notifications: NotificationRepository,
               val integration: IntegrationRepository)

class AppContainer(context: Context) {
    val settings = SettingsStore(context)
    private val secure = EncryptedPrefsStore(context, "em_secure")
    private val cacheStore = CacheStore(EncryptedPrefsStore(context, "em_cache"))
    val session = SessionManager(secure, cacheStore)
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    @Volatile var baseUrl: String = initialUrl()
        private set
    @Volatile var services: Services = build(baseUrl)
        private set

    init {
        // Notification state belongs to a session: drop the badge as soon as nobody is signed in.
        scope.launch { session.state.collect { if (it !is SessionState.SignedIn) services.notifications.clear() } }
    }

    private fun initialUrl(): String {
        val saved = settings.serverUrl
        if (saved != null && ApiUrl.check(saved, BuildConfig.ALLOW_CLEARTEXT) is UrlCheck.Ok) return (ApiUrl.check(saved, BuildConfig.ALLOW_CLEARTEXT) as UrlCheck.Ok).baseUrl
        return BuildConfig.DEFAULT_API_URL
    }

    private fun build(url: String): Services {
        val api = ApiClientFactory.create(url, token = { session.token() }, onUnauthorized = { used -> session.expire(used) })
        val rt = ReadThrough(session, cacheStore)
        return Services(api, AuthRepository(api, session), StudentRepository(api, session, rt), ExamRepository(api, rt),
            AnnouncementRepository(api, rt), StaffRepository(api, rt), NotificationRepository(api), IntegrationRepository(api))
    }

    /** Returns null on success, or a user-readable reason. Only allowed while signed out. */
    fun changeServer(raw: String): String? {
        if (session.state.value is SessionState.SignedIn) return "Sign out before changing the server."
        return when (val c = ApiUrl.check(raw, BuildConfig.ALLOW_CLEARTEXT)) {
            is UrlCheck.Rejected -> c.reason
            is UrlCheck.Ok -> { settings.serverUrl = c.baseUrl; baseUrl = c.baseUrl; services = build(c.baseUrl); null }
        }
    }
}

class ExamMonitorApp : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }
}
