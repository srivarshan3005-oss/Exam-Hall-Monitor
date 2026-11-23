package com.example.exammonitor.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.exammonitor.ui.ChangePasswordViewModel
import com.example.exammonitor.ui.LoginViewModel
import com.example.exammonitor.ui.RecoveryViewModel
import com.example.exammonitor.ui.components.AppCard

@Composable
fun SplashScreen() {
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.primary) {
        Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
            Text("EM", style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.onPrimary)
            Spacer(Modifier.height(8.dp))
            Text("Exam Monitor", style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.onPrimary)
            Text("University examination portal", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onPrimary)
            Spacer(Modifier.height(24.dp))
            CircularProgressIndicator(color = MaterialTheme.colorScheme.onPrimary)
        }
    }
}

@Composable
fun PasswordField(value: String, onChange: (String) -> Unit, label: String, modifier: Modifier = Modifier,
                  imeAction: ImeAction = ImeAction.Next, onDone: (() -> Unit)? = null) {
    var visible by remember { mutableStateOf(false) }
    OutlinedTextField(
        value = value, onValueChange = onChange, label = { Text(label) }, singleLine = true, modifier = modifier.fillMaxWidth(),
        visualTransformation = if (visible) VisualTransformation.None else PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = imeAction),
        keyboardActions = KeyboardActions(onDone = { onDone?.invoke() }),
        trailingIcon = { TextButton(onClick = { visible = !visible }) { Text(if (visible) "Hide" else "Show") } }
    )
}

@Composable
private fun ErrorText(text: String?) {
    if (text != null) Text(text, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium,
        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Assertive })
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoginScreen(vm: LoginViewModel, notice: String?, onForgot: () -> Unit, allowCleartextHint: Boolean) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    var username by rememberSaveable { mutableStateOf("") }
    var password by remember { mutableStateOf("") }          // never saved to instance state
    var showServer by rememberSaveable { mutableStateOf(false) }
    var server by rememberSaveable(ui.serverUrl) { mutableStateOf(ui.serverUrl) }
    val submit = { vm.login(username, password) }

    Surface(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).imePadding().systemBarsPadding().padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Surface(color = MaterialTheme.colorScheme.primary, shape = MaterialTheme.shapes.large, modifier = Modifier.size(72.dp)) {
                Box(contentAlignment = Alignment.Center) { Text("EM", style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.onPrimary) }
            }
            Spacer(Modifier.height(16.dp))
            Text("Exam Monitor", style = MaterialTheme.typography.headlineMedium)
            Text("Sign in with your university account", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(24.dp))
            if (notice != null) {
                AppCard(container = MaterialTheme.colorScheme.secondaryContainer) {
                    Text(notice, color = MaterialTheme.colorScheme.onSecondaryContainer, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
                }
                Spacer(Modifier.height(16.dp))
            }
            OutlinedTextField(value = username, onValueChange = { username = it }, label = { Text("Username or register number") },
                singleLine = true, modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii, imeAction = ImeAction.Next))
            Spacer(Modifier.height(12.dp))
            PasswordField(password, { password = it }, "Password", imeAction = ImeAction.Done, onDone = { if (!ui.busy) submit() })
            Spacer(Modifier.height(8.dp))
            ErrorText(ui.error)
            Spacer(Modifier.height(12.dp))
            Button(onClick = submit, enabled = !ui.busy && username.isNotBlank() && password.isNotEmpty(), modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp)) {
                if (ui.busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary) else Text("Sign in")
            }
            TextButton(onClick = onForgot) { Text("Forgot password?") }
            TextButton(onClick = { showServer = !showServer }) { Text(if (showServer) "Hide server settings" else "Server settings") }
            if (showServer) {
                OutlinedTextField(value = server, onValueChange = { server = it }, label = { Text("Server address") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done),
                    supportingText = { Text(if (allowCleartextHint) "Debug build: http:// is allowed for local testing." else "HTTPS is required. Use the address your institution gave you.") })
                Spacer(Modifier.height(8.dp))
                OutlinedButton(onClick = { vm.saveServer(server) }, modifier = Modifier.fillMaxWidth()) { Text("Save address") }
                ui.serverMessage?.let { Text(it, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp)) }
            }
            Spacer(Modifier.height(16.dp))
            Text("Your password is sent only to your institution's server and is never stored on this device.",
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecoveryScreen(vm: RecoveryViewModel, onBack: () -> Unit) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    var step by rememberSaveable { mutableIntStateOf(0) }          // 0 = ask for link, 1 = use link
    var identifier by rememberSaveable { mutableStateOf("") }
    var link by remember { mutableStateOf("") }
    var pw by remember { mutableStateOf("") }
    var pw2 by remember { mutableStateOf("") }
    val mismatch = pw2.isNotEmpty() && pw != pw2

    Scaffold(topBar = {
        TopAppBar(title = { Text("Reset password") }, navigationIcon = {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back to sign in") }
        })
    }) { pad ->
        Column(Modifier.padding(pad).fillMaxSize().verticalScroll(rememberScrollState()).imePadding().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (step == 0) {
                Text("Enter your username or e-mail address. If an active account matches, the university e-mails you a reset link.", style = MaterialTheme.typography.bodyLarge)
                OutlinedTextField(value = identifier, onValueChange = { identifier = it }, label = { Text("Username or e-mail") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Done))
                ErrorText(ui.error)
                ui.info?.let { Text(it, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
                Button(onClick = { vm.requestLink(identifier) }, enabled = !ui.busy && identifier.trim().length >= 3, modifier = Modifier.fillMaxWidth()) {
                    Text(if (ui.busy) "Sending…" else "Send reset link")
                }
                OutlinedButton(onClick = { vm.clear(); step = 1 }, modifier = Modifier.fillMaxWidth()) { Text("I already have a reset link") }
            } else {
                Text("Paste the link from the e-mail (or just its code) and choose a new password.", style = MaterialTheme.typography.bodyLarge)
                OutlinedTextField(value = link, onValueChange = { link = it }, label = { Text("Reset link or code") }, modifier = Modifier.fillMaxWidth(), minLines = 2,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
                PasswordField(pw, { pw = it }, "New password")
                PasswordField(pw2, { pw2 = it }, "Confirm new password", imeAction = ImeAction.Done)
                Text("At least 12 characters with a letter and a digit.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (mismatch) ErrorText("The passwords do not match.")
                ErrorText(ui.error)
                ui.info?.let { Text(it, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
                if (ui.done) Button(onClick = onBack, modifier = Modifier.fillMaxWidth()) { Text("Back to sign in") }
                else Button(onClick = { vm.reset(link, pw) }, enabled = !ui.busy && link.isNotBlank() && pw.isNotEmpty() && pw == pw2, modifier = Modifier.fillMaxWidth()) {
                    Text(if (ui.busy) "Saving…" else "Set new password")
                }
                TextButton(onClick = { vm.clear(); step = 0 }) { Text("Request a new link") }
            }
        }
    }
}

/** Used both for the forced change after an administrator reset (forced = true) and from the profile screen. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChangePasswordScreen(vm: ChangePasswordViewModel, forced: Boolean, onDone: () -> Unit, onBack: (() -> Unit)?, onLogout: (() -> Unit)? = null) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    var cur by remember { mutableStateOf("") }
    var new by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf("") }
    LaunchedEffect(ui.success) { if (ui.success) { cur = ""; new = ""; confirm = ""; onDone() } }

    Scaffold(topBar = {
        TopAppBar(title = { Text(if (forced) "Choose a new password" else "Change password") }, navigationIcon = {
            if (onBack != null) IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") }
        })
    }) { pad ->
        Column(Modifier.padding(pad).fillMaxSize().verticalScroll(rememberScrollState()).imePadding().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (forced) AppCard(container = MaterialTheme.colorScheme.tertiaryContainer) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.Lock, contentDescription = null); Spacer(Modifier.width(12.dp))
                    Text("Your administrator requires a new password before you can continue.")
                }
            }
            PasswordField(cur, { cur = it }, "Current password")
            PasswordField(new, { new = it }, "New password")
            PasswordField(confirm, { confirm = it }, "Confirm new password", imeAction = ImeAction.Done)
            Text("At least 12 characters with a letter and a digit. Other devices are signed out when you change it.", style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            ErrorText(ui.error)
            Button(onClick = { vm.submit(cur, new, confirm) }, enabled = !ui.busy && cur.isNotEmpty() && new.isNotEmpty() && confirm.isNotEmpty(), modifier = Modifier.fillMaxWidth()) {
                Text(if (ui.busy) "Saving…" else "Change password")
            }
            if (onLogout != null) TextButton(onClick = onLogout) { Text("Sign out instead") }
        }
    }
}
