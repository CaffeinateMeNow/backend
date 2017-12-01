import abc

from mediawords.db import DatabaseHandler
from mediawords.key_value_store.test_key_value_store import TestKeyValueStoreTestCase


class TestMockDownloadTestCase(TestKeyValueStoreTestCase, metaclass=abc.ABCMeta):
    """Abstract class for test cases which require a mock download."""

    @staticmethod
    def __create_mock_download(db: DatabaseHandler, downloads_id: int):
        db.query("""
            INSERT INTO media (media_id, url, name, moderated)
            VALUES (1, 'http://', 'Test Media', 't')
        """)
        db.query("""
            INSERT INTO feeds(feeds_id, media_id, name, url)
            VALUES (1, 1, 'Test Feed', 'http://')
        """)
        db.query("""
            INSERT INTO stories (stories_id, media_id, url, guid, title, publish_date, collect_date)
            VALUES (1, 1, 'http://', 'guid', 'Test Story', now(), now());
        """)
        db.query("""
            INSERT INTO downloads (
                downloads_id, feeds_id, stories_id, url, host, download_time, type, state, priority, sequence
            ) VALUES (
                %(downloads_id)s, 1, 1, 'http://', '', NOW(), 'content', 'pending', 0, 0
            )
        """, {'downloads_id': downloads_id})

    def setUp(self):
        super().setUp()
        self.__create_mock_download(db=self.db(), downloads_id=self._TEST_OBJECT_ID)
