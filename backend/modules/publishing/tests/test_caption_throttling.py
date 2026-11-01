from types import SimpleNamespace

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from modules.api.v1.publishing.caption_views import (
    CaptionGenerateThrottle, CaptionJobAPIView, CaptionReadThrottle,
    CaptionWriteThrottle,
)


@override_settings(CACHES={'default': {
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'LOCATION': 'caption-throttle-test',
}})
class CaptionThrottleTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True, pk=123))

    def test_generation_limit_does_not_block_reads_or_approval(self):
        for _ in range(4):
            self.assertTrue(CaptionGenerateThrottle().allow_request(self.request, None))
        self.assertFalse(CaptionGenerateThrottle().allow_request(self.request, None))
        self.assertTrue(CaptionReadThrottle().allow_request(self.request, None))
        self.assertTrue(CaptionWriteThrottle().allow_request(self.request, None))

    def test_job_action_selects_correct_limit(self):
        view = CaptionJobAPIView()
        for method, data, expected in (
            ('GET', {}, CaptionReadThrottle),
            ('POST', {'action': 'generate'}, CaptionGenerateThrottle),
            ('POST', {'action': 'approve'}, CaptionWriteThrottle),
            ('POST', {'action': 'reject'}, CaptionWriteThrottle),
        ):
            view.request = SimpleNamespace(method=method, data=data)
            self.assertIsInstance(view.get_throttles()[0], expected)
