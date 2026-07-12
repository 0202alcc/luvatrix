from __future__ import annotations

from threading import Event
import unittest

from luvatrix.app import InteractionAwareWorkScheduler


class InteractionAwareWorkSchedulerTests(unittest.TestCase):
    def test_work_waits_until_interaction_is_idle_then_invalidates(self) -> None:
        interaction_active = Event()
        interaction_active.set()
        started = Event()
        completed = Event()
        results: list[str] = []
        renders: list[str] = []
        scheduler = InteractionAwareWorkScheduler(
            interaction_active=interaction_active.is_set,
            request_render=lambda: renders.append("render"),
            idle_poll_interval=0.005,
        )
        self.addCleanup(scheduler.close, wait=True)

        accepted = scheduler.submit(
            "event:123",
            lambda: started.set() or "prepared",
            on_complete=lambda value: (results.append(value), completed.set()),
        )

        self.assertTrue(accepted)
        self.assertFalse(started.wait(0.05))
        interaction_active.clear()
        scheduler.notify_interaction_state_changed()

        self.assertTrue(completed.wait(1.0))
        self.assertTrue(scheduler.wait_idle(timeout=1.0))
        self.assertEqual(results, ["prepared"])
        self.assertEqual(renders, ["render"])

    def test_duplicate_keys_are_rejected_while_work_is_pending(self) -> None:
        interaction_active = Event()
        interaction_active.set()
        scheduler = InteractionAwareWorkScheduler(
            interaction_active=interaction_active.is_set,
            idle_poll_interval=0.005,
        )
        self.addCleanup(scheduler.close, wait=True)

        self.assertTrue(scheduler.submit("event:123", lambda: None))
        self.assertFalse(scheduler.submit("event:123", lambda: None))
        self.assertEqual(scheduler.pending_count, 1)

    def test_work_errors_are_reported_without_stopping_the_worker(self) -> None:
        errors: list[tuple[str, str]] = []
        completed = Event()
        scheduler = InteractionAwareWorkScheduler(
            interaction_active=lambda: False,
            on_error=lambda key, error: errors.append((key, str(error))),
            idle_poll_interval=0.005,
        )
        self.addCleanup(scheduler.close, wait=True)

        def fail() -> None:
            raise ValueError("bad event")

        self.assertTrue(scheduler.submit("bad", fail))
        self.assertTrue(
            scheduler.submit("good", lambda: "ok", on_complete=lambda _value: completed.set())
        )

        self.assertTrue(completed.wait(1.0))
        self.assertTrue(scheduler.wait_idle(timeout=1.0))
        self.assertEqual(errors, [("bad", "bad event")])


if __name__ == "__main__":
    unittest.main()
