import tempfile
import unittest
from pathlib import Path
from ucon_trailcam_smtp.event_metadata import FIELDS, event_metadata, select_event, save_metadata, load_metadata, metadata_text


class EventMetadataTests(unittest.TestCase):
    def test_only_requested_fields_and_nulls(self):
        item = {'itemid': 'id', 'et_utc': 123, 'img_url': 'secret'}
        data = event_metadata(item)
        self.assertEqual(tuple(data), FIELDS)
        self.assertIsNone(data['battery'])
        self.assertNotIn('secret', metadata_text(item))

    def test_select_exact_own_event(self):
        own = {'uid': 'own', 'et_utc': 123}
        items = [own, {'uid': 'other', 'et_utc': 123}, {'uid': 'own', 'et_utc': 124}]
        self.assertIs(select_event(items, 'own', 123), own)
        for records, stamp in ((items, 125), (items + [own], 123)):
            with self.assertRaises(ValueError):
                select_event(records, 'own', stamp)

    def test_sidecar_roundtrip_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'event.json'
            item = {'itemid': 'id', 'et_utc': 123, 'user_tag': {'name': 'Reh'}}
            save_metadata(path, item)
            self.assertEqual(load_metadata(path), event_metadata(item))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                save_metadata(path, item)
