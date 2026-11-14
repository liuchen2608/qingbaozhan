"""Portable checks of installer decisions; not a real macOS execution."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts/install-mac.command'

def definitions(home, platform):
    body = SCRIPT.read_text().split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    body = body.rsplit('\ntry:\n    main()', 1)[0]
    namespace = {}
    with patch('pathlib.Path.home', return_value=home), patch('sys.platform', platform):
        exec(compile(body, str(SCRIPT), 'exec'), namespace)
    return namespace

class DesktopInstallerTests(unittest.TestCase):
    def test_existing_folder_is_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp); target = home / 'Desktop/情报站'; target.mkdir(parents=True)
            secret = target / '.env'; secret.write_text('existing-personal-config')
            ns = definitions(home, 'darwin')
            with patch('sys.platform', 'darwin'), patch('urllib.request.urlopen') as network:
                with self.assertRaisesRegex(RuntimeError, '目标目录已存在'):
                    ns['main']()
                network.assert_not_called()
            self.assertEqual(secret.read_text(), 'existing-personal-config')
            self.assertEqual(list(target.iterdir()), [secret])

    def test_cloud_cannot_claim_mac_installation(self):
        ns = definitions(Path('/tmp'), 'linux')
        with patch('sys.platform', 'linux'):
            with self.assertRaisesRegex(RuntimeError, '仅用于你的 Mac'):
                ns['main']()

    def test_install_and_open_only_after_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp); (home / 'Desktop').mkdir()
            ns = definitions(home, 'darwin')
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w') as book:
                for name in ['run.py', 'setup.sh', 'requirements.txt', 'hub/app.py', '启动情报站.command']:
                    book.writestr('qingbaozhan-' + ns['REVISION'] + '/' + name, '# placeholder')
            process = MagicMock()
            process.poll.side_effect = [None, 0]
            sock = MagicMock(); sock.__enter__.return_value.connect_ex.return_value = 1
            with patch('sys.platform', 'darwin'), patch('urllib.request.urlopen', side_effect=[io.BytesIO(archive.getvalue()), io.BytesIO(json.dumps({'model_configured':False,'categories':[]}).encode())]), patch('subprocess.run') as install, patch('subprocess.Popen',return_value=process), patch('socket.socket',return_value=sock), patch('webbrowser.open',return_value=True) as browser:
                ns['main']()
                install.assert_called_once()
                browser.assert_called_once_with('http://127.0.0.1:8765')
                process.wait.assert_called_once()
            self.assertTrue((home/'Desktop/情报站/hub/app.py').is_file())

if __name__ == '__main__':
    unittest.main()
