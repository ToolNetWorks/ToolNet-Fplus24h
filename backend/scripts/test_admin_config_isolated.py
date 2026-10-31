"""Configuration/Caption regression suite, isolated database and temporary worker locks."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings_test_config'

import django

django.setup()
from django.conf import settings
from django.test.runner import DiscoverRunner

if set(settings.DATABASES) != {'default'} or settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
    raise RuntimeError('Refusing tests outside isolated SQLite configuration.')

with tempfile.TemporaryDirectory(prefix='toolnet-ai-test-locks-') as directory:
    with patch('modules.publishing.management.commands.publishing_caption_tick.LOCK_PATH', Path(directory) / 'caption.lock'), patch('modules.publishing.management.commands.publishing_recovery_tick.LOCK_PATH', Path(directory) / 'recovery.lock'):
        failures = DiscoverRunner(interactive=False, verbosity=1).run_tests([
            'modules.system_config',
            'modules.publishing.tests.test_caption_isolated',
            'modules.publishing.tests.test_caption_tick_recovery',
        ])
sys.exit(bool(failures))
