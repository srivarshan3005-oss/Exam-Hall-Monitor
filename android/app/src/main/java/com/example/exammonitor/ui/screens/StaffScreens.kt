package com.example.exammonitor.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.exammonitor.core.*
import com.example.exammonitor.ui.*
import com.example.exammonitor.ui.components.*
import java.time.LocalDateTime

@Composable
fun ExamsScreen(vm: ExamListViewModel, role: Role, snackbar: SnackbarHostState, onOpen: (Exam) -> Unit) {
    val state by vm.exams.state.collectAsStateWithLifecycle()
    val filter by vm.filter.collectAsStateWithLifecycle()
    val message by vm.message.collectAsStateWithLifecycle()
    val publishing by vm.publishing.collectAsStateWithLifecycle()
    var query by rememberSaveable { mutableStateOf(filter.query) }
    var confirm by remember { mutableStateOf<Pair<Exam, Boolean>?>(null) }
    val now = remember { LocalDateTime.now() }
    val canPublish = Permissions.can(role, Capability.PUBLISH_EXAMS)
    LaunchedEffect(Unit) { vm.exams.load() }
    LaunchedEffect(message) { message?.let { snackbar.showSnackbar(it); vm.consumeMessage() } }

    StateHost(state, onRefresh = { vm.exams.load(refresh = true) }, isEmpty = { it.isEmpty() },
        emptyIcon = Icons.AutoMirrored.Filled.List, emptyTitle = "No examinations found",
        emptyMessage = if (filter.query.isNotBlank() || filter.status.isNotBlank()) "Try a different search or filter." else "Examinations created in the web portal appear here.",
        header = {
            item {
                OutlinedTextField(value = query, onValueChange = { query = it }, singleLine = true, label = { Text("Search title or subject code") },
                    modifier = Modifier.fillMaxWidth(), trailingIcon = { IconButton(onClick = { vm.setFilter(filter.copy(query = query)) }) { Icon(Icons.Filled.Search, "Search") } },
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search), keyboardActions = KeyboardActions(onSearch = { vm.setFilter(filter.copy(query = query)) }))
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("" to "All", "published" to "Published", "draft" to "Draft", "completed" to "Completed").forEach { (v, label) ->
                        FilterChip(selected = filter.status == v, onClick = { vm.setFilter(filter.copy(status = v, query = query)) }, label = { Text(label) })
                    }
                }
            }
        }
    ) { exams ->
        exams.forEach { e ->
            item(key = "e-${e.id}") {
                ExamInfoCard(e, now, onClick = { onOpen(e) }) {
                    e.allotmentCount?.let { KeyValue("Seats allotted", it.toString()) }
                    if (canPublish && e.status != "completed") {
                        Spacer(Modifier.height(8.dp))
                        val publish = e.status != "published"
                        OutlinedButton(onClick = { confirm = e to publish }, enabled = publishing == null) {
                            Text(if (publishing == e.id) "Working…" else if (publish) "Publish to students" else "Unpublish")
                        }
                    }
                }
            }
        }
    }

    confirm?.let { (exam, publish) ->
        AlertDialog(onDismissRequest = { confirm = null },
            title = { Text(if (publish) "Publish examination?" else "Unpublish examination?") },
            text = { Text(if (publish) "“${exam.title}” becomes visible to students and they are notified. The server checks dates and venue conflicts."
                         else "“${exam.title}” is hidden from students and they are notified of the change.") },
            confirmButton = { TextButton(onClick = { vm.setPublished(exam, publish); confirm = null }) { Text(if (publish) "Publish" else "Unpublish") } },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel") } })
    }
}

@Composable
fun ExamDetailScreen(vm: ExamDetailViewModel, role: Role) {
    val state by vm.detail.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.load() }
    StateHost(state, onRefresh = { vm.load(refresh = true) }, isEmpty = { false },
        emptyIcon = Icons.AutoMirrored.Filled.List, emptyTitle = "", emptyMessage = "") { d ->
        d.summary?.let { s ->
            item { SectionTitle("Allocation summary") }
            item { AppCard {
                KeyValue("Eligible students", s.eligible.toString()); KeyValue("Seats allotted", s.allotted.toString())
                KeyValue("Not yet allotted", s.unallocated.toString()); KeyValue("Halls in use", s.halls.toString())
            } }
        }
        if (d.halls.isNotEmpty()) {
            item { SectionTitle("Halls") }
            d.halls.forEach { h -> item(key = "h-${h.hall}") { AppCard {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(h.hall, style = MaterialTheme.typography.titleMedium)
                    if (!h.verified) Tag("Not verified", MaterialTheme.colorScheme.tertiaryContainer, MaterialTheme.colorScheme.onTertiaryContainer)
                }
                KeyValue("Allocated", h.allocated.toString())
                h.capacity?.let { KeyValue("Capacity", it.toString()) }
                h.free?.let { KeyValue("Free seats", it.toString()) }
                h.occupancyPercent?.let { KeyValue("Occupancy", "$it %") }
            } } }
        }
        if (d.roster.isNotEmpty()) {
            item { SectionTitle("Seat allocations (${d.roster.size}${if (d.rosterMore) "+" else ""})") }
            if (d.rosterMore) item { Text("Showing the first ${d.roster.size}. Use the web portal for the complete roster.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            d.roster.forEachIndexed { i, r -> item(key = "r-$i-${r.registerNumber}") { AppCard {
                Text(r.registerNumber, style = MaterialTheme.typography.titleMedium)
                r.studentName?.let { Text(it) }
                Text("Hall ${r.hall} · Seat ${r.seat}", color = MaterialTheme.colorScheme.onSurfaceVariant)
            } } }
        }
        if (d.summary == null && d.halls.isEmpty() && d.roster.isEmpty()) item { Text("No allocation has been recorded for this examination yet.") }
        d.notes.forEach { n -> item { Text(n, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) } }
        item { WebOnlyNote("Creating or changing allocations, editing examinations and importing PDFs are done in the web portal.") }
    }
}

@Composable
fun WebOnlyNote(text: String) {
    AppCard(container = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.5f)) {
        Text("Web portal", style = MaterialTheme.typography.labelLarge)
        Text(text, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
fun StudentsScreen(vm: StudentSearchViewModel) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    var query by rememberSaveable { mutableStateOf("") }
    val go = { vm.search(query) }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            OutlinedTextField(value = query, onValueChange = { query = it }, singleLine = true, label = { Text("Register number or name") },
                modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search), keyboardActions = KeyboardActions(onSearch = { go() }),
                supportingText = { Text("Results show only students you are authorised to see. Records are not saved on this device.") })
        }
        item { Button(onClick = go, enabled = !ui.busy && query.trim().length >= 2, modifier = Modifier.fillMaxWidth()) { Text(if (ui.busy) "Searching…" else "Search") } }
        when {
            ui.busy -> item { LoadingView(label = "Searching…") }
            ui.error != null -> item { ErrorView(ui.error!!, go) }
            ui.results == null -> item { MessageView(Icons.Filled.Search, "Find a student's seats", "Search by register number or name to see their examinations, halls and seats.") }
            ui.results!!.isEmpty() -> item { MessageView(Icons.Filled.Search, "No matching student", "Check the spelling or try fewer characters.") }
            else -> ui.results!!.forEach { s ->
                item(key = "s-${s.registerNumber}") { AppCard {
                    Text(s.registerNumber, style = MaterialTheme.typography.titleMedium)
                    s.studentName?.let { Text(it) }
                    Text(listOfNotNull(s.department, s.year?.let { "Year $it" }).joinToString(" · "), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(8.dp))
                    if (s.seats.isEmpty()) Text("No seats allotted yet.", style = MaterialTheme.typography.bodyMedium)
                    s.seats.forEach { a ->
                        HorizontalDivider(Modifier.padding(vertical = 6.dp))
                        Text(a.exam, style = MaterialTheme.typography.labelLarge)
                        Text("${ExamClock.formatDate(a.date)} · ${ExamClock.formatTime(a.startTime)} · ${a.status}", style = MaterialTheme.typography.bodyMedium)
                        Text("Hall ${a.hall} · Seat ${a.seat}", style = MaterialTheme.typography.bodyMedium)
                    }
                } }
            }
        }
    }
}
