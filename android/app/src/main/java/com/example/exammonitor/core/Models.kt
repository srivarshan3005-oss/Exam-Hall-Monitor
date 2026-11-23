package com.example.exammonitor.core

data class UserProfile(
    val username: String, val role: Role, val roleLabel: String, val department: String?, val email: String?,
    val passwordChangeRequired: Boolean, val registerNumber: String?, val studentName: String?
)

data class Exam(
    val id: Int, val title: String, val subjectCode: String, val date: String, val startTime: String,
    val endTime: String, val venue: String, val status: String, val durationMinutes: Int?, val session: String?,
    val subjectName: String?, val termName: String?, val allotmentCount: Int?
)

data class HallLocation(val building: String?, val block: String?, val floor: String?, val room: String?) {
    fun describe(): String = listOfNotNull(building, block, floor, room).filter { it.isNotBlank() }.joinToString(" / ")
}

data class SeatAllotment(
    val exam: String, val subjectCode: String, val date: String, val time: String,
    val hall: String, val seat: String, val location: HallLocation?
)

data class StudentLookup(
    val registerNumber: String, val department: String, val year: Int?, val fullName: String?,
    val allotments: List<SeatAllotment>
)

data class ResultItem(val exam: String, val subjectCode: String, val marks: Double?, val maxMarks: Double?, val grade: String?)

data class Announcement(val id: Int, val title: String, val body: String, val publishedAt: String)

data class AppNotification(
    val id: Int, val category: String, val categoryLabel: String, val priority: String, val title: String,
    val body: String, val link: String?, val createdAt: String, val read: Boolean, val archived: Boolean
)

data class NotificationPage(val items: List<AppNotification>, val total: Int)

data class PreferenceItem(val category: String, val label: String, val inApp: Boolean, val email: Boolean, val inAppLocked: Boolean)
data class Preferences(val items: List<PreferenceItem>, val hasEmail: Boolean)

data class DashboardStats(val students: Int, val exams: Int, val allotments: Int, val publishedResults: Int)

data class StaffSeat(val examId: Int?, val exam: String, val subjectCode: String, val date: String, val startTime: String,
                     val status: String, val hall: String, val seat: String)
data class StaffStudentSeats(val registerNumber: String, val studentName: String?, val department: String?, val year: Int?,
                             val seats: List<StaffSeat>)

data class ExamSummary(val examId: Int, val eligible: Int, val allotted: Int, val unallocated: Int, val halls: Int)
data class HallOccupancy(val hall: String, val verified: Boolean, val capacity: Int?, val allocated: Int, val free: Int?, val occupancyPercent: Double?)
data class RosterEntry(val registerNumber: String, val studentName: String?, val department: String?, val hall: String, val seat: String)

/** A value together with where it came from. `staleReason` is set when a refresh failed and cached data is shown. */
data class Loaded<T>(val data: T, val fetchedAtMillis: Long, val fromCache: Boolean, val staleReason: ApiFailure? = null) {
    val isStale: Boolean get() = fromCache && staleReason != null
}
