package com.example.exammonitor.data

import com.example.exammonitor.core.ErrorMapper
import com.google.gson.JsonElement
import com.google.gson.JsonParser
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Adds the bearer token. Credentials endpoints never get one. The token is never logged (no logging interceptor exists). */
class AuthInterceptor(private val token: () -> String?) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val req = chain.request()
        val b = req.newBuilder().header("Accept", "application/json").header("User-Agent", "ExamMonitorAndroid")
        val path = req.url.encodedPath
        val anonymous = ANONYMOUS.any { path.endsWith(it) }
        if (!anonymous && req.header("Authorization") == null) token()?.let { b.header("Authorization", "Bearer $it") }
        return chain.proceed(b.build())
    }
    companion object { val ANONYMOUS = listOf("/api/auth/login", "/api/auth/forgot-password", "/api/auth/reset-password", "/api/config", "/api/health") }
}

/** Safe retry: only idempotent GET requests are re-sent after a connection failure. POST/PUT are never auto-retried. */
class GetRetryInterceptor(private val maxRetries: Int = 2, private val sleep: (Long) -> Unit = { Thread.sleep(it) }) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val req = chain.request()
        if (req.method != "GET") return chain.proceed(req)
        var attempt = 0
        var last: IOException? = null
        while (attempt <= maxRetries) {
            if (chain.call().isCanceled()) throw IOException("Canceled")
            try { return chain.proceed(req) } catch (e: IOException) {
                last = e
                attempt++
                if (attempt <= maxRetries) sleep(400L * attempt)
            }
        }
        throw last ?: IOException("Network failure")
    }
}

/** Tells the session layer when the server rejects the token we sent (expired, revoked, idle timeout, password changed). */
class UnauthorizedInterceptor(private val onUnauthorized: (usedToken: String?) -> Unit) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val resp = chain.proceed(chain.request())
        val auth = chain.request().header("Authorization")
        val path = chain.request().url.encodedPath
        if (resp.code == 401 && auth != null && !AuthInterceptor.ANONYMOUS.any { path.endsWith(it) }) {
            onUnauthorized(auth.removePrefix("Bearer ").trim())
        }
        return resp
    }
}

object ApiClientFactory {
    fun create(baseUrl: String, token: () -> String?, onUnauthorized: (String?) -> Unit): ExamApi {
        val client = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS).callTimeout(60, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .addInterceptor(AuthInterceptor(token))
            .addInterceptor(GetRetryInterceptor())
            .addInterceptor(UnauthorizedInterceptor(onUnauthorized))
            .build()
        return Retrofit.Builder().baseUrl(baseUrl).client(client)
            .addConverterFactory(GsonConverterFactory.create()).build().create(ExamApi::class.java)
    }
}

object DetailExtractor {
    /** FastAPI errors: {"detail": "text"} | {"detail":[{"msg":..}]} | {"detail":{"message":..}}. Returns plain text or null. */
    fun fromBody(body: String?): String? {
        if (body.isNullOrBlank()) return null
        return try {
            val detail: JsonElement = JsonParser.parseString(body).asJsonObject.get("detail") ?: return null
            when {
                detail.isJsonPrimitive -> detail.asString
                detail.isJsonArray -> detail.asJsonArray.mapNotNull { e ->
                    runCatching { e.asJsonObject.get("msg")?.asString }.getOrNull()
                }.joinToString("; ").ifBlank { null }
                detail.isJsonObject -> detail.asJsonObject.get("message")?.takeIf { it.isJsonPrimitive }?.asString
                else -> null
            }
        } catch (e: Exception) { null }
    }

    fun failure(status: Int, errorBody: String?, retryAfter: String?) =
        ErrorMapper.fromHttp(status, fromBody(errorBody), retryAfter)
}
