package com.luvatrix.benchmark

import android.content.Intent
import androidx.benchmark.macro.MacrobenchmarkScope

internal const val TARGET_PACKAGE = "com.luvatrix.app"
internal const val TARGET_ACTIVITY = "$TARGET_PACKAGE.MainActivity"

internal fun MacrobenchmarkScope.startMainActivityAndWait() {
    val intent = Intent(Intent.ACTION_MAIN).apply {
        setClassName(TARGET_PACKAGE, TARGET_ACTIVITY)
        addCategory(Intent.CATEGORY_LAUNCHER)
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
    }
    startActivityAndWait(intent)
}
