package com.example.exammonitor.core

/** Client-side hints that mirror the backend password policy. The backend stays authoritative. */
object PasswordPolicy {
    fun problems(password: String, username: String? = null): List<String> {
        val out = mutableListOf<String>()
        if (password.length < 12) out += "Use at least 12 characters"
        if (password.length > 128) out += "Use at most 128 characters"
        if (password.none { it.isLetter() } || password.none { it.isDigit() }) out += "Include at least one letter and one digit"
        if (password.toSet().size < 5) out += "Use more variety of characters"
        if (username != null && username.length >= 3 && password.contains(username, ignoreCase = true)) out += "Must not contain your username"
        return out
    }
}

/** The reset e-mail contains a web link `…/?reset=<token>`. Accept the whole link or just the token. */
object ResetTokenParser {
    private val tokenRegex = Regex("^[A-Za-z0-9_\\-]{20,200}$")

    fun extract(input: String): String? {
        val text = input.trim()
        if (text.isEmpty()) return null
        val candidate = Regex("[?&#]reset=([^&#\\s]+)").find(text)?.groupValues?.get(1) ?: text
        return candidate.takeIf { tokenRegex.matches(it) }
    }
}

sealed interface UrlCheck {
    data class Ok(val baseUrl: String) : UrlCheck
    data class Rejected(val reason: String) : UrlCheck
}

object ApiUrl {
    /** Normalises a server address to a base URL ending in '/'. HTTPS is mandatory unless [allowCleartext] (debug builds). */
    fun check(raw: String, allowCleartext: Boolean): UrlCheck {
        var s = raw.trim()
        if (s.isEmpty()) return UrlCheck.Rejected("Enter the server address.")
        if (!s.contains("://")) s = "https://$s"
        val m = Regex("^(https?)://([^/?#\\s]+)(/[^?#\\s]*)?$", RegexOption.IGNORE_CASE).matchEntire(s)
            ?: return UrlCheck.Rejected("That does not look like a valid web address.")
        val scheme = m.groupValues[1].lowercase()
        val host = m.groupValues[2]
        if (host.contains("@")) return UrlCheck.Rejected("Addresses with embedded credentials are not allowed.")
        if (scheme == "http" && !allowCleartext) return UrlCheck.Rejected("This build only connects over HTTPS.")
        val path = (m.groupValues[3].ifEmpty { "/" }).let { if (it.endsWith("/")) it else "$it/" }
        return UrlCheck.Ok("$scheme://$host$path")
    }
}

object LoginValidation {
    fun problem(username: String, password: String): String? = when {
        username.isBlank() -> "Enter your username or register number."
        password.isEmpty() -> "Enter your password."
        username.length > 80 || password.length > 128 -> "That input is too long."
        else -> null
    }
}
