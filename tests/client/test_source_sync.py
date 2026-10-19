"""Remote-only stdlib tests for the shared source-sync writer."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[2] / 'tools' / 'trajectory_source_sync.py'
spec = importlib.util.spec_from_file_location('source_sync', MODULE)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SourceSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / 'session.jsonl'
        self.path.write_bytes(b'{"x":1}\n')
        self.spec = {'path': str(self.path), 'legacy_path': 'C:\\logs\\session.jsonl', 'ecosystem': 'codex'}
        self.state = sync.SyncState(self.root / 'state.sqlite')

    def tearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def ack(self, row):
        body = json.loads(row[1])
        self.state.acknowledge(row, {'durable': True, 'mutation_id': body['mutation_id'],
            'accepted_bytes': body['end'] - body['start'], 'next_offset': body['end']})
        return body

    def test_pending_replay_survives_reopen_and_bad_receipt(self):
        self.state.prepare('collector', self.spec)
        first = self.state.next()
        self.state.close()
        self.state = sync.SyncState(self.root / 'state.sqlite')
        self.assertEqual(first, self.state.next())
        with self.assertRaises(ValueError):
            self.state.acknowledge(first, {'durable': True})
        self.assertEqual(first, self.state.next())
        self.ack(first)
        self.assertIsNone(self.state.next())
        self.assertFalse(self.state.prepare('collector', self.spec))

    def test_append_retains_generation_offset_and_identity(self):
        self.state.prepare('collector', self.spec)
        first = self.ack(self.state.next())
        with self.path.open('ab') as stream:
            stream.write(b'{"x":2}\n')
        self.state.prepare('collector', self.spec)
        second = self.ack(self.state.next())
        self.assertEqual(second['generation'], first['generation'])
        self.assertEqual(second['start'], first['end'])
        self.assertEqual(second['source'], sync.source_id('collector', self.spec['legacy_path']))
        self.assertEqual(base64.b64decode(second['content']), b'{"x":2}\n')

    def test_replacement_starts_new_generation(self):
        self.state.prepare('collector', self.spec)
        first = self.ack(self.state.next())
        self.path.write_bytes(b'{"z":3}\n')
        self.state.prepare('collector', self.spec)
        second = self.ack(self.state.next())
        self.assertNotEqual(first['generation'], second['generation'])
        self.assertEqual(second['start'], 0)

    def test_chunk_bound_and_incomplete_json_line_preservation(self):
        content = b'x' * (sync.CHUNK_BYTES + 11)
        self.path.write_bytes(content)
        self.state.prepare('collector', self.spec)
        first = self.ack(self.state.next())
        self.assertEqual(len(base64.b64decode(first['content'])), sync.CHUNK_BYTES)
        self.state.prepare('collector', self.spec)
        second = self.ack(self.state.next())
        self.assertEqual(base64.b64decode(first['content']) + base64.b64decode(second['content']), content)

    def test_process_lock_prevents_second_writer(self):
        with sync.process_lock(self.root / 'state.lock'):
            with self.assertRaises(OSError):
                with sync.process_lock(self.root / 'state.lock'):
                    self.fail('Second writer acquired same lock')

    def test_redirect_is_never_followed(self):
        with self.assertRaises(ValueError):
            sync.NoRedirect().redirect_request(None, None, None, None, None, None)


if __name__ == '__main__':
    unittest.main()
