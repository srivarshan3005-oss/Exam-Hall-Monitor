package com.example.exammonitor.data

import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.lang.reflect.Type

/**
 * Read-only cache of safe responses, namespaced per user (see CacheKeys). Stored encrypted. It is wiped on logout,
 * on session expiry and whenever a different account signs in, so private data never outlives its owner's session.
 */
class CacheStore(private val store: KeyValueStore, private val gson: Gson = Gson(), private val clock: () -> Long = System::currentTimeMillis) {
    private data class Entry(val t: Long, val v: String, val ver: Int)

    fun <T> put(userKey: String, value: T) {
        val entry = Entry(clock(), gson.toJson(value), VERSION)
        store.put(PREFIX + userKey, gson.toJson(entry))
    }

    fun <T> get(userKey: String, type: Type): Pair<T, Long>? {
        val raw = store.get(PREFIX + userKey) ?: return null
        return try {
            val e = gson.fromJson(raw, Entry::class.java)
            if (e == null || e.ver != VERSION || e.v == null) null
            else gson.fromJson<T>(e.v, type)?.let { it to e.t }
        } catch (ex: Exception) { null }
    }

    fun clearAll() {
        store.keys().filter { it.startsWith(PREFIX) }.forEach { store.remove(it) }
    }

    fun clearForOtherUsers(username: String) {
        store.keys().filter { it.startsWith(PREFIX) && !com.example.exammonitor.core.CacheKeys.belongsTo(it.removePrefix(PREFIX), username) }
            .forEach { store.remove(it) }
    }

    companion object {
        const val VERSION = 1
        private const val PREFIX = "cache|"
        inline fun <reified T> typeOf(): Type = object : TypeToken<T>() {}.type
    }
}
