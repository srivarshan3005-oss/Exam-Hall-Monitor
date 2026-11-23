package com.example.exammonitor.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.exammonitor.core.*
import com.example.exammonitor.ui.HomeViewModel
import com.example.exammonitor.ui.ScreenState
import com.example.exammonitor.ui.components.*
import java.time.LocalDateTime

@Composable
private fun Stat(label: String, value: Int, modifier: Modifier = Modifier) {
    AppCard(modifier) {
        Text(value.toString(), style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.primary)
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun HomeScreen(vm: HomeViewModel, profile: UserProfile, onOpenTab: (AppTab) -> Unit) {
    val role = profile.role
    val notices by vm.notices.state.collectAsStateWithLifecycle()
    val lookup by vm.lookup.state.collectAsStateWithLifecycle()
    val stats by vm.stats.state.collectAsStateWithLifecycle()
    val exams by vm.exams.state.collectAsStateWithLifecycle()
    val unread by vm.unread.collectAsStateWithLifecycle()
    val now = remember { LocalDateTime.now() }
    LaunchedEffect(role) { vm.load(role, refresh = false) }
    val refreshing = notices.refreshing || exams.refreshing || lookup.refreshing || stats.refreshing

    val wrapper = ScreenState<Unit>(refreshing = refreshing, data = Loaded(Unit, System.currentTimeMillis(), false))

    StateHost(wrapper, onRefresh = { vm.load(role, refresh = true) }, isEmpty = { false },
        emptyIcon = Icons.Filled.Home, emptyTitle = "", emptyMessage = "") { _ ->
        item {
            Text("Hello, ${profile.studentName ?: profile.username}", style = MaterialTheme.typography.headlineMedium)
            Text(profile.roleLabel + (profile.department?.let { " · $it" } ?: ""), color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        item {
            AppCard(onClick = { onOpenTab(AppTab.ALERTS) }, container = if (unread > 0) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f)) {
                Text(if (unread == 0) "You're all caught up" else "$unread unread notification${if (unread == 1) "" else "s"}", style = MaterialTheme.typography.titleMedium)
                Text("Tap to open your notification centre", style = MaterialTheme.typography.bodyMedium)
            }
        }
        if (role == Role.STUDENT) studentHero(lookup, now, onOpenTab) else staffHero(role, stats, exams, now, onOpenTab)
        val shown = notices.data?.data.orEmpty().take(3)
        if (shown.isNotEmpty()) {
            item { SectionTitle("Latest announcements") }
            shown.forEach { a -> item(key = "a-${a.id}") { AppCard(onClick = { onOpenTab(AppTab.ALERTS) }) {
                Text(a.title, style = MaterialTheme.typography.titleMedium)
                Text(a.body, maxLines = 3, style = MaterialTheme.typography.bodyMedium)
                Text(ExamClock.formatStamp(a.publishedAt), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            } } }
        } else notices.error?.let { e -> item { Text("Announcements unavailable: ${e.message}", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) } }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.studentHero(state: ScreenState<StudentLookup>, now: LocalDateTime, open: (AppTab) -> Unit) {
    val d = state.data
    item { SectionTitle("Your next examination") }
    when {
        d != null -> {
            if (d.isStale) item { StaleBanner(d) }
            val next = Timetable.next(d.data.allotments, now)
            if (next != null) item { AllotmentCard(next, now) { open(AppTab.TIMETABLE) } }
            else item { AppCard { Text("No upcoming examination with an allotted seat."); Text("Check the timetable tab for published examinations.", style = MaterialTheme.typography.bodyMedium) } }
        }
        state.error != null -> item { ErrorView(state.error!!, null) }
        else -> item { LoadingView() }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.staffHero(role: Role, stats: ScreenState<DashboardStats>, exams: ScreenState<List<Exam>>, now: LocalDateTime, open: (AppTab) -> Unit) {
    if (Permissions.can(role, Capability.VIEW_DASHBOARD_STATS)) {
        item { SectionTitle("Overview") }
        val s = stats.data
        when {
            s != null -> {
                if (s.isStale) item { StaleBanner(s) }
                item { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Stat("Students", s.data.students, Modifier.weight(1f)); Stat("Examinations", s.data.exams, Modifier.weight(1f)) } }
                item { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Stat("Seat allotments", s.data.allotments, Modifier.weight(1f)); Stat("Published results", s.data.publishedResults, Modifier.weight(1f)) } }
            }
            stats.error != null -> item { ErrorView(stats.error!!, null) }
            else -> item { LoadingView() }
        }
    }
    val up = Timetable.upcomingExams(exams.data?.data.orEmpty(), now).take(3)
    item { SectionTitle("Upcoming published examinations") }
    if (up.isEmpty()) item { Text(if (exams.error != null) "Could not load examinations: ${exams.error!!.message}" else "No upcoming published examinations.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
    up.forEach { e -> item(key = "x-${e.id}") { ExamInfoCard(e, now, onClick = { open(AppTab.EXAMS) }) } }
    item { WebOnlyNote(if (role == Role.INVIGILATOR) "Hall rosters and seating charts for your duties are under Exams." else "Seat allocation runs, PDF/OCR imports, results publishing and account management are done in the web portal.") }
}
