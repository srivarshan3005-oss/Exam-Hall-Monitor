package com.example.exammonitor.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.exammonitor.BuildConfig
import com.example.exammonitor.core.Role
import com.example.exammonitor.core.UserProfile
import com.example.exammonitor.ui.components.AppCard
import com.example.exammonitor.ui.components.KeyValue
import com.example.exammonitor.ui.components.SectionTitle

@Composable
fun ProfileScreen(profile: UserProfile, serverUrl: String, themeMode: String, onTheme: (String) -> Unit, onPreferences: () -> Unit,
                  onChangePassword: () -> Unit, onLogout: () -> Unit) {
    var confirm by remember { mutableStateOf(false) }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { SectionTitle("Account") }
        item { AppCard {
            Text(profile.studentName ?: profile.username, style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(8.dp))
            KeyValue("Username", profile.username)
            KeyValue("Role", profile.roleLabel)
            profile.registerNumber?.let { KeyValue("Register no.", it) }
            profile.department?.takeIf { it.isNotBlank() }?.let { KeyValue("Department", it) }
            profile.email?.takeIf { it.isNotBlank() }?.let { KeyValue("E-mail", it) }
            if (profile.role == Role.STUDENT && profile.registerNumber == null)
                Text("Your account is not linked to a student record yet. Contact the examination office.", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
        } }
        item { SectionTitle("Appearance") }
        item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("system" to "System", "light" to "Light", "dark" to "Dark").forEach { (v, l) ->
                FilterChip(selected = themeMode == v, onClick = { onTheme(v) }, label = { Text(l) })
            }
        } }
        item { SectionTitle("Settings") }
        item { OutlinedButton(onClick = onPreferences, modifier = Modifier.fillMaxWidth()) { Text("Notification preferences") } }
        item { OutlinedButton(onClick = onChangePassword, modifier = Modifier.fillMaxWidth()) { Text("Change password") } }
        item { SectionTitle("About") }
        item { AppCard {
            KeyValue("Server", serverUrl)
            KeyValue("App version", BuildConfig.VERSION_NAME)
            Text("Private data is kept only in encrypted storage and is removed when you sign out.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } }
        item { Button(onClick = { confirm = true }, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error), modifier = Modifier.fillMaxWidth()) { Text("Sign out") } }
    }
    if (confirm) AlertDialog(onDismissRequest = { confirm = false }, title = { Text("Sign out?") },
        text = { Text("Saved data on this device will be erased.") },
        confirmButton = { TextButton(onClick = { confirm = false; onLogout() }) { Text("Sign out") } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } })
}
