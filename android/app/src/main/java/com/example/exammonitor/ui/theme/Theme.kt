package com.example.exammonitor.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

private val LightColors = lightColorScheme(
    primary = Color(0xFF1F3A8A), onPrimary = Color.White, primaryContainer = Color(0xFFDCE4FF), onPrimaryContainer = Color(0xFF0B1B4D),
    secondary = Color(0xFF0F766E), onSecondary = Color.White, secondaryContainer = Color(0xFFCCF1EC), onSecondaryContainer = Color(0xFF00201D),
    tertiary = Color(0xFFB45309), tertiaryContainer = Color(0xFFFFE8CC), onTertiaryContainer = Color(0xFF3A1C00),
    background = Color(0xFFF7F8FC), surface = Color(0xFFF7F8FC), surfaceVariant = Color(0xFFE3E6F0), onSurfaceVariant = Color(0xFF44474F),
    error = Color(0xFFB3261E), errorContainer = Color(0xFFF9DEDC), onErrorContainer = Color(0xFF410E0B)
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFB4C5FF), onPrimary = Color(0xFF0B1B4D), primaryContainer = Color(0xFF2B4299), onPrimaryContainer = Color(0xFFDCE4FF),
    secondary = Color(0xFF7FD6CB), onSecondary = Color(0xFF003732), secondaryContainer = Color(0xFF00504A), onSecondaryContainer = Color(0xFFCCF1EC),
    tertiary = Color(0xFFFFB86B), tertiaryContainer = Color(0xFF6B3A00), onTertiaryContainer = Color(0xFFFFE8CC),
    background = Color(0xFF11131A), surface = Color(0xFF11131A), surfaceVariant = Color(0xFF2C2F3A), onSurfaceVariant = Color(0xFFC5C8D4),
    error = Color(0xFFF2B8B5), errorContainer = Color(0xFF8C1D18), onErrorContainer = Color(0xFFF9DEDC)
)

private val AppTypography = Typography(
    headlineMedium = TextStyle(fontSize = 26.sp, lineHeight = 32.sp, fontWeight = FontWeight.SemiBold),
    titleLarge = TextStyle(fontSize = 21.sp, lineHeight = 28.sp, fontWeight = FontWeight.SemiBold),
    titleMedium = TextStyle(fontSize = 16.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold),
    bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 24.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
    labelLarge = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.Medium)
)

/** [mode]: "system" | "light" | "dark". */
@Composable
fun ExamTheme(mode: String, content: @Composable () -> Unit) {
    val dark = when (mode) { "dark" -> true; "light" -> false; else -> isSystemInDarkTheme() }
    MaterialTheme(colorScheme = if (dark) DarkColors else LightColors, typography = AppTypography, content = content)
}
