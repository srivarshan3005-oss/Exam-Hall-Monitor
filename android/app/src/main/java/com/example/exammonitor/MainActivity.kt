package com.example.exammonitor

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.exammonitor.core.Destination
import com.example.exammonitor.core.Router
import com.example.exammonitor.ui.*
import com.example.exammonitor.ui.nav.MainScreen
import com.example.exammonitor.ui.screens.*
import com.example.exammonitor.ui.theme.ExamTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val container = (application as ExamMonitorApp).container
        setContent {
            val factory = remember { AppViewModelFactory(container) }
            val appVm: AppViewModel = viewModel(factory = factory)
            val theme by appVm.theme.collectAsStateWithLifecycle()
            ExamTheme(theme) { AppRoot(container, appVm, factory) }
        }
    }
}

@Composable
private fun AppRoot(container: AppContainer, appVm: AppViewModel, factory: AppViewModelFactory) {
    val state by appVm.session.collectAsStateWithLifecycle()
    val toast by appVm.toast.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    var screen by rememberSaveable { mutableStateOf("login") }     // login | recovery
    LaunchedEffect(Unit) { appVm.restore() }
    LaunchedEffect(toast) { toast?.let { snackbar.showSnackbar(it); appVm.consumeToast() } }

    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { _ ->
        when (val d = Router.destinationFor(state)) {
            Destination.Splash -> SplashScreen()
            is Destination.Login -> {
                if (screen == "recovery") RecoveryScreen(viewModel(factory = factory), onBack = { screen = "login" })
                else LoginScreen(viewModel(factory = factory), d.notice, onForgot = { screen = "recovery" }, allowCleartextHint = BuildConfig.ALLOW_CLEARTEXT)
            }
            Destination.ForcePasswordChange -> ChangePasswordScreen(viewModel(factory = factory), forced = true, onDone = {}, onBack = null, onLogout = { appVm.logout() })
            is Destination.Main -> (state as? com.example.exammonitor.core.SessionState.SignedIn)?.let { MainScreen(container, appVm, it.profile) }
        }
    }
}
