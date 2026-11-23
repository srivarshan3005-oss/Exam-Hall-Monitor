package com.example.exammonitor.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.example.exammonitor.core.ApiFailure
import com.example.exammonitor.core.ErrorKind
import com.example.exammonitor.core.ExamClock
import com.example.exammonitor.core.Loaded
import com.example.exammonitor.ui.ScreenState

@Composable
fun LoadingView(modifier: Modifier = Modifier, label: String = "Loading…") {
    Column(modifier.fillMaxWidth().padding(48.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        CircularProgressIndicator()
        Spacer(Modifier.height(12.dp))
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun MessageView(icon: ImageVector, title: String, message: String, actionLabel: String? = null, onAction: (() -> Unit)? = null) {
    Column(Modifier.fillMaxWidth().padding(vertical = 40.dp, horizontal = 16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(48.dp))
        Spacer(Modifier.height(12.dp))
        Text(title, style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
        Spacer(Modifier.height(4.dp))
        Text(message, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
        if (actionLabel != null && onAction != null) {
            Spacer(Modifier.height(16.dp))
            FilledTonalButton(onClick = onAction) { Icon(Icons.Filled.Refresh, contentDescription = null); Spacer(Modifier.width(8.dp)); Text(actionLabel) }
        }
    }
}

@Composable
fun ErrorView(failure: ApiFailure, onRetry: (() -> Unit)?) {
    val title = when (failure.kind) {
        ErrorKind.NETWORK, ErrorKind.TIMEOUT -> "You appear to be offline"
        ErrorKind.FORBIDDEN -> "Not available for your account"
        ErrorKind.SERVER -> "Server problem"
        else -> "Something went wrong"
    }
    MessageView(Icons.Filled.Warning, title, failure.message, if (onRetry != null && failure.kind != ErrorKind.FORBIDDEN) "Try again" else null, onRetry)
}

/** Clearly marks cached data that could not be refreshed. */
@Composable
fun StaleBanner(loaded: Loaded<*>) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiaryContainer),
        modifier = Modifier.fillMaxWidth().semantics { liveRegion = LiveRegionMode.Polite }) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.Info, contentDescription = null, tint = MaterialTheme.colorScheme.onTertiaryContainer)
            Spacer(Modifier.width(12.dp))
            Column {
                Text("Saved copy · last updated ${ExamClock.formatMillis(loaded.fetchedAtMillis)}", style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onTertiaryContainer)
                Text((loaded.staleReason?.message ?: "Could not refresh.") + " Pull down to retry.", style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onTertiaryContainer)
            }
        }
    }
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary,
        modifier = modifier.padding(top = 8.dp).semantics { heading() })
}

@Composable
fun AppCard(modifier: Modifier = Modifier, onClick: (() -> Unit)? = null, container: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f),
            content: @Composable ColumnScope.() -> Unit) {
    val colors = CardDefaults.cardColors(containerColor = container)
    if (onClick != null) Card(onClick = onClick, modifier = modifier.fillMaxWidth(), colors = colors) { Column(Modifier.padding(16.dp), content = content) }
    else Card(modifier = modifier.fillMaxWidth(), colors = colors) { Column(Modifier.padding(16.dp), content = content) }
}

@Composable
fun Tag(text: String, container: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.primaryContainer,
        content: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.onPrimaryContainer) {
    Surface(color = container, shape = MaterialTheme.shapes.small) {
        Text(text, Modifier.padding(horizontal = 8.dp, vertical = 2.dp), style = MaterialTheme.typography.labelLarge, color = content)
    }
}

@Composable
fun KeyValue(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(label, Modifier.weight(0.38f), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, Modifier.weight(0.62f), style = MaterialTheme.typography.bodyMedium)
    }
}

/**
 * Standard screen body: pull-to-refresh, first-load spinner, error with retry, stale-cache banner, empty state.
 * Everything is inside one scrollable list so pull-to-refresh works in every state.
 */
@OptIn(ExperimentalMaterial3Api::class)   // PullToRefreshBox is experimental in Material3 1.3.x
@Composable
fun <T> StateHost(
    state: ScreenState<T>, onRefresh: () -> Unit, isEmpty: (T) -> Boolean, emptyIcon: ImageVector, emptyTitle: String, emptyMessage: String,
    modifier: Modifier = Modifier, header: (LazyListScope.() -> Unit)? = null, content: LazyListScope.(T) -> Unit
) {
    PullToRefreshBox(isRefreshing = state.refreshing, onRefresh = onRefresh, modifier = modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            header?.invoke(this)
            val d = state.data
            val err = state.error
            when {
                d != null -> {
                    if (d.isStale) item { StaleBanner(d) }
                    else if (err != null) item { StaleBanner(Loaded(d.data, d.fetchedAtMillis, true, err)) }
                    if (isEmpty(d.data)) item { MessageView(emptyIcon, emptyTitle, emptyMessage) } else content(d.data)
                }
                err != null -> item { ErrorView(err, onRefresh) }
                else -> item { LoadingView() }
            }
        }
    }
}
