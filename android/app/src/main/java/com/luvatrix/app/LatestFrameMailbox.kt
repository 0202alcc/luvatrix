package com.luvatrix.app

/** A single-slot latest-wins queue for render work crossing onto the UI thread. */
class LatestFrameMailbox<T : Any> {
    private var pending: T? = null
    private var presentationScheduled = false

    @Synchronized
    fun offer(value: T): Boolean {
        pending = value
        if (presentationScheduled) return false
        presentationScheduled = true
        return true
    }

    @Synchronized
    fun take(): T? {
        val value = pending
        pending = null
        presentationScheduled = false
        return value
    }
}
