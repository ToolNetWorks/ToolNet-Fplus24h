"""Inspect Facebook's first-time participation prompt without accepting it.

The prompt appears after an irreversible post click.  Its contents may be
account-specific, so merely detecting it never authorizes joining a group,
accepting rules, answering questions, or clicking its submit button.
"""
import hashlib
import json
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)
PROMPT_TITLE = re.compile(
    r'câu hỏi dành cho người tham gia|câu hỏi cho người tham gia|'
    r'participation questions|membership questions|questions for participants|questions for (?:people )?joining',
    re.I,
)


@dataclass(frozen=True)
class RulesPrompt:
    digest: str
    checkbox_count: int
    checked_count: int
    response_field_count: int
    screenshot_path: str = ''
    display_text: str = ''
    questions: tuple = ()


def response_fields(dialog):
    return dialog.locator('textarea, select, input:not([type="checkbox"]):not([type="hidden"]):not([type="submit"]), [contenteditable="true"], [role="textbox"], [role="combobox"], [role="radio"]')


def find_rules_prompt(page):
    """Find exactly one visible prompt without interacting with it."""
    dialogs = page.get_by_role('dialog')
    matches = []
    for index in range(dialogs.count()):
        dialog = dialogs.nth(index)
        if not dialog.is_visible():
            continue
        text = dialog.inner_text(timeout=3000)
        if PROMPT_TITLE.search(text):
            matches.append((dialog, text))
    if not matches:
        # Some layouts navigate to a full page rather than opening a dialog.
        headings = page.get_by_role('heading', name=PROMPT_TITLE)
        visible = [headings.nth(i) for i in range(headings.count())
                   if headings.nth(i).is_visible()]
        if not visible:
            return None
        if len(visible) != 1:
            raise RuntimeError('Multiple participation prompts require manual review.')
        main = page.get_by_role('main')
        container = main.first if main.count() == 1 and main.first.is_visible() else page.locator('body')
        matches.append((container, container.inner_text(timeout=3000)))
    if len(matches) != 1:
        raise RuntimeError('Multiple participation prompts require manual review.')
    return matches[0]


def inspect_rules_prompt(page):
    """Read visible prompt text for authorized review, without accepting it."""
    found = find_rules_prompt(page)
    if not found:
        return None
    dialog, text = found
    checkboxes = dialog.get_by_role('checkbox')
    checked = 0
    for index in range(checkboxes.count()):
        item = checkboxes.nth(index)
        if item.is_checked():
            checked += 1
    # Any response field may contain an unanswered question or sensitive data.
    fields = response_fields(dialog)
    questions = []
    for index in range(fields.count()):
        item = fields.nth(index)
        if not item.is_visible():
            continue
        info = item.evaluate('''e => {
          const tag = e.tagName.toLowerCase();
          const type = (e.getAttribute('type') || 'text').toLowerCase();
          const label = e.getAttribute('aria-label') || e.labels?.[0]?.innerText || e.getAttribute('placeholder') || '';
          return {tag, type, label: label.trim(), prefilled: !!e.value};
        }''')
        info['supported'] = bool(info.get('label') and not info.get('prefilled') and
            (info.get('tag') == 'textarea' or (info.get('tag') == 'input' and info.get('type') == 'text')))
        questions.append(info)
    response_count = len(questions)
    normalized = ' '.join(text.split())
    digest = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    # Never publish a truncated or redacted set of terms for approval.
    from modules.publishing.services.post_verification import SECRET_MARKER
    from modules.system_config.crypto import sanitize_text
    if (len(text) > 16000 or len(questions) > 10 or SECRET_MARKER.search(text) or sanitize_text(text) != text or
            any(SECRET_MARKER.search(str(q.get('label', ''))) or
                sanitize_text(str(q.get('label', ''))) != str(q.get('label', '')) or
                len(str(q.get('label', ''))) > 500 for q in questions) or
            re.search(r'https?://\S+\?', text, re.I)):
        raise RuntimeError('Rules cannot be safely displayed; manual review required.')
    snapshot = RulesPrompt(digest, checkboxes.count(), checked, response_count,
                           display_text=text, questions=tuple(questions))
    # Persist only non-sensitive counts; a fully masked screenshot is safe even
    # when Facebook displays a name, private question or prefilled response.
    try:
        directory = Path(tempfile.mkdtemp(prefix='fb-rules-review-'))
        (directory / 'summary.json').write_text(json.dumps({
            'rules_digest': digest,
            'checkbox_count': snapshot.checkbox_count,
            'checked_count': checked,
            'response_field_count': response_count,
        }), encoding='utf-8')
        path = directory / 'masked.png'
        page.screenshot(path=str(path), mask=[page.locator('body')])
        title = dialog.get_by_role('heading', name=re.compile(
            r'^(câu hỏi dành cho người tham gia|membership questions|participation questions)$', re.I
        ))
        if title.count() == 1 and title.first.is_visible():
            path = directory / 'prompt-title.png'
            title.first.screenshot(path=str(path))
        snapshot = RulesPrompt(digest, snapshot.checkbox_count, checked, response_count, str(path), text, tuple(questions))
    except Exception:
        logger.warning('Could not save masked rules diagnostic')
    return snapshot
