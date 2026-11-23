package com.example.exammonitor.core

/**
 * Wire models. Every field is nullable because Gson bypasses Kotlin constructors and can leave any field null;
 * [Mappers] validates required fields and raises [InvalidResponseException] instead of passing nulls on.
 * Property names equal the backend JSON keys on purpose (no annotations needed, R8-safe with keep rules).
 */
data class LoginRequest(val username: String, val password: String)
data class LoginResponseDto(val access_token: String? = null, val token_type: String? = null, val role: String? = null,
                            val username: String? = null, val role_label: String? = null,
                            val pw_change_required: Boolean? = null, val expires_in: Long? = null)
data class ChangePasswordRequest(val current_password: String, val new_password: String)
data class ChangePasswordResponseDto(val access_token: String? = null, val detail: String? = null)
data class ForgotRequest(val identifier: String)
data class ResetRequest(val token: String, val new_password: String)
data class DetailDto(val detail: String? = null)
data class ProfileDto(val username: String? = null, val role: String? = null, val role_label: String? = null,
                      val department: String? = null, val email: String? = null, val pw_change_required: Boolean? = null,
                      val register_number: String? = null, val student_name: String? = null)
data class ExamDto(val id: Int? = null, val title: String? = null, val subject_code: String? = null, val exam_date: String? = null,
                   val start_time: String? = null, val end_time: String? = null, val venue: String? = null, val status: String? = null,
                   val duration_minutes: Int? = null, val session: String? = null, val subject_name: String? = null,
                   val term_name: String? = null, val allotment_count: Int? = null)
data class HallLocationDto(val building: String? = null, val block: String? = null, val floor: String? = null, val room: String? = null)
data class AllotmentDto(val exam: String? = null, val subject_code: String? = null, val date: String? = null, val time: String? = null,
                        val hall: String? = null, val seat: String? = null, val location: HallLocationDto? = null)
data class StudentCardDto(val register_number: String? = null, val department: String? = null, val year: Int? = null, val full_name: String? = null)
data class LookupDto(val student: StudentCardDto? = null, val allotments: List<AllotmentDto>? = null)
data class ResultDto(val exam: String? = null, val subject_code: String? = null, val marks: Double? = null, val max_marks: Double? = null, val grade: String? = null)
data class AnnouncementDto(val id: Int? = null, val title: String? = null, val body: String? = null, val published_at: String? = null)
data class NotificationDto(val id: Int? = null, val category: String? = null, val category_label: String? = null, val priority: String? = null,
                           val title: String? = null, val body: String? = null, val link: String? = null, val created_at: String? = null,
                           val read: Boolean? = null, val archived: Boolean? = null,
                           /** present only on the read/unread/archive action responses */ val unread: Int? = null)
data class UnreadDto(val unread: Int? = null)
data class ReadAllDto(val marked_read: Int? = null, val unread: Int? = null)
data class PreferenceItemDto(val category: String? = null, val label: String? = null, val in_app: Boolean? = null,
                             val email: Boolean? = null, val in_app_locked: Boolean? = null)
data class PreferencesDto(val preferences: List<PreferenceItemDto>? = null, val has_email: Boolean? = null)
data class PreferenceUpdate(val category: String, val in_app: Boolean, val email: Boolean)
data class PreferencesUpdateRequest(val preferences: List<PreferenceUpdate>)
data class DashboardDto(val students: Int? = null, val exams: Int? = null, val allotments: Int? = null, val published_results: Int? = null)
data class StaffSeatDto(val exam_id: Int? = null, val exam: String? = null, val subject_code: String? = null, val date: String? = null,
                        val start_time: String? = null, val status: String? = null, val hall: String? = null, val seat: String? = null)
data class StaffStudentDto(val register_number: String? = null, val student_name: String? = null, val department: String? = null,
                           val year: Int? = null, val allotments: List<StaffSeatDto>? = null)
data class ExamSummaryDto(val exam_id: Int? = null, val eligible_students: Int? = null, val allotted: Int? = null,
                          val unallocated: Int? = null, val halls_used: Int? = null)
data class HallOccupancyDto(val hall: String? = null, val verified: Boolean? = null, val capacity: Int? = null, val allocated: Int? = null,
                            val free: Int? = null, val occupancy_percent: Double? = null)
data class RosterDto(val register_number: String? = null, val student_name: String? = null, val department: String? = null,
                     val hall: String? = null, val seat: String? = null)

object Mappers {
    private fun bad(what: String): Nothing = throw InvalidResponseException(what)
    private fun req(v: String?, what: String): String = v?.takeIf { it.isNotBlank() } ?: bad(what)

    fun profile(d: ProfileDto?): UserProfile {
        d ?: bad("profile")
        val role = Role.fromApi(d.role) ?: bad("profile role")
        return UserProfile(req(d.username, "profile username"), role, d.role_label ?: role.label, d.department, d.email,
            d.pw_change_required ?: false, d.register_number, d.student_name)
    }

    fun exam(d: ExamDto?): Exam {
        d ?: bad("exam")
        return Exam(d.id ?: bad("exam id"), req(d.title, "exam title"), d.subject_code.orEmpty(), req(d.exam_date, "exam date"),
            req(d.start_time, "exam start"), d.end_time.orEmpty(), d.venue.orEmpty(), d.status ?: "published", d.duration_minutes,
            d.session, d.subject_name, d.term_name, d.allotment_count)
    }

    fun allotment(d: AllotmentDto?): SeatAllotment {
        d ?: bad("allotment")
        val loc = d.location?.let { HallLocation(it.building, it.block, it.floor, it.room) }?.takeIf { it.describe().isNotEmpty() }
        return SeatAllotment(req(d.exam, "allotment exam"), d.subject_code.orEmpty(), req(d.date, "allotment date"),
            d.time.orEmpty(), req(d.hall, "allotment hall"), req(d.seat, "allotment seat"), loc)
    }

    fun lookup(d: LookupDto?): StudentLookup {
        d ?: bad("lookup")
        val s = d.student ?: bad("lookup student")
        return StudentLookup(req(s.register_number, "register number"), s.department.orEmpty(), s.year, s.full_name,
            (d.allotments ?: emptyList()).map { allotment(it) })
    }

    fun result(d: ResultDto?): ResultItem {
        d ?: bad("result")
        return ResultItem(req(d.exam, "result exam"), d.subject_code.orEmpty(), d.marks, d.max_marks, d.grade)
    }

    fun announcement(d: AnnouncementDto?): Announcement {
        d ?: bad("announcement")
        return Announcement(d.id ?: bad("announcement id"), req(d.title, "announcement title"), d.body.orEmpty(), d.published_at.orEmpty())
    }

    fun notification(d: NotificationDto?): AppNotification {
        d ?: bad("notification")
        return AppNotification(d.id ?: bad("notification id"), d.category.orEmpty(), d.category_label ?: d.category.orEmpty(),
            d.priority ?: "normal", req(d.title, "notification title"), d.body.orEmpty(), d.link, d.created_at.orEmpty(),
            d.read ?: false, d.archived ?: false)
    }

    fun preferences(d: PreferencesDto?): Preferences {
        d ?: bad("preferences")
        return Preferences((d.preferences ?: bad("preferences list")).map {
            PreferenceItem(req(it.category, "preference category"), it.label ?: it.category.orEmpty(), it.in_app ?: true,
                it.email ?: true, it.in_app_locked ?: false)
        }, d.has_email ?: false)
    }

    fun dashboard(d: DashboardDto?): DashboardStats {
        d ?: bad("dashboard")
        return DashboardStats(d.students ?: 0, d.exams ?: 0, d.allotments ?: 0, d.published_results ?: 0)
    }

    fun staffStudent(d: StaffStudentDto?): StaffStudentSeats {
        d ?: bad("student")
        return StaffStudentSeats(req(d.register_number, "register number"), d.student_name, d.department, d.year,
            (d.allotments ?: emptyList()).map {
                StaffSeat(it.exam_id, it.exam.orEmpty(), it.subject_code.orEmpty(), it.date.orEmpty(), it.start_time.orEmpty(),
                    it.status.orEmpty(), it.hall.orEmpty(), it.seat.orEmpty())
            })
    }

    fun summary(d: ExamSummaryDto?): ExamSummary {
        d ?: bad("summary")
        return ExamSummary(d.exam_id ?: bad("summary id"), d.eligible_students ?: 0, d.allotted ?: 0, d.unallocated ?: 0, d.halls_used ?: 0)
    }

    fun hall(d: HallOccupancyDto?): HallOccupancy {
        d ?: bad("hall")
        return HallOccupancy(req(d.hall, "hall"), d.verified ?: false, d.capacity, d.allocated ?: 0, d.free, d.occupancy_percent)
    }

    fun roster(d: RosterDto?): RosterEntry {
        d ?: bad("roster entry")
        return RosterEntry(req(d.register_number, "register number"), d.student_name, d.department, d.hall.orEmpty(), d.seat.orEmpty())
    }
}
