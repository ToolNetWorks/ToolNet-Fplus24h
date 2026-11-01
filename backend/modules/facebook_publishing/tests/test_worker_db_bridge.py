import asyncio
import threading

from django.test import SimpleTestCase

from modules.facebook_publishing.services.worker import _db_call


class WorkerDatabaseBridgeTests(SimpleTestCase):
    def test_db_call_uses_another_thread_when_event_loop_is_running(self):
        async def check():
            caller = threading.get_ident()
            return caller, _db_call(threading.get_ident)
        caller, worker = asyncio.run(check())
        self.assertNotEqual(caller, worker)

    def test_db_errors_are_not_silently_ignored(self):
        async def check():
            def fail():
                raise RuntimeError('database write failed')
            _db_call(fail)
        with self.assertRaisesRegex(RuntimeError, 'database write failed'):
            asyncio.run(check())
