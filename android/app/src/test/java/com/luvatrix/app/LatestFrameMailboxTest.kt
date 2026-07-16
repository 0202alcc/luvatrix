package com.luvatrix.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LatestFrameMailboxTest {
    @Test
    fun pendingPresentationKeepsOnlyTheNewestFrame() {
        val mailbox = LatestFrameMailbox<String>()

        assertTrue(mailbox.offer("frame-1"))
        assertFalse(mailbox.offer("frame-2"))
        assertFalse(mailbox.offer("frame-3"))

        assertEquals("frame-3", mailbox.take())
        assertNull(mailbox.take())
        assertTrue(mailbox.offer("frame-4"))
    }
}
