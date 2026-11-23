package com.example.exammonitor.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.exammonitor.core.*
import com.example.exammonitor.ui.ResultsViewModel
import com.example.exammonitor.ui.TimetableViewModel
import com.example.exammonitor.ui.components.*
import java.time.LocalDateTime

@Composable
fun AllotmentCard(a: SeatAllotment, now: LocalDateTime, onClick: () -> Unit) {
    AppCard(onClick = onClick) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(a.exam, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            ExamClock.countdown(a.date, a.time, now)?.let { Spacer(Modifier.width(8.dp)); Tag(it) }
        }
        if (a.subjectCode.isNotBlank()) Text(a.subjectCode, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(8.dp))
        KeyValue("Date", ExamClock.formatDate(a.date))
        KeyValue("Starts", ExamClock.formatTime(a.time))
        KeyValue("Hall", a.hall)
        KeyValue("Seat", a.seat)
        a.location?.describe()?.takeIf { it.isNotEmpty() }?.let { KeyValue("Location", it) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AllotmentSheet(a: SeatAllotment, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.padding(horizontal = 24.dp).padding(bottom = 32.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(a.exam, style = MaterialTheme.typography.titleLarge)
            if (a.subjectCode.isNotBlank()) Text(a.subjectCode, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(12.dp))
            KeyValue("Date", ExamClock.formatDate(a.date))
            KeyValue("Start time", ExamClock.formatTime(a.time))
            KeyValue("Hall", a.hall)
            KeyValue("Seat number", a.seat)
            val loc = a.location
            if (loc != null) {
                loc.building?.takeIf { it.isNotBlank() }?.let { KeyValue("Building", it) }
                loc.block?.takeIf { it.isNotBlank() }?.let { KeyValue("Block", it) }
                loc.floor?.takeIf { it.isNotBlank() }?.let { KeyValue("Floor", it) }
                loc.room?.takeIf { it.isNotBlank() }?.let { KeyValue("Room", it) }
            } else {
                Text("Hall location details have not been published for this hall.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.height(12.dp))
            Text("Arrive early and carry your ID card. The published timetable and seat allocation are the official sources.",
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
fun ExamInfoCard(e: Exam, now: LocalDateTime, onClick: (() -> Unit)? = null, footer: (@Composable ColumnScope.() -> Unit)? = null) {
    AppCard(onClick = onClick) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(e.title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            Spacer(Modifier.width(8.dp))
            when (e.status) {
                "published" -> ExamClock.countdown(e.date, e.startTime, now)?.let { Tag(it) }
                else -> Tag(e.status.replaceFirstChar { it.uppercase() }, MaterialTheme.colorScheme.tertiaryContainer, MaterialTheme.colorScheme.onTertiaryContainer)
            }
        }
        if (e.subjectCode.isNotBlank()) Text(e.subjectCode + (e.subjectName?.let { " · $it" } ?: ""), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(6.dp))
        KeyValue("Date", ExamClock.formatDate(e.date))
        KeyValue("Time", ExamClock.formatRange(e.startTime, e.endTime.ifBlank { null }))
        if (e.venue.isNotBlank()) KeyValue("Venue", e.venue)
        e.durationMinutes?.let { KeyValue("Duration", "${it / 60} h ${it % 60} min") }
        footer?.invoke(this)
    }
}

@Composable
fun TimetableScreen(vm: TimetableViewModel) {
    val lookup by vm.lookup.state.collectAsStateWithLifecycle()
    val exams by vm.exams.state.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.load() }
    val now = remember { LocalDateTime.now() }
    var selected by remember { mutableStateOf<SeatAllotment?>(null) }

    StateHost(lookup, onRefresh = { vm.load(refresh = true) },
        isEmpty = { it.allotments.isEmpty() && (exams.data?.data?.isEmpty() != false) },
        emptyIcon = Icons.Filled.DateRange, emptyTitle = "No examinations yet",
        emptyMessage = "Your timetable, hall and seat appear here once the examination office publishes them."
    ) { data ->
        val upcoming = Timetable.upcoming(data.allotments, now)
        val past = Timetable.past(data.allotments, now)
        item { SectionTitle("My examinations") }
        if (upcoming.isEmpty()) item { Text("No upcoming examinations with an allotted seat.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        upcoming.forEach { a -> item(key = "u-${a.exam}-${a.date}-${a.time}") { AllotmentCard(a, now) { selected = a } } }
        otherPublished(exams.data?.data.orEmpty(), data.allotments, now)
        if (past.isNotEmpty()) {
            item { SectionTitle("Completed") }
            past.forEach { a -> item(key = "p-${a.exam}-${a.date}-${a.time}") { AllotmentCard(a, now) { selected = a } } }
        }
    }
    selected?.let { AllotmentSheet(it) { selected = null } }
}

private fun LazyListScope.otherPublished(all: List<Exam>, mine: List<SeatAllotment>, now: LocalDateTime) {
    val mineKeys = mine.map { Triple(it.exam, it.date, it.time) }.toSet()
    val others = Timetable.upcomingExams(all, now).filterNot { Triple(it.title, it.date, it.startTime) in mineKeys }.take(10)
    if (others.isEmpty()) return
    item { SectionTitle("Other published examinations") }
    item { Text("College-wide timetable. A hall and seat appear above only when one is allotted to you.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    others.forEach { e -> item(key = "o-${e.id}") { ExamInfoCard(e, now) } }
}

@Composable
fun ResultsScreen(vm: ResultsViewModel) {
    val state by vm.results.state.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.results.load() }
    StateHost(state, onRefresh = { vm.results.load(refresh = true) }, isEmpty = { it.isEmpty() },
        emptyIcon = Icons.Filled.CheckCircle, emptyTitle = "No published results",
        emptyMessage = "Results appear here after the examination office publishes them. You will also get a notification."
    ) { items ->
        item { SectionTitle("Published results") }
        items.forEachIndexed { i, r ->
            item(key = "r-$i-${r.exam}") {
                AppCard {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(r.exam, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        r.grade?.takeIf { it.isNotBlank() }?.let { Tag("Grade $it", MaterialTheme.colorScheme.secondaryContainer, MaterialTheme.colorScheme.onSecondaryContainer) }
                    }
                    if (r.subjectCode.isNotBlank()) Text(r.subjectCode, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(6.dp))
                    KeyValue("Marks", if (r.marks != null) "${fmt(r.marks)}${r.maxMarks?.let { " / ${fmt(it)}" } ?: ""}" else "—")
                }
            }
        }
    }
}

private fun fmt(d: Double): String = if (d == Math.floor(d)) d.toLong().toString() else String.format(java.util.Locale.ENGLISH, "%.1f", d)
