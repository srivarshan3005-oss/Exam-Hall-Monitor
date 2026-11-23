package com.example.exammonitor.data

import com.example.exammonitor.core.Role
import com.example.exammonitor.core.SessionState
import com.example.exammonitor.core.UserProfile
import com.google.gson.Gson
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Single source of truth for "who is signed in". Holds the bearer token in encrypted storage only (never the password)
 * and clears every private cache when the session ends, expires or the account changes.
 */
class SessionManager(private val secure: KeyValueStore, private val cache: CacheStore, private val gson: Gson = Gson()) {
    private val _state = MutableStateFlow<SessionState>(SessionState.Restoring)
    val state: StateFlow<SessionState> = _state.asStateFlow()

    @Volatile private var token: String? = secure.get(KEY_TOKEN)

    fun token(): String? = token
    fun hasStoredToken(): Boolean = !token.isNullOrBlank()
    fun currentProfile(): UserProfile? = (state.value as? SessionState.SignedIn)?.profile

    private data class StoredProfile(val username: String? = null, val role: String? = null, val roleLabel: String? = null,
                                     val department: String? = null, val email: String? = null,
                                     val registerNumber: String? = null, val studentName: String? = null)

    /** Profile saved at last sign-in; lets the app open (read-only, cached data) when the server is unreachable. */
    fun storedProfile(): UserProfile? {
        val raw = secure.get(KEY_PROFILE) ?: return null
        val it = try { gson.fromJson(raw, StoredProfile::class.java) } catch (e: Exception) { null } ?: return null
        val role = Role.fromApi(it.role) ?: return null
        val name = it.username ?: return null
        return UserProfile(name, role, it.roleLabel ?: role.label, it.department, it.email, false, it.registerNumber, it.studentName)
    }

    /** Called after a successful login/password change. Switching accounts wipes the previous user's cache first. */
    fun signIn(newToken: String, profile: UserProfile) {
        val previous = storedProfile()?.username
        if (previous != null && !previous.equals(profile.username, ignoreCase = true)) cache.clearAll()
        cache.clearForOtherUsers(profile.username)
        token = newToken
        secure.put(KEY_TOKEN, newToken)
        persist(profile)
        _state.value = SessionState.SignedIn(profile)
    }

    /** Updates the profile after it is (re)fetched, e.g. after the forced password change. */
    fun updateProfile(profile: UserProfile) {
        persist(profile)
        if (token != null) _state.value = SessionState.SignedIn(profile)
    }

    fun updateToken(newToken: String) { token = newToken; secure.put(KEY_TOKEN, newToken) }

    /** Local sign-out: forget everything private. The caller tells the server separately (best effort). */
    fun signOut(notice: String? = null) {
        wipe()
        _state.value = SessionState.SignedOut(notice)
    }

    /** The server rejected our token. [usedToken] guards against a stale in-flight request ending a *new* session. */
    fun expire(usedToken: String?, notice: String = "Your session has ended. Please sign in again.") {
        if (usedToken != null && usedToken != token) return
        if (state.value is SessionState.SignedOut) return
        signOut(notice)
    }

    fun markRestoring() { _state.value = SessionState.Restoring }
    fun markSignedOut(notice: String? = null) { _state.value = SessionState.SignedOut(notice) }

    private fun persist(p: UserProfile) {
        secure.put(KEY_PROFILE, gson.toJson(StoredProfile(p.username, p.role.api, p.roleLabel, p.department, p.email, p.registerNumber, p.studentName)))
    }

    private fun wipe() {
        token = null
        secure.remove(KEY_TOKEN)
        secure.remove(KEY_PROFILE)
        cache.clearAll()
    }

    private companion object { const val KEY_TOKEN = "access_token"; const val KEY_PROFILE = "profile" }
}
