package com.example.exammonitor.core

import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale

/** Exam dates/times are plain local values ("2026-11-20", "09:30") exactly as the backend stores them. */
object ExamClock {
    private val dateFmt = DateTimeFormatter.ofPattern("EEE, d MMM yyyy", Locale.ENGLISH)
    private val timeFmt = DateTimeFormatter.ofPattern("h:mm a", Locale.ENGLISH)
    private val stampFmt = DateTimeFormatter.ofPattern("d MMM yyyy, h:mm a", Locale.ENGLISH)

    fun parseDate(s: String?): LocalDate? = try { s?.let { LocalDate.parse(it.trim()) } } catch (e: DateTimeParseException) { null }
    fun parseTime(s: String?): LocalTime? = try { s?.let { LocalTime.parse(it.trim()) } } catch (e: DateTimeParseException) { null }

    fun startOf(date: String, start: String): LocalDateTime? {
        val d = parseDate(date) ?: return null
        val t = parseTime(start) ?: return null
        return LocalDateTime.of(d, t)
    }

    fun formatDate(s: String?): String = parseDate(s)?.format(dateFmt) ?: (s ?: "—")
    fun formatTime(s: String?): String = parseTime(s)?.format(timeFmt) ?: (s ?: "—")
    fun formatRange(start: String?, end: String?): String = "${formatTime(start)} – ${formatTime(end)}"

    fun isUpcoming(date: String, start: String, now: LocalDateTime): Boolean {
        val at = startOf(date, start) ?: return false
        return !at.isBefore(now)
    }

    /** "Today", "Tomorrow", "In 5 days", "Started", or null when the date is unparsable. */
    fun countdown(date: String, start: String, now: LocalDateTime): String? {
        val at = startOf(date, start) ?: return null
        if (at.isBefore(now)) return if (parseDate(date) == now.toLocalDate()) "Started today" else "Completed"
        val days = Duration.between(now.toLocalDate().atStartOfDay(), at.toLocalDate().atStartOfDay()).toDays()
        return when (days) { 0L -> "Today"; 1L -> "Tomorrow"; else -> "In $days days" }
    }

    /** Server timestamps are ISO-8601; naive ones are UTC (the backend stores UTC). */
    fun parseInstant(iso: String?): Instant? {
        if (iso.isNullOrBlank()) return null
        return try { OffsetDateTime.parse(iso).toInstant() } catch (e: DateTimeParseException) {
            try { LocalDateTime.parse(iso).atZone(ZoneId.of("UTC")).toInstant() } catch (e2: DateTimeParseException) { null }
        }
    }

    fun formatStamp(iso: String?, zone: ZoneId = ZoneId.systemDefault()): String =
        parseInstant(iso)?.atZone(zone)?.format(stampFmt) ?: (iso ?: "—")

    fun formatMillis(millis: Long, zone: ZoneId = ZoneId.systemDefault()): String =
        Instant.ofEpochMilli(millis).atZone(zone).format(stampFmt)

    fun relative(iso: String?, now: Instant = Instant.now()): String {
        val t = parseInstant(iso) ?: return iso ?: "—"
        val m = Duration.between(t, now).toMinutes()
        return when {
            m < 1 -> "Just now"; m < 60 -> "$m min ago"; m < 60 * 24 -> "${m / 60} h ago"
            m < 60 * 24 * 7 -> "${m / (60 * 24)} d ago"; else -> formatStamp(iso)
        }
    }
}

object Timetable {
    fun sorted(items: List<SeatAllotment>): List<SeatAllotment> =
        items.sortedWith(compareBy({ it.date }, { it.time }, { it.exam }))

    fun upcoming(items: List<SeatAllotment>, now: LocalDateTime) = sorted(items).filter { ExamClock.isUpcoming(it.date, it.time, now) }
    fun past(items: List<SeatAllotment>, now: LocalDateTime) = sorted(items).filterNot { ExamClock.isUpcoming(it.date, it.time, now) }.reversed()
    fun next(items: List<SeatAllotment>, now: LocalDateTime) = upcoming(items, now).firstOrNull()

    /** Published exams (public list) that are upcoming, soonest first. */
    fun upcomingExams(exams: List<Exam>, now: LocalDateTime) =
        exams.filter { ExamClock.isUpcoming(it.date, it.startTime, now) }.sortedWith(compareBy({ it.date }, { it.startTime }))
}

object NotificationLogic {
    fun withRead(items: List<AppNotification>, id: Int, read: Boolean) = items.map { if (it.id == id) it.copy(read = read) else it }
    fun without(items: List<AppNotification>, id: Int) = items.filterNot { it.id == id }
    fun allRead(items: List<AppNotification>) = items.map { it.copy(read = true) }
    fun unreadIn(items: List<AppNotification>) = items.count { !it.read && !it.archived }

    /** Appends a next page without duplicating items already shown. */
    fun merge(existing: List<AppNotification>, next: List<AppNotification>): List<AppNotification> {
        val seen = existing.mapTo(HashSet()) { it.id }
        return existing + next.filter { seen.add(it.id) }
    }

    /** Maps a web hash link from the backend ("#/my-exams") to an app tab; unknown links return null. */
    fun tabForLink(link: String?, role: Role): AppTab? {
        val target = when (link?.trim()) {
            "#/my-exams" -> if (role == Role.STUDENT) AppTab.TIMETABLE else AppTab.EXAMS
            "#/my-results" -> if (role == Role.STUDENT) AppTab.RESULTS else null
            "#/account" -> AppTab.PROFILE
            "#/notifications" -> AppTab.ALERTS
            else -> null
        }
        return target?.takeIf { Navigation.canOpen(role, it.route) }
    }
}

object CacheKeys {
    /** Every cache entry is namespaced by user so one account can never read another's cached private data. */
    fun forUser(username: String, name: String) = "u:${username.trim().lowercase()}:$name"
    fun belongsTo(key: String, username: String) = key.startsWith("u:${username.trim().lowercase()}:")
}
