plugins {
    id("com.android.application")
}

android {
    namespace = "com.munjajikimi"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.munjajikimi"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
