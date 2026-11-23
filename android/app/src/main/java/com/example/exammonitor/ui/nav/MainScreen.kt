package com.example.exammonitor.ui.nav

import android.net.Uri
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.example.exammonitor.AppContainer
import com.example.exammonitor.core.*
import com.example.exammonitor.ui.*
import com.example.exammonitor.ui.screens.*

private fun iconFor(t: AppTab): ImageVector = when (t) {
    AppTab.HOME -> Icons.Filled.Home
    AppTab.TIMETABLE -> Icons.Filled.DateRange
    AppTab.RESULTS -> Icons.Filled.CheckCircle
    AppTab.EXAMS -> Icons.AutoMirrored.Filled.List
    AppTab.STUDENTS -> Icons.Filled.Search
    AppTab.ALERTS -> Icons.Filled.Notifications
    AppTab.PROFILE -> Icons.Filled.AccountCircle
}

private const val PREFS = "prefs"
private const val CHANGE_PW = "changepw"
private const val NOTIF = "notification/{id}"
private const val EXAM = "exam/{id}?title={title}"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(container: AppContainer, appVm: AppViewModel, profile: UserProfile) {
    val role = profile.role
    val nav = rememberNavController()
    // Every ViewModel with private data lives in this store; it is emptied at sign-out / session expiry.
    val owner = remember(appVm) { object : ViewModelStoreOwner { override val viewModelStore: ViewModelStore get() = appVm.privateStore } }
    val factory = remember(container) { AppViewModelFactory(container) }
    val snackbar = remember { SnackbarHostState() }
    val tabs = remember(role) { Navigation.tabsFor(role) }
    val entry by nav.currentBackStackEntryAsState()
    val route = entry?.destination?.route
    val topLevel = tabs.firstOrNull { it.route == route }
    val theme by appVm.theme.collectAsStateWithLifecycle()
    val notifVm: AlertsViewModel = viewModel(viewModelStoreOwner = owner, factory = factory)
    val unread by notifVm.unread.collectAsStateWithLifecycle()

    fun goTab(t: AppTab) {
        if (!Navigation.canOpen(role, t.route)) return
        nav.navigate(t.route) { popUpTo(nav.graph.findStartDestination().id) { saveState = true }; launchSingleTop = true; restoreState = true }
    }

    val title = when {
        topLevel != null -> if (topLevel == AppTab.HOME) "Exam Monitor" else topLevel.label
        route == PREFS -> "Notification preferences"
        route == CHANGE_PW -> "Change password"
        route == NOTIF -> "Notification"
        route == EXAM -> entry?.arguments?.getString("title")?.takeIf { it.isNotBlank() } ?: "Examination"
        else -> "Exam Monitor"
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text(title) }, navigationIcon = {
            if (topLevel == null && route != null) IconButton(onClick = { nav.popBackStack() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") }
        }) },
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            if (topLevel != null) NavigationBar {
                tabs.forEach { t ->
                    NavigationBarItem(selected = topLevel == t, onClick = { goTab(t) }, label = { Text(t.label) }, icon = {
                        if (t == AppTab.ALERTS && unread > 0) BadgedBox(badge = { Badge { Text(if (unread > 99) "99+" else unread.toString()) } }) { Icon(iconFor(t), contentDescription = "${t.label}, $unread unread") }
                        else Icon(iconFor(t), contentDescription = t.label)
                    })
                }
            }
        }
    ) { pad ->
        NavHost(nav, startDestination = AppTab.HOME.route, modifier = Modifier.padding(pad)) {
            composable(AppTab.HOME.route) {
                val vm: HomeViewModel = viewModel(viewModelStoreOwner = owner, factory = factory)
                HomeScreen(vm, profile, onOpenTab = ::goTab)
            }
            if (role == Role.STUDENT) {
                composable(AppTab.TIMETABLE.route) { TimetableScreen(viewModel<TimetableViewModel>(viewModelStoreOwner = owner, factory = factory)) }
                composable(AppTab.RESULTS.route) { ResultsScreen(viewModel<ResultsViewModel>(viewModelStoreOwner = owner, factory = factory)) }
            } else {
                composable(AppTab.EXAMS.route) {
                    val vm: ExamListViewModel = viewModel(viewModelStoreOwner = owner, factory = factory)
                    ExamsScreen(vm, role, snackbar) { e -> nav.navigate("exam/${e.id}?title=${Uri.encode(e.title)}") }
                }
                composable(EXAM, arguments = listOf(navArgument("id") { type = NavType.IntType }, navArgument("title") { type = NavType.StringType; defaultValue = "" })) { be ->
                    val id = be.arguments?.getInt("id") ?: 0
                    val vm: ExamDetailViewModel = viewModel(viewModelStoreOwner = owner, key = "exam-$id", factory = AppViewModelFactory(container, role, id))
                    ExamDetailScreen(vm, role)
                }
                if (Permissions.can(role, Capability.LOOKUP_STUDENT_SEATS))
                    composable(AppTab.STUDENTS.route) { StudentsScreen(viewModel<StudentSearchViewModel>(viewModelStoreOwner = owner, factory = factory)) }
            }
            composable(AppTab.ALERTS.route) { AlertsScreen(notifVm, snackbar, onOpen = { nav.navigate("notification/${it.id}") }, onPreferences = { nav.navigate(PREFS) }) }
            composable(NOTIF, arguments = listOf(navArgument("id") { type = NavType.IntType })) { be ->
                val id = be.arguments?.getInt("id") ?: 0
                val vm: NotificationDetailViewModel = viewModel(viewModelStoreOwner = owner, key = "notif-$id", factory = AppViewModelFactory(container, role, id))
                NotificationDetailScreen(vm, role, onOpenTab = { goTab(it) }, onClosed = { nav.popBackStack(); notifVm.refresh() })
            }
            composable(PREFS) { PreferencesScreen(viewModel<PreferencesViewModel>(viewModelStoreOwner = owner, factory = factory), snackbar) }
            composable(AppTab.PROFILE.route) {
                ProfileScreen(profile, container.baseUrl, theme, onTheme = { appVm.themeMode = it }, onPreferences = { nav.navigate(PREFS) },
                    onChangePassword = { nav.navigate(CHANGE_PW) }, onLogout = { appVm.logout() })
            }
            composable(CHANGE_PW) {
                val vm: ChangePasswordViewModel = viewModel(viewModelStoreOwner = owner, factory = factory)
                ChangePasswordScreen(vm, forced = false, onDone = { nav.popBackStack() }, onBack = { nav.popBackStack() })
            }
        }
    }
}
