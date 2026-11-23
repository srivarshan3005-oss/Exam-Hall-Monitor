package com.example.exammonitor.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.viewModelScope
import com.example.exammonitor.AppContainer
import com.example.exammonitor.core.*
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ScreenState<T>(val loading: Boolean = false, val refreshing: Boolean = false,
                          val data: Loaded<T>? = null, val error: ApiFailure? = null)

/** One in-flight load at a time (a second tap or a rapid pull-to-refresh is ignored, not duplicated). */
class LoadController<T>(private val scope: CoroutineScope, private val peek: () -> Loaded<T>?,
                        private val fetch: suspend () -> ApiResult<Loaded<T>>) {
    private val _state = MutableStateFlow(ScreenState<T>(loading = true, data = peek()))
    val state: StateFlow<ScreenState<T>> = _state.asStateFlow()
    @Volatile private var running = false

    fun load(refresh: Boolean = false) {
        if (running) return
        running = true
        _state.update { it.copy(loading = it.data == null && !refresh, refreshing = refresh || it.data != null, error = null) }
        scope.launch {
            try {
                when (val r = fetch()) {
                    is ApiResult.Success -> _state.value = ScreenState(data = r.value)
                    is ApiResult.Failure -> _state.update { it.copy(loading = false, refreshing = false, error = r.failure) }
                }
            } finally { running = false }
        }
    }

    fun setData(newData: T) = _state.update { s -> s.data?.let { s.copy(data = it.copy(data = newData)) } ?: s }
}

class AppViewModel(private val c: AppContainer) : ViewModel() {
    val session = c.session.state
    val baseUrl: String get() = c.baseUrl
    private val _toast = MutableStateFlow<String?>(null)
    val toast: StateFlow<String?> = _toast.asStateFlow()
    @Volatile private var restoreStarted = false

    /**
     * Holds every ViewModel that contains private data (timetable, results, notifications...). It survives rotation but is
     * emptied the moment nobody is signed in, so a later account on the same device can never see the previous user's state.
     */
    val privateStore = ViewModelStore()

    init {
        viewModelScope.launch { c.session.state.collect { if (it !is SessionState.SignedIn) privateStore.clear() } }
    }

    fun restore() {
        if (restoreStarted) return
        restoreStarted = true
        viewModelScope.launch { c.services.auth.restore() }
    }

    fun logout() = viewModelScope.launch {
        val confirmed = c.services.auth.logout()
        _toast.value = if (confirmed) "Signed out." else "Signed out on this device. The server could not be reached; the session will expire on its own."
    }

    fun consumeToast() { _toast.value = null }
    var themeMode: String
        get() = c.settings.themeMode
        set(v) { c.settings.themeMode = v; _theme.value = v }
    private val _theme = MutableStateFlow(c.settings.themeMode)
    val theme: StateFlow<String> = _theme.asStateFlow()
}

class LoginViewModel(private val c: AppContainer) : ViewModel() {
    data class UiState(val busy: Boolean = false, val error: String? = null, val serverUrl: String = "", val serverMessage: String? = null)
    private val _ui = MutableStateFlow(UiState(serverUrl = c.baseUrl))
    val ui: StateFlow<UiState> = _ui.asStateFlow()

    fun saveServer(raw: String) {
        val problem = c.changeServer(raw)
        _ui.update { it.copy(serverMessage = problem ?: "Server address saved.", serverUrl = if (problem == null) c.baseUrl else raw) }
    }

    fun login(username: String, password: String) {
        if (_ui.value.busy) return                   // no duplicate submissions
        _ui.update { it.copy(busy = true, error = null) }
        viewModelScope.launch {
            when (val r = c.services.auth.login(username, password)) {
                is ApiResult.Success -> _ui.update { it.copy(busy = false) }          // session flow navigates
                is ApiResult.Failure -> _ui.update { it.copy(busy = false, error = r.failure.message) }
            }
        }
    }
}

class RecoveryViewModel(private val c: AppContainer) : ViewModel() {
    data class UiState(val busy: Boolean = false, val error: String? = null, val info: String? = null, val done: Boolean = false)
    private val _ui = MutableStateFlow(UiState())
    val ui: StateFlow<UiState> = _ui.asStateFlow()

    fun requestLink(identifier: String) = run { c.services.auth.forgotPassword(identifier) }
    fun reset(linkOrToken: String, password: String) = run { c.services.auth.resetPassword(linkOrToken, password) }

    private fun run(call: suspend () -> ApiResult<String>) {
        if (_ui.value.busy) return
        _ui.update { UiState(busy = true) }
        viewModelScope.launch {
            _ui.value = when (val r = call()) {
                is ApiResult.Success -> UiState(info = r.value, done = true)
                is ApiResult.Failure -> UiState(error = r.failure.message)
            }
        }
    }
    fun clear() { _ui.value = UiState() }
}

class ChangePasswordViewModel(private val c: AppContainer) : ViewModel() {
    data class UiState(val busy: Boolean = false, val error: String? = null, val success: Boolean = false)
    private val _ui = MutableStateFlow(UiState())
    val ui: StateFlow<UiState> = _ui.asStateFlow()

    fun submit(current: String, new: String, confirm: String) {
        if (_ui.value.busy) return
        if (new != confirm) { _ui.value = UiState(error = "The new passwords do not match."); return }
        _ui.value = UiState(busy = true)
        viewModelScope.launch {
            _ui.value = when (val r = c.services.auth.changePassword(current, new)) {
                is ApiResult.Success -> UiState(success = true)
                is ApiResult.Failure -> UiState(error = r.failure.message)
            }
        }
    }
}

class HomeViewModel(private val c: AppContainer) : ViewModel() {
    private val s get() = c.services
    val notices = LoadController(viewModelScope, { null }) { s.announcements.list() }
    val lookup = LoadController(viewModelScope, { s.student.peekLookup() }) { s.student.myLookup() }
    val stats = LoadController(viewModelScope, { null }) { s.staff.dashboard() }
    val exams = LoadController(viewModelScope, { null }) { s.exams.published() }
    val unread = c.services.notifications.unread

    fun load(role: Role, refresh: Boolean) {
        notices.load(refresh); exams.load(refresh)
        if (Permissions.can(role, Capability.VIEW_OWN_TIMETABLE)) lookup.load(refresh)
        if (Permissions.can(role, Capability.VIEW_DASHBOARD_STATS)) stats.load(refresh)
        viewModelScope.launch { s.notifications.refreshUnread() }
    }
}

class TimetableViewModel(private val c: AppContainer) : ViewModel() {
    val lookup = LoadController(viewModelScope, { c.services.student.peekLookup() }) { c.services.student.myLookup() }
    val exams = LoadController(viewModelScope, { null }) { c.services.exams.published() }
    fun load(refresh: Boolean = false) { lookup.load(refresh); exams.load(refresh) }
}

class ResultsViewModel(private val c: AppContainer) : ViewModel() {
    val results = LoadController(viewModelScope, { c.services.student.peekResults() }) { c.services.student.myResults() }
}

class ExamListViewModel(private val c: AppContainer) : ViewModel() {
    data class Filter(val query: String = "", val status: String = "")
    private val _filter = MutableStateFlow(Filter())
    val filter: StateFlow<Filter> = _filter.asStateFlow()
    private val _message = MutableStateFlow<String?>(null)
    val message: StateFlow<String?> = _message.asStateFlow()
    private val _publishing = MutableStateFlow<Int?>(null)
    val publishing: StateFlow<Int?> = _publishing.asStateFlow()

    val exams = LoadController(viewModelScope, { null }) { c.services.exams.adminList(_filter.value.query.trim(), _filter.value.status) }

    fun setFilter(f: Filter) { _filter.value = f; exams.load(refresh = true) }

    /** Backend decides (past dates, venue conflicts, permissions). One request at a time; never auto-retried. */
    fun setPublished(exam: Exam, publish: Boolean) {
        if (_publishing.value != null) return
        _publishing.value = exam.id
        viewModelScope.launch {
            when (val r = c.services.exams.setPublished(exam.id, publish)) {
                is ApiResult.Success -> { _message.value = if (publish) "“${exam.title}” is now published." else "“${exam.title}” was unpublished."; exams.load(refresh = true) }
                is ApiResult.Failure -> _message.value = r.failure.message
            }
            _publishing.value = null
        }
    }
    fun consumeMessage() { _message.value = null }
}

class ExamDetailViewModel(private val c: AppContainer, private val examId: Int, private val role: Role) : ViewModel() {
    data class Detail(val summary: ExamSummary? = null, val halls: List<HallOccupancy> = emptyList(), val roster: List<RosterEntry> = emptyList(),
                      val rosterMore: Boolean = false, val notes: List<String> = emptyList())
    private val _detail = MutableStateFlow(ScreenState<Detail>(loading = true))
    val detail: StateFlow<ScreenState<Detail>> = _detail.asStateFlow()
    @Volatile private var running = false

    fun load(refresh: Boolean = false) {
        if (running) return
        running = true
        _detail.update { it.copy(loading = it.data == null, refreshing = refresh, error = null) }
        viewModelScope.launch {
            try {
                val notes = mutableListOf<String>()
                var summary: ExamSummary? = null
                var halls = emptyList<HallOccupancy>()
                var roster = emptyList<RosterEntry>()
                var firstFailure: ApiFailure? = null
                if (Permissions.can(role, Capability.VIEW_EXAM_SUMMARY)) when (val r = c.services.exams.summary(examId)) {
                    is ApiResult.Success -> summary = r.value
                    is ApiResult.Failure -> { firstFailure = firstFailure ?: r.failure; notes += "Summary: ${r.failure.message}" }
                }
                if (Permissions.can(role, Capability.VIEW_HALL_OCCUPANCY)) when (val r = c.services.exams.halls(examId)) {
                    is ApiResult.Success -> halls = r.value
                    is ApiResult.Failure -> { firstFailure = firstFailure ?: r.failure; notes += "Halls: ${r.failure.message}" }
                }
                if (Permissions.can(role, Capability.VIEW_EXAM_ALLOCATIONS)) when (val r = c.services.exams.roster(examId, "", 0)) {
                    is ApiResult.Success -> roster = r.value
                    is ApiResult.Failure -> { firstFailure = firstFailure ?: r.failure; notes += "Allocations: ${r.failure.message}" }
                }
                val allFailed = summary == null && halls.isEmpty() && roster.isEmpty() && firstFailure != null
                _detail.value = if (allFailed) ScreenState(error = firstFailure)
                else ScreenState(data = Loaded(Detail(summary, halls, roster, roster.size >= com.example.exammonitor.data.ExamRepository.PAGE, notes),
                    System.currentTimeMillis(), false))
            } finally { running = false }
        }
    }
}

class StudentSearchViewModel(private val c: AppContainer) : ViewModel() {
    data class UiState(val busy: Boolean = false, val error: ApiFailure? = null, val results: List<StaffStudentSeats>? = null, val query: String = "")
    private val _ui = MutableStateFlow(UiState())
    val ui: StateFlow<UiState> = _ui.asStateFlow()

    fun search(q: String) {
        if (_ui.value.busy) return
        _ui.update { it.copy(busy = true, error = null, query = q) }
        viewModelScope.launch {
            _ui.value = when (val r = c.services.staff.studentSeats(q)) {
                is ApiResult.Success -> UiState(results = r.value, query = q)
                is ApiResult.Failure -> UiState(error = r.failure, query = q)
            }
        }
    }
    fun clear() { _ui.value = UiState() }
}

class AlertsViewModel(private val c: AppContainer) : ViewModel() {
    data class ListState(val items: List<AppNotification> = emptyList(), val total: Int = 0, val loading: Boolean = true,
                         val refreshing: Boolean = false, val loadingMore: Boolean = false, val error: ApiFailure? = null,
                         val unreadOnly: Boolean = false, val busyIds: Set<Int> = emptySet(), val message: String? = null)
    private val repo get() = c.services.notifications
    private val _ui = MutableStateFlow(ListState())
    val ui: StateFlow<ListState> = _ui.asStateFlow()
    val unread get() = repo.unread
    val announcements = LoadController(viewModelScope, { null }) { c.services.announcements.list() }
    @Volatile private var running = false

    fun refresh(initial: Boolean = false) {
        if (running) return
        running = true
        _ui.update { it.copy(loading = initial && it.items.isEmpty(), refreshing = !initial, error = null) }
        viewModelScope.launch {
            try {
                when (val r = repo.page(_ui.value.unreadOnly, 0)) {
                    is ApiResult.Success -> _ui.update { it.copy(items = r.value.items, total = r.value.total, loading = false, refreshing = false) }
                    is ApiResult.Failure -> _ui.update { it.copy(loading = false, refreshing = false, error = r.failure) }
                }
                repo.refreshUnread()
            } finally { running = false }
        }
        announcements.load(refresh = !initial)
    }

    fun loadMore() {
        val s = _ui.value
        if (running || s.loadingMore || s.items.size >= s.total) return
        _ui.update { it.copy(loadingMore = true) }
        viewModelScope.launch {
            when (val r = repo.page(s.unreadOnly, s.items.size)) {
                is ApiResult.Success -> _ui.update { it.copy(items = NotificationLogic.merge(it.items, r.value.items), total = r.value.total, loadingMore = false) }
                is ApiResult.Failure -> _ui.update { it.copy(loadingMore = false, message = r.failure.message) }
            }
        }
    }

    fun setUnreadOnly(v: Boolean) { _ui.update { it.copy(unreadOnly = v, items = emptyList(), total = 0) }; refresh(initial = true) }

    /** Marks read/unread on the server; the list only changes after the server confirms (no optimistic duplicate writes). */
    fun setRead(n: AppNotification, read: Boolean) = act(n.id) {
        when (val r = if (read) repo.markRead(n.id) else repo.markUnread(n.id)) {
            is ApiResult.Success -> _ui.update { s -> s.copy(items = NotificationLogic.withRead(s.items, n.id, r.value.read).let { l -> if (s.unreadOnly && r.value.read) NotificationLogic.without(l, n.id) else l }) }
            is ApiResult.Failure -> _ui.update { it.copy(message = r.failure.message) }
        }
    }

    fun archive(n: AppNotification) = act(n.id) {
        when (val r = repo.archive(n.id)) {
            is ApiResult.Success -> _ui.update { it.copy(items = NotificationLogic.without(it.items, n.id), total = (it.total - 1).coerceAtLeast(0)) }
            is ApiResult.Failure -> _ui.update { it.copy(message = r.failure.message) }
        }
    }

    fun markAllRead() {
        if (_ui.value.busyIds.contains(ALL)) return
        _ui.update { it.copy(busyIds = it.busyIds + ALL) }
        viewModelScope.launch {
            when (val r = repo.markAllRead()) {
                is ApiResult.Success -> _ui.update { it.copy(items = if (it.unreadOnly) emptyList() else NotificationLogic.allRead(it.items), total = if (it.unreadOnly) 0 else it.total, message = "All notifications marked as read.") }
                is ApiResult.Failure -> _ui.update { it.copy(message = r.failure.message) }
            }
            _ui.update { it.copy(busyIds = it.busyIds - ALL) }
        }
    }

    private fun act(id: Int, block: suspend () -> Unit) {
        if (_ui.value.busyIds.contains(id)) return
        _ui.update { it.copy(busyIds = it.busyIds + id) }
        viewModelScope.launch { try { block() } finally { _ui.update { it.copy(busyIds = it.busyIds - id) } } }
    }
    fun consumeMessage() = _ui.update { it.copy(message = null) }
    private companion object { const val ALL = -1 }
}

class NotificationDetailViewModel(private val c: AppContainer, private val id: Int) : ViewModel() {
    data class UiState(val loading: Boolean = true, val item: AppNotification? = null, val error: ApiFailure? = null, val busy: Boolean = false, val closed: Boolean = false)
    private val repo get() = c.services.notifications
    private val _ui = MutableStateFlow(UiState())
    val ui: StateFlow<UiState> = _ui.asStateFlow()
    init { load() }

    fun load() {
        _ui.update { it.copy(loading = true, error = null) }
        viewModelScope.launch {
            when (val r = repo.get(id)) {
                is ApiResult.Failure -> _ui.update { it.copy(loading = false, error = r.failure) }
                is ApiResult.Success -> {
                    _ui.update { it.copy(loading = false, item = r.value) }
                    if (!r.value.read) when (val m = repo.markRead(id)) {          // opening a notification reads it
                        is ApiResult.Success -> _ui.update { it.copy(item = m.value) }
                        is ApiResult.Failure -> Unit
                    }
                }
            }
        }
    }

    fun toggleRead() {
        val cur = _ui.value.item ?: return
        if (_ui.value.busy) return
        _ui.update { it.copy(busy = true) }
        viewModelScope.launch {
            val r = if (cur.read) repo.markUnread(id) else repo.markRead(id)
            _ui.update { s -> if (r is ApiResult.Success) s.copy(busy = false, item = r.value) else s.copy(busy = false, error = (r as ApiResult.Failure).failure) }
        }
    }

    fun archive() {
        if (_ui.value.busy) return
        _ui.update { it.copy(busy = true) }
        viewModelScope.launch {
            when (val r = repo.archive(id)) {
                is ApiResult.Success -> _ui.update { it.copy(busy = false, closed = true) }
                is ApiResult.Failure -> _ui.update { it.copy(busy = false, error = r.failure) }
            }
        }
    }
}

class PreferencesViewModel(private val c: AppContainer) : ViewModel() {
    data class UiState(val loading: Boolean = true, val items: List<PreferenceItem> = emptyList(), val hasEmail: Boolean = false,
                       val error: ApiFailure? = null, val saving: Boolean = false, val message: String? = null, val dirty: Boolean = false)
    private val _ui = MutableStateFlow(UiState())
    val ui: StateFlow<UiState> = _ui.asStateFlow()
    init { load() }

    fun load() {
        _ui.update { it.copy(loading = true, error = null) }
        viewModelScope.launch {
            when (val r = c.services.notifications.preferences()) {
                is ApiResult.Success -> _ui.value = UiState(loading = false, items = r.value.items, hasEmail = r.value.hasEmail)
                is ApiResult.Failure -> _ui.update { it.copy(loading = false, error = r.failure) }
            }
        }
    }

    fun toggle(category: String, inApp: Boolean?, email: Boolean?) = _ui.update { s ->
        s.copy(dirty = true, message = null, items = s.items.map {
            if (it.category != category) it else it.copy(inApp = if (it.inAppLocked) true else inApp ?: it.inApp, email = email ?: it.email)
        })
    }

    fun save() {
        if (_ui.value.saving) return
        _ui.update { it.copy(saving = true, message = null) }
        viewModelScope.launch {
            when (val r = c.services.notifications.savePreferences(_ui.value.items)) {
                is ApiResult.Success -> _ui.value = UiState(loading = false, items = r.value.items, hasEmail = r.value.hasEmail, message = "Preferences saved.")
                is ApiResult.Failure -> _ui.update { it.copy(saving = false, message = r.failure.message) }
            }
        }
    }
}

class AppViewModelFactory(private val c: AppContainer, private val role: Role? = null, private val id: Int = 0) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T = when (modelClass) {
        AppViewModel::class.java -> AppViewModel(c)
        LoginViewModel::class.java -> LoginViewModel(c)
        RecoveryViewModel::class.java -> RecoveryViewModel(c)
        ChangePasswordViewModel::class.java -> ChangePasswordViewModel(c)
        HomeViewModel::class.java -> HomeViewModel(c)
        TimetableViewModel::class.java -> TimetableViewModel(c)
        ResultsViewModel::class.java -> ResultsViewModel(c)
        ExamListViewModel::class.java -> ExamListViewModel(c)
        ExamDetailViewModel::class.java -> ExamDetailViewModel(c, id, role ?: Role.INVIGILATOR)
        StudentSearchViewModel::class.java -> StudentSearchViewModel(c)
        AlertsViewModel::class.java -> AlertsViewModel(c)
        NotificationDetailViewModel::class.java -> NotificationDetailViewModel(c, id)
        PreferencesViewModel::class.java -> PreferencesViewModel(c)
        else -> throw IllegalArgumentException("Unknown ViewModel ${modelClass.name}")
    } as T
}
