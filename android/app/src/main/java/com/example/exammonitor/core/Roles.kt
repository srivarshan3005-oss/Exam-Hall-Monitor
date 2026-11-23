package com.example.exammonitor.core

/** Roles exactly as stored by the backend (users.role). */
enum class Role(val api: String, val label: String) {
    SUPER_ADMIN("super_admin", "Super administrator"),
    ADMIN("admin", "Examination administrator"),
    STAFF("staff", "Department staff"),
    INVIGILATOR("invigilator", "Invigilator"),
    STUDENT("student", "Student");

    val isStaffSide: Boolean get() = this != STUDENT

    companion object {
        fun fromApi(value: String?): Role? = entries.firstOrNull { it.api == value }
    }
}

/** What the *UI* may offer. The backend remains the authority and re-checks every request. */
enum class Capability {
    VIEW_DASHBOARD_STATS,   // GET /api/dashboard                  admin, staff
    VIEW_ADMIN_EXAMS,       // GET /api/admin/exams                admin, staff, invigilator
    VIEW_EXAM_SUMMARY,      // GET /api/reports/exams/{id}/summary admin, staff
    VIEW_EXAM_ALLOCATIONS,  // GET /api/allotments/exam/{id}       admin, staff, invigilator
    VIEW_HALL_OCCUPANCY,    // GET /api/reports/exams/{id}/halls   admin, staff, invigilator
    LOOKUP_STUDENT_SEATS,   // GET /api/reports/students/seats     admin, staff
    PUBLISH_EXAMS,          // POST /api/exams/{id}/(un)publish    admin, staff
    VIEW_OWN_TIMETABLE,     // student only (own register number)
    VIEW_OWN_RESULTS        // student only (own register number)
}

object Permissions {
    private val adminLevel = setOf(Role.SUPER_ADMIN, Role.ADMIN)
    private val staffLevel = adminLevel + Role.STAFF
    private val readLevel = staffLevel + Role.INVIGILATOR

    fun can(role: Role, capability: Capability): Boolean = when (capability) {
        Capability.VIEW_DASHBOARD_STATS, Capability.VIEW_EXAM_SUMMARY,
        Capability.LOOKUP_STUDENT_SEATS, Capability.PUBLISH_EXAMS -> role in staffLevel
        Capability.VIEW_ADMIN_EXAMS, Capability.VIEW_EXAM_ALLOCATIONS,
        Capability.VIEW_HALL_OCCUPANCY -> role in readLevel
        Capability.VIEW_OWN_TIMETABLE, Capability.VIEW_OWN_RESULTS -> role == Role.STUDENT
    }
}

enum class AppTab(val route: String, val label: String) {
    HOME("home", "Home"), TIMETABLE("timetable", "Timetable"), RESULTS("results", "Results"),
    EXAMS("exams", "Exams"), STUDENTS("students", "Students"), ALERTS("alerts", "Alerts"), PROFILE("profile", "Profile")
}

object Navigation {
    fun tabsFor(role: Role): List<AppTab> = when (role) {
        Role.STUDENT -> listOf(AppTab.HOME, AppTab.TIMETABLE, AppTab.RESULTS, AppTab.ALERTS, AppTab.PROFILE)
        Role.INVIGILATOR -> listOf(AppTab.HOME, AppTab.EXAMS, AppTab.ALERTS, AppTab.PROFILE)
        Role.STAFF, Role.ADMIN, Role.SUPER_ADMIN -> listOf(AppTab.HOME, AppTab.EXAMS, AppTab.STUDENTS, AppTab.ALERTS, AppTab.PROFILE)
    }

    fun canOpen(role: Role, route: String): Boolean = tabsFor(role).any { it.route == route }
}

/** Top-level destination chosen from the session state. Pure so it can be unit-tested. */
sealed interface Destination {
    data object Splash : Destination
    data class Login(val notice: String? = null) : Destination
    data object ForcePasswordChange : Destination
    data class Main(val role: Role) : Destination
}

sealed interface SessionState {
    data object Restoring : SessionState
    data class SignedOut(val notice: String? = null) : SessionState
    data class SignedIn(val profile: UserProfile) : SessionState
}

object Router {
    fun destinationFor(state: SessionState): Destination = when (state) {
        SessionState.Restoring -> Destination.Splash
        is SessionState.SignedOut -> Destination.Login(state.notice)
        is SessionState.SignedIn ->
            if (state.profile.passwordChangeRequired) Destination.ForcePasswordChange
            else Destination.Main(state.profile.role)
    }
}
