package com.example.exammonitor.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.exammonitor.core.*
import com.example.exammonitor.ui.*
import com.example.exammonitor.ui.components.*

@Composable
fun AlertsScreen(vm: AlertsViewModel, snackbar: SnackbarHostState, onOpen: (AppNotification) -> Unit, onPreferences: () -> Unit) {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    val unread by vm.unread.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.refresh(initial = true) }
    Column(Modifier.fillMaxSize()) {
        TabRow(selectedTabIndex = tab) {
            Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text(if (unread > 0) "Notifications ($unread)" else "Notifications") })
            Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("Announcements") })
        }
        if (tab == 0) NotificationList(vm, snackbar, onOpen, onPreferences) else AnnouncementList(vm)
    }
}

@OptIn(ExperimentalMaterial3Api::class)   // PullToRefreshBox is experimental in Material3 1.3.x
@Composable
private fun NotificationList(vm: AlertsViewModel, snackbar: SnackbarHostState, onOpen: (AppNotification) -> Unit, onPreferences: () -> Unit) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    LaunchedEffect(ui.message) { ui.message?.let { snackbar.showSnackbar(it); vm.consumeMessage() } }

    PullToRefreshBox(isRefreshing = ui.refreshing, onRefresh = { vm.refresh() }, modifier = Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    FilterChip(selected = !ui.unreadOnly, onClick = { if (ui.unreadOnly) vm.setUnreadOnly(false) }, label = { Text("All") })
                    Spacer(Modifier.width(8.dp))
                    FilterChip(selected = ui.unreadOnly, onClick = { if (!ui.unreadOnly) vm.setUnreadOnly(true) }, label = { Text("Unread") })
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = { vm.markAllRead() }, enabled = ui.items.any { !it.read } && !ui.busyIds.contains(-1)) { Text("Mark all read") }
                    IconButton(onClick = onPreferences) { Icon(Icons.Filled.Settings, contentDescription = "Notification preferences") }
                }
            }
            when {
                ui.loading -> item { LoadingView() }
                ui.error != null && ui.items.isEmpty() -> item { ErrorView(ui.error!!, { vm.refresh() }) }
                ui.items.isEmpty() -> item { MessageView(Icons.Filled.Notifications, if (ui.unreadOnly) "No unread notifications" else "No notifications yet",
                    "Examination, timetable, seating, result and account notices will appear here.") }
                else -> {
                    ui.error?.let { e -> item { Text("Could not refresh: ${e.message}", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) } }
                    items(ui.items, key = { it.id }) { n -> NotificationRow(n, busy = ui.busyIds.contains(n.id), onOpen = { onOpen(n) },
                        onToggle = { vm.setRead(n, !n.read) }, onArchive = { vm.archive(n) }) }
                    if (ui.items.size < ui.total) item {
                        OutlinedButton(onClick = { vm.loadMore() }, enabled = !ui.loadingMore, modifier = Modifier.fillMaxWidth()) {
                            Text(if (ui.loadingMore) "Loading…" else "Load more (${ui.total - ui.items.size} left)")
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun NotificationRow(n: AppNotification, busy: Boolean, onOpen: () -> Unit, onToggle: () -> Unit, onArchive: () -> Unit) {
    var menu by remember { mutableStateOf(false) }
    val urgent = n.priority == "urgent" || n.priority == "high"
    AppCard(onClick = onOpen, container = if (n.read) MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f) else MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.6f),
        modifier = Modifier.semantics { contentDescription = (if (n.read) "" else "Unread. ") + n.title }) {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Tag(n.categoryLabel)
                    if (urgent) Tag(n.priority.replaceFirstChar { it.uppercase() }, MaterialTheme.colorScheme.errorContainer, MaterialTheme.colorScheme.onErrorContainer)
                }
                Spacer(Modifier.height(6.dp))
                Text(n.title, style = MaterialTheme.typography.titleMedium, fontWeight = if (n.read) FontWeight.Normal else FontWeight.SemiBold)
                Text(n.body, maxLines = 2, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(ExamClock.relative(n.createdAt), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Box {
                if (busy) CircularProgressIndicator(Modifier.size(24.dp).padding(2.dp), strokeWidth = 2.dp)
                else IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, contentDescription = "Actions for ${n.title}") }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    DropdownMenuItem(text = { Text(if (n.read) "Mark as unread" else "Mark as read") }, onClick = { menu = false; onToggle() })
                    DropdownMenuItem(text = { Text("Archive") }, onClick = { menu = false; onArchive() })
                }
            }
        }
    }
}

@Composable
private fun AnnouncementList(vm: AlertsViewModel) {
    val state by vm.announcements.state.collectAsStateWithLifecycle()
    StateHost(state, onRefresh = { vm.announcements.load(refresh = true) }, isEmpty = { it.isEmpty() },
        emptyIcon = Icons.Filled.Notifications, emptyTitle = "No announcements", emptyMessage = "Official announcements from the examination office appear here.") { list ->
        list.forEach { a -> item(key = "an-${a.id}") { AppCard {
            Text(a.title, style = MaterialTheme.typography.titleMedium)
            Text(ExamClock.formatStamp(a.publishedAt), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(6.dp))
            Text(a.body, style = MaterialTheme.typography.bodyMedium)
        } } }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NotificationDetailScreen(vm: NotificationDetailViewModel, role: Role, onOpenTab: (AppTab) -> Unit, onClosed: () -> Unit) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    LaunchedEffect(ui.closed) { if (ui.closed) onClosed() }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        val n = ui.item
        when {
            ui.loading -> item { LoadingView() }
            n == null -> item { ErrorView(ui.error ?: ErrorMapper.invalid("notification"), { vm.load() }) }
            else -> {
                item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Tag(n.categoryLabel); Tag(n.priority.replaceFirstChar { it.uppercase() }, MaterialTheme.colorScheme.secondaryContainer, MaterialTheme.colorScheme.onSecondaryContainer)
                    Tag(if (n.read) "Read" else "Unread", MaterialTheme.colorScheme.surfaceVariant, MaterialTheme.colorScheme.onSurfaceVariant)
                } }
                item { Text(n.title, style = MaterialTheme.typography.titleLarge) }
                item { Text(ExamClock.formatStamp(n.createdAt), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                item { Text(n.body, style = MaterialTheme.typography.bodyLarge) }
                ui.error?.let { e -> item { Text(e.message, color = MaterialTheme.colorScheme.error) } }
                NotificationLogic.tabForLink(n.link, role)?.let { tab -> item { Button(onClick = { onOpenTab(tab) }, modifier = Modifier.fillMaxWidth()) { Text("Open ${tab.label}") } } }
                item { OutlinedButton(onClick = { vm.toggleRead() }, enabled = !ui.busy, modifier = Modifier.fillMaxWidth()) { Text(if (n.read) "Mark as unread" else "Mark as read") } }
                item { OutlinedButton(onClick = { vm.archive() }, enabled = !ui.busy, modifier = Modifier.fillMaxWidth()) { Text("Archive") } }
            }
        }
    }
}

@Composable
fun PreferencesScreen(vm: PreferencesViewModel, snackbar: SnackbarHostState) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    LaunchedEffect(ui.message) { ui.message?.let { snackbar.showSnackbar(it) } }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        when {
            ui.loading -> item { LoadingView() }
            ui.error != null && ui.items.isEmpty() -> item { ErrorView(ui.error!!, { vm.load() }) }
            else -> {
                item { Text("Choose how you want to be notified. Account and security notices are always shown in the app.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                if (!ui.hasEmail) item { Text("No e-mail address is on file, so e-mail notifications cannot be delivered.", color = MaterialTheme.colorScheme.tertiary, style = MaterialTheme.typography.bodyMedium) }
                items(ui.items, key = { it.category }) { p -> AppCard {
                    Text(p.label, style = MaterialTheme.typography.titleMedium)
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(if (p.inAppLocked) "In the app (always on)" else "In the app", Modifier.weight(1f))
                        Switch(checked = p.inApp, onCheckedChange = { vm.toggle(p.category, it, null) }, enabled = !p.inAppLocked && !ui.saving)
                    }
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text("By e-mail", Modifier.weight(1f))
                        Switch(checked = p.email, onCheckedChange = { vm.toggle(p.category, null, it) }, enabled = ui.hasEmail && !ui.saving)
                    }
                } }
                item { Button(onClick = { vm.save() }, enabled = ui.dirty && !ui.saving, modifier = Modifier.fillMaxWidth()) { Text(if (ui.saving) "Saving…" else "Save preferences") } }
                item { Text("Push notifications to the lock screen are not available yet; the app shows notifications when you open it.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
        }
    }
}
