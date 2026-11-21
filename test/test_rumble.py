#!/usr/bin/env python3

# Allow direct execution
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import io
import json
from unittest.mock import patch

from test.helper import FakeYDL
from yt_dlp.extractor.rumble import RumbleChannelIE
from yt_dlp.networking import Response
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import ExtractorError


class TestRumbleChannel(unittest.TestCase):
    def setUp(self):
        self.ie = RumbleChannelIE(FakeYDL())
        self.url = 'https://rumble.com/user/example/videos'

    @staticmethod
    def page(items, next_link=''):
        return f'''
            <head>{next_link}</head>
            <script type="application/json">{{"items": [{{"url": "https://example.com/unrelated"}}]}}</script>
            <rum-videos-grid>
                <script type="application/json">{json.dumps({'items': items})}</script>
            </rum-videos-grid>
        '''

    def test_entries_and_pagination(self):
        pages = [
            self.page([
                {'url': 'https://rumble.com/v123-first.html', 'title': 'First & second'},
                {'url': None},
                {'title': 'Missing URL'},
                {'url': 'not a URL'},
            ], '<link href="?page=2&amp;sort=date" rel="next">'),
            self.page([
                {'url': 'https://rumble.com/v456-second.html', 'title': 'Another video'},
            ], f'<link rel=next href="{self.url}?page=3">'),
            self.page([{'url': 'https://rumble.com/v789-third.html'}]),
        ]
        with patch.object(self.ie, '_download_webpage', side_effect=pages) as download:
            entries = list(self.ie.entries(self.url, 'example'))

        self.assertEqual(entries, [
            {'_type': 'url', 'ie_key': 'Rumble', 'url': 'https://rumble.com/v123-first.html', 'title': 'First & second'},
            {'_type': 'url', 'ie_key': 'Rumble', 'url': 'https://rumble.com/v456-second.html', 'title': 'Another video'},
            {'_type': 'url', 'ie_key': 'Rumble', 'url': 'https://rumble.com/v789-third.html'},
        ])
        self.assertEqual([call.args[0] for call in download.call_args_list], [
            self.url, f'{self.url}?page=2&sort=date', f'{self.url}?page=3',
        ])

    def test_channel_urls_use_video_listing(self):
        for prefix in ('user', 'c'):
            for suffix in ('', '/', '/videos', '/videos/'):
                with self.subTest(prefix=prefix, suffix=suffix):
                    with patch.object(self.ie, '_download_webpage', return_value=self.page([])) as download:
                        result = self.ie._real_extract(f'https://rumble.com/{prefix}/example{suffix}')
                        self.assertEqual(result['id'], 'example')
                        self.assertEqual(list(result['entries']), [])
                    self.assertEqual(download.call_args.args[0], f'https://rumble.com/{prefix}/example/videos')

    def test_empty_listing(self):
        with patch.object(self.ie, '_download_webpage', return_value=self.page([])) as download:
            self.assertEqual(list(self.ie.entries(self.url, 'example')), [])
            download.assert_called_once()

    def test_unrecognized_or_invalid_listing(self):
        for webpage in (
            '<html><title>Please wait</title></html>',
            '<script type="application/json">{"items": []}</script>',
            '<rum-videos-grid><script type="application/json">{"items": INVALID}</script></rum-videos-grid>',
        ):
            with self.subTest(webpage=webpage):
                with patch.object(self.ie, '_download_webpage', return_value=webpage):
                    with self.assertRaises(ExtractorError):
                        list(self.ie.entries(self.url, 'example'))

    def test_lazy_pagination(self):
        page = self.page([
            {'url': 'https://rumble.com/v123-first.html'},
            {'url': 'https://rumble.com/v456-second.html'},
        ], '<link rel="next" href="?page=2">')
        with patch.object(self.ie, '_download_webpage', return_value=page) as download:
            entries = self.ie.entries(self.url, 'example')
            download.assert_not_called()
            self.assertEqual(next(entries)['url'], 'https://rumble.com/v123-first.html')
            self.assertEqual(next(entries)['url'], 'https://rumble.com/v456-second.html')
            download.assert_called_once()

    def test_pagination_loop(self):
        pages = [
            self.page([{'url': 'https://rumble.com/v123-first.html'}], '<link rel="next" href="?page=2">'),
            self.page([{'url': 'https://rumble.com/v456-second.html'}], f'<link rel="next" href="{self.url}">'),
        ]
        with patch.object(self.ie, '_download_webpage', side_effect=pages) as download:
            self.assertEqual(len(list(self.ie.entries(self.url, 'example'))), 2)
            self.assertEqual(download.call_count, 2)

    def test_http_errors(self):
        for status in (404, 403):
            with self.subTest(status=status):
                error = ExtractorError('Unable to download webpage', cause=HTTPError(
                    Response(io.BytesIO(), self.url, {}, status=status)))
                page = self.page([{'url': 'https://rumble.com/v123-first.html'}], '<link rel="next" href="?page=2">')
                with patch.object(self.ie, '_download_webpage', side_effect=[page, error]):
                    entries = self.ie.entries(self.url, 'example')
                    self.assertEqual(next(entries)['url'], 'https://rumble.com/v123-first.html')
                    if status == 404:
                        self.assertEqual(list(entries), [])
                    else:
                        with self.assertRaises(ExtractorError) as raised:
                            next(entries)
                        self.assertIs(raised.exception, error)


if __name__ == '__main__':
    unittest.main()
