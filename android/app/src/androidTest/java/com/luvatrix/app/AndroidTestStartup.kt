package com.luvatrix.app

import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.PyObject
import java.util.concurrent.TimeUnit

internal fun awaitPythonModule(): PyObject {
    val context = InstrumentationRegistry.getInstrumentation().targetContext
    val application = context.applicationContext as LuvatrixApplication
    return application.pythonStartup.future.get(60, TimeUnit.SECONDS)
}
