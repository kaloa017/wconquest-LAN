"""Pi operations checks use disposable data and never import the game."""
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from contextlib import closing

from tools.pi_backup import create_backup
from tools.pi_healthcheck import check
from tools.package_pi import package


class PiDeploymentTests(unittest.TestCase):
    def test_backup_includes_committed_wal_state_and_private_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);state=root/'state';state.mkdir();database=state/'game.db'
            with closing(sqlite3.connect(database)) as conn:
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('CREATE TABLE moves(id INTEGER PRIMARY KEY, value TEXT)')
                conn.execute('INSERT INTO moves(value) VALUES(?)',('committed move',));conn.commit()
                (state/'.session-secret').write_text('disposable-test-secret')
                (state/'ideas.txt').write_text('test idea')
                (state/'media').mkdir();(state/'media'/'world.mp3').write_bytes(b'test sound')
                eva=root/'eva';eva.mkdir();(eva/'unit.jpg').write_bytes(b'test image')
                backup=create_backup(database,root/'backups',eva_directory=eva)
                with closing(sqlite3.connect(backup/'game.db')) as restored:
                    self.assertEqual(restored.execute('SELECT value FROM moves').fetchone()[0],'committed move')
                    self.assertEqual(restored.execute('PRAGMA quick_check').fetchone()[0],'ok')
                self.assertEqual((backup/'.session-secret').read_text(),'disposable-test-secret')
                self.assertEqual((backup/'media'/'world.mp3').read_bytes(),b'test sound')
                self.assertEqual((backup/'eva'/'unit.jpg').read_bytes(),b'test image')
                self.assertEqual((backup/'ideas.txt').read_text(),'test idea')
                self.assertFalse(list((root/'backups').glob('.pending-*')))
                conn.execute('INSERT INTO moves(value) VALUES("still usable")');conn.commit()

    def test_retention_only_removes_our_completed_backups(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);database=root/'game.db'
            with closing(sqlite3.connect(database)) as conn:conn.execute('CREATE TABLE saves(id INTEGER)')
            directory=root/'backups';directory.mkdir()
            unrelated=directory/'my-own-backup';unrelated.mkdir();(unrelated/'keep').write_text('keep')
            incomplete=directory/'wconquest-20000101T000000-000000000Z';incomplete.mkdir()
            first=create_backup(database,directory,keep=2)
            second=create_backup(database,directory,keep=2)
            third=create_backup(database,directory,keep=2)
            self.assertFalse(first.exists());self.assertTrue(second.exists());self.assertTrue(third.exists())
            self.assertTrue((unrelated/'keep').exists());self.assertTrue(incomplete.exists())

    def test_missing_source_and_invalid_retention_do_not_create_worlds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with self.assertRaises(FileNotFoundError):create_backup(root/'absent.db',root/'backups')
            self.assertFalse((root/'absent.db').exists())
            with self.assertRaises(ValueError):create_backup(root/'absent.db',root/'backups',keep=0)

    def test_healthcheck_uses_allowed_host_and_checks_tunnel_readiness(self):
        class Response(io.BytesIO):
            status=200
        with patch('tools.pi_healthcheck.urlopen',side_effect=[Response(json.dumps({'version':'test','csrf':'test'}).encode()),Response(b'ready')]) as opener:
            self.assertEqual(check('game.example.com',tunnel=True),'test')
            request=opener.call_args_list[0].args[0]
            self.assertEqual(request.full_url,'http://127.0.0.1:5055/api/bootstrap')
            self.assertEqual(request.get_header('Host'),'game.example.com')
            self.assertEqual(opener.call_args_list[1].args[0],'http://127.0.0.1:20241/ready')
        with patch('tools.pi_healthcheck.urlopen',return_value=Response(b'{}')):
            with self.assertRaises(RuntimeError):check('localhost')

    def test_package_rejects_private_files_and_preserves_linux_read_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'app.py').write_text('# disposable code\n')
            (root/'game.db').write_bytes(b'private save')
            with patch('tools.package_pi.ROOT',root),patch('tools.package_pi.public_files',return_value=['app.py','game.db']):
                with self.assertRaises(ValueError):package(root/'private.zip')
            self.assertFalse((root/'private.zip').exists())
            with patch('tools.package_pi.ROOT',root),patch('tools.package_pi.public_files',return_value=['app.py']):
                output=package(root/'public.zip')
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist(),['app.py'])
                self.assertEqual(archive.getinfo('app.py').external_attr >> 16,0o100644)


if __name__=='__main__':unittest.main()
