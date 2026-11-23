plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Override at build time: ./gradlew assembleRelease -PAPI_BASE_URL=https://exams.your-university.edu/
// Also accepted from the environment variable API_BASE_URL. Release builds REQUIRE it (see the task-graph check below).
val apiBaseUrl: String = ((project.findProperty("API_BASE_URL") as String?) ?: System.getenv("API_BASE_URL"))?.trim().orEmpty()
if (apiBaseUrl.isNotEmpty() && !apiBaseUrl.startsWith("https://", ignoreCase = true)) {
    throw GradleException("Release API_BASE_URL must use HTTPS.")
}
// Release signing inputs: Gradle properties (-P... or ~/.gradle/gradle.properties) or environment variables.
// The keystore and its passwords must live OUTSIDE this repository and are never packaged in the release ZIP.
val releaseSigningInputs: Map<String, String?> = listOf(
    "RELEASE_STORE_FILE", "RELEASE_STORE_PASSWORD", "RELEASE_KEY_ALIAS", "RELEASE_KEY_PASSWORD"
).associateWith { name -> providers.gradleProperty(name).orNull?.takeIf { it.isNotBlank() } ?: System.getenv(name)?.takeIf { it.isNotBlank() } }
val releaseStoreFile = releaseSigningInputs["RELEASE_STORE_FILE"]
val releaseStorePassword = releaseSigningInputs["RELEASE_STORE_PASSWORD"]
val releaseKeyAlias = releaseSigningInputs["RELEASE_KEY_ALIAS"]
val releaseKeyPassword = releaseSigningInputs["RELEASE_KEY_PASSWORD"]
val missingReleaseSigningInputs = releaseSigningInputs.filterValues { it == null }.keys
// Signing is applied only when all four values are present; with none present the release artifact stays unsigned.
val hasReleaseSigning = missingReleaseSigningInputs.isEmpty()
val partialReleaseSigning = !hasReleaseSigning && missingReleaseSigningInputs.size < releaseSigningInputs.size

// A half-configured release must fail loudly instead of silently producing an unsigned or mis-signed artifact.
// Debug/test tasks are unaffected. Values (passwords) are never printed.
gradle.taskGraph.whenReady {
    val releaseRequested = allTasks.any { it.project == project && it.name.contains("Release", ignoreCase = true) }
    if (releaseRequested && apiBaseUrl.isEmpty()) {
        throw GradleException("Release builds need the production backend URL: pass -PAPI_BASE_URL=https://your-domain/ " +
            "(or set the API_BASE_URL environment variable). No default address is built into release artifacts.")
    }
    if (releaseRequested && partialReleaseSigning) {
        throw GradleException(
            "Incomplete release signing configuration. Provide all four of RELEASE_STORE_FILE, RELEASE_STORE_PASSWORD, " +
                "RELEASE_KEY_ALIAS and RELEASE_KEY_PASSWORD (or none, for an unsigned release). Missing: " +
                missingReleaseSigningInputs.joinToString()
        )
    }
    if (releaseRequested && hasReleaseSigning && !file(releaseStoreFile!!).isFile) {
        throw GradleException("RELEASE_STORE_FILE does not point to an existing keystore file: $releaseStoreFile " +
            "(use an absolute path; a relative path is resolved against android/app).")
    }
}

android {
    namespace = "com.example.exammonitor"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.example.exammonitor"
        minSdk = 26
        targetSdk = 35
        versionCode = 3
        versionName = "0.8.1"
    }
    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(releaseStoreFile!!)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }
    buildTypes {
        debug {
            buildConfigField("String", "DEFAULT_API_URL", "\"${apiBaseUrl.ifEmpty { "http://10.0.2.2:8000/" }}\"")
            buildConfigField("boolean", "ALLOW_CLEARTEXT", "true")   // local testing only (see src/debug)
        }
        release {
            isMinifyEnabled = false   // R8 not verified for this app yet; see android/README.md
            buildConfigField("String", "DEFAULT_API_URL", "\"${apiBaseUrl.ifEmpty { "https://api-base-url-not-configured.invalid/" }}\"")
            buildConfigField("boolean", "ALLOW_CLEARTEXT", "false")
            if (hasReleaseSigning) signingConfig = signingConfigs.getByName("release")
        }
    }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    testOptions { unitTests.isReturnDefaultValues = true }
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.activity:activity-compose:1.10.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.navigation:navigation-compose:2.8.5")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-gson:2.11.0")
    implementation("com.google.code.gson:gson:2.11.0")
    debugImplementation("androidx.compose.ui:ui-tooling")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}
