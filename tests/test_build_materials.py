import csv
import gzip
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import build_materials as build


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raw = Path(self.temp.name)
        self.patch = patch.object(build, 'RAW', self.raw)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def download(self, payload):
        # Mock both the old and current transport so regressions never use the network.
        def retrieve(_url, path):
            Path(path).write_bytes(payload)
        with patch.object(build.urllib.request, 'urlretrieve', side_effect=retrieve), \
                patch.object(build.urllib.request, 'urlopen', return_value=io.BytesIO(payload)) as request:
            result = build.download_cedict()
        return result, request

    def test_success_is_cached_and_network_has_timeout(self):
        result, request = self.download(gzip.compress(b'# dictionary\n'))
        self.assertEqual(result.read_bytes(), b'# dictionary\n')
        request.assert_called_once_with(build.CC_CEDICT_URL, timeout=30)
        with patch.object(build.urllib.request, 'urlopen') as request:
            self.assertEqual(build.download_cedict(), result)
            request.assert_not_called()

    def test_truncated_gzip_does_not_poison_cache_and_can_retry(self):
        result, _ = self.download(gzip.compress(b'# dictionary\n')[:-5])
        self.assertIsNone(result)
        self.assertEqual(list(self.raw.iterdir()), [])
        result, _ = self.download(gzip.compress(b'# complete\n'))
        self.assertEqual(result.read_bytes(), b'# complete\n')

    def test_compressed_size_limit(self):
        with patch.object(build, 'CEDICT_MAX_DOWNLOAD_BYTES', 4, create=True):
            result, _ = self.download(gzip.compress(b'# dictionary\n'))
        self.assertIsNone(result)
        self.assertEqual(list(self.raw.iterdir()), [])

    def test_decompressed_size_limit(self):
        with patch.object(build, 'CEDICT_MAX_TEXT_BYTES', 8, create=True):
            result, _ = self.download(gzip.compress(b'x' * 1000))
        self.assertIsNone(result)
        self.assertEqual(list(self.raw.iterdir()), [])

    def test_timeout_leaves_no_cache(self):
        with patch.object(build.urllib.request, 'urlretrieve', side_effect=TimeoutError), \
                patch.object(build.urllib.request, 'urlopen', side_effect=TimeoutError):
            self.assertIsNone(build.download_cedict())
        self.assertEqual(list(self.raw.iterdir()), [])


class AnkiTests(unittest.TestCase):
    def test_dictionary_fields_are_text_inside_card_html(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master = pd.DataFrame([{
                'character': '我', 'pinyin': '<img src=x onerror=alert(1)>',
                'definition_en': '<script>alert(2)</script> & "meaning"',
                'example_words': '<img src=x onerror=alert(3)>',
                'learning_band': 'Zero Beginner', 'in_3500': True,
                'frequency_rank': 1, 'rank_3500': 1, 'pinyin_plain': 'wo',
                'lookup_category': 'People',
            }])
            with patch.object(build, 'PROCESSED', root), patch.object(build, 'CONTENT', root):
                build.export_data(master, [])
            with (root / 'anki_top_600.csv').open(encoding='utf-8-sig') as handle:
                card = next(csv.DictReader(handle))
            self.assertEqual(card['front'], '我')
            self.assertEqual(card['back'],
                '&lt;img src=x onerror=alert(1)&gt;<br>'
                '&lt;script&gt;alert(2)&lt;/script&gt; &amp; &quot;meaning&quot;<br>'
                '<small>&lt;img src=x onerror=alert(3)&gt;</small>')
            self.assertEqual(card['tags'], 'zero_beginner')


if __name__ == '__main__':
    unittest.main()
