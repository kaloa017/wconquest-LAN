import unittest
from release_notes import unseen_notes


class ReleaseNotesTests(unittest.TestCase):
    notes = '# 6.5.0 — future\nFuture\n\n## 6.4.1 — fixes\nFixes\n\n# 6.4.0 — economy\nEconomy\n\n# 6.3.6 — world\nOld\n'

    def test_only_unseen_published_releases(self):
        versions, text = unseen_notes(self.notes, '6.3.6', '6.4.1')
        self.assertEqual(versions, ['6.4.1', '6.4.0'])
        self.assertIn('Economy', text);self.assertNotIn('Old', text);self.assertNotIn('Future', text)

    def test_first_visit_only_current_release(self):
        self.assertEqual(unseen_notes(self.notes, '', '6.4.1')[0], ['6.4.1'])
        self.assertNotIn('Economy', unseen_notes(self.notes, '', '6.4.1')[1])

    def test_seen_future_and_numeric_order(self):
        self.assertEqual(unseen_notes(self.notes, '6.4.1', '6.4.1'), ([], ''))
        self.assertEqual(unseen_notes(self.notes, '6.5.0', '6.4.1'), ([], ''))
        self.assertEqual(unseen_notes('# 6.10.0\nNew\n# 6.9.0\nOld', '6.9.0', '6.10.0')[0], ['6.10.0'])

    def test_missing_notes_and_unknown_legacy_version(self):
        self.assertEqual(unseen_notes('', '6.3.6', '6.4.1')[0], ['6.4.1'])
        self.assertEqual(unseen_notes(self.notes, 'legacy', '6.4.1')[0], ['6.4.1'])
