package com.example.exammonitor.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Minimal key/value abstraction so storage can be swapped for an in-memory fake in unit tests. */
interface KeyValueStore {
    fun get(key: String): String?
    fun put(key: String, value: String)
    fun remove(key: String)
    fun keys(): Set<String>
    fun clear()
}

class InMemoryStore : KeyValueStore {
    private val map = LinkedHashMap<String, String>()
    @Synchronized override fun get(key: String) = map[key]
    @Synchronized override fun put(key: String, value: String) { map[key] = value }
    @Synchronized override fun remove(key: String) { map.remove(key) }
    @Synchronized override fun keys(): Set<String> = map.keys.toSet()
    @Synchronized override fun clear() = map.clear()
}

/** AES-256 encrypted SharedPreferences backed by the Android Keystore. Holds the access token, profile and cache. */
class EncryptedPrefsStore(context: Context, private val fileName: String) : KeyValueStore {
    private val prefs: SharedPreferences = open(context.applicationContext, fileName)

    override fun get(key: String): String? = prefs.getString(key, null)
    override fun put(key: String, value: String) { prefs.edit().putString(key, value).apply() }
    override fun remove(key: String) { prefs.edit().remove(key).apply() }
    override fun keys(): Set<String> = prefs.all.keys.toSet()
    override fun clear() { prefs.edit().clear().apply() }

    private companion object {
        fun open(ctx: Context, name: String): SharedPreferences {
            fun create(): SharedPreferences {
                val key = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
                return EncryptedSharedPreferences.create(ctx, name, key,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM)
            }
            return try { create() } catch (e: Exception) {
                // A restored backup or a reset keystore leaves undecryptable data. Dropping it only signs the user out.
                ctx.deleteSharedPreferences(name)
                create()
            }
        }
    }
}

/** Plain, non-sensitive settings (server address, theme choice). */
class SettingsStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("exam_monitor_settings", Context.MODE_PRIVATE)
    var serverUrl: String?
        get() = prefs.getString("server_url", null)
        set(v) { prefs.edit().putString("server_url", v).apply() }
    var themeMode: String
        get() = prefs.getString("theme_mode", "system") ?: "system"
        set(v) { prefs.edit().putString("theme_mode", v).apply() }
}
