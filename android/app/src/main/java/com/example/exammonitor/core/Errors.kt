package com.example.exammonitor.core

enum class ErrorKind {
    NETWORK, TIMEOUT, UNAUTHORIZED, FORBIDDEN, NOT_FOUND, CONFLICT, VALIDATION, RATE_LIMITED, SERVER,
    PASSWORD_CHANGE_REQUIRED, INVALID_RESPONSE, UNKNOWN
}

data class ApiFailure(val kind: ErrorKind, val message: String, val status: Int? = null, val retryAfterSeconds: Int? = null)

sealed interface ApiResult<out T> {
    data class Success<T>(val value: T) : ApiResult<T>
    data class Failure(val failure: ApiFailure) : ApiResult<Nothing>
}

inline fun <T, R> ApiResult<T>.map(f: (T) -> R): ApiResult<R> = when (this) {
    is ApiResult.Success -> ApiResult.Success(f(value))
    is ApiResult.Failure -> this
}

/** Thrown by mappers when the server answered with something the app cannot trust. */
class InvalidResponseException(message: String) : Exception(message)

object ErrorMapper {
    /** `detail` is the already-extracted FastAPI `detail` text (may be null). It never contains credentials. */
    fun fromHttp(status: Int, detail: String?, retryAfterHeader: String? = null): ApiFailure {
        val clean = detail?.trim()?.takeIf { it.isNotEmpty() }?.take(300)
        val retry = retryAfterHeader?.trim()?.toIntOrNull()?.coerceIn(1, 86_400)
        return when {
            status == 401 -> ApiFailure(ErrorKind.UNAUTHORIZED, clean ?: "Please sign in again.", status)
            status == 403 && clean?.contains("Password change required", ignoreCase = true) == true ->
                ApiFailure(ErrorKind.PASSWORD_CHANGE_REQUIRED, "You must choose a new password before continuing.", status)
            status == 403 -> ApiFailure(ErrorKind.FORBIDDEN, clean ?: "You do not have permission to do this.", status)
            status == 404 -> ApiFailure(ErrorKind.NOT_FOUND, clean ?: "Not found.", status)
            status == 409 -> ApiFailure(ErrorKind.CONFLICT, clean ?: "This conflicts with the current state.", status)
            status == 400 || status == 422 -> ApiFailure(ErrorKind.VALIDATION, clean ?: "Please check the details you entered.", status)
            status == 429 -> ApiFailure(ErrorKind.RATE_LIMITED,
                (clean ?: "Too many requests.") + (retry?.let { " Try again in ${humanSeconds(it)}." } ?: ""), status, retry)
            status in 500..599 -> ApiFailure(ErrorKind.SERVER, "The server had a problem. Please try again shortly.", status)
            else -> ApiFailure(ErrorKind.UNKNOWN, clean ?: "Unexpected response ($status).", status)
        }
    }

    fun humanSeconds(s: Int): String = when {
        s < 60 -> "$s seconds"
        s < 3600 -> "${(s + 59) / 60} minutes"
        else -> "${(s + 3599) / 3600} hours"
    }

    fun network(timeout: Boolean) = if (timeout)
        ApiFailure(ErrorKind.TIMEOUT, "The server took too long to respond. Check your connection and try again.")
    else ApiFailure(ErrorKind.NETWORK, "Cannot reach the server. Check your internet connection and the server address.")

    fun invalid(what: String) = ApiFailure(ErrorKind.INVALID_RESPONSE, "The server sent an unexpected response ($what).")

    /** Whether showing cached data is an acceptable fallback for this failure. */
    fun allowsCacheFallback(f: ApiFailure) = f.kind in setOf(ErrorKind.NETWORK, ErrorKind.TIMEOUT, ErrorKind.SERVER, ErrorKind.RATE_LIMITED, ErrorKind.INVALID_RESPONSE)
}
