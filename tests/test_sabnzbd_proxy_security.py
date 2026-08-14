import ast
import builtins
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).parents[1]


def _load_update_function():
    """טוען רק את פונקציית העדכון כדי שהבדיקה לא תפעיל את הבוט."""

    source = (ROOT / "bot" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_update_sabnzbd_ini"
    ]
    namespace = {"LOGGER": SimpleNamespace(info=lambda *_: None, warning=lambda *_: None, error=lambda *_: None)}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "bot/__init__.py", "exec"), namespace)
    return namespace["_update_sabnzbd_ini"]


class SabnzbdProxySecurityTests(unittest.TestCase):
    def test_sabnzbd_keeps_api_key_but_removes_the_second_web_login(self):
        update = _load_update_function()
        with tempfile.TemporaryDirectory() as temporary:
            ini = Path(temporary) / "SABnzbd.ini"
            ini.write_text(
                "host = ::\nusername = admin\npassword = old\napi_key = old\n",
                encoding="utf-8",
            )
            real_open = builtins.open

            def redirected_open(path, *args, **kwargs):
                if path == "configs/sabnzbd/SABnzbd.ini":
                    return real_open(ini, *args, **kwargs)
                return real_open(path, *args, **kwargs)

            with patch("builtins.open", side_effect=redirected_open):
                update("derived-api-key")
            content = ini.read_text(encoding="utf-8")

        self.assertIn("host = 127.0.0.1", content)
        self.assertIn("username = \n", content)
        self.assertIn("password = \n", content)
        self.assertIn("api_key = derived-api-key", content)

    def test_sabnzbd_is_not_exposed_outside_the_protected_proxy(self):
        launcher = (ROOT / "setpkgs.sh").read_text(encoding="utf-8")
        web = (ROOT / "web" / "wserver.py").read_text(encoding="utf-8")

        self.assertIn("-s 127.0.0.1:8070", launcher)
        self.assertIn('return await protected_proxy("nzb", path, request)', web)
        self.assertIn('"nzb": {"url": "http://localhost:8070/", "password":', web)


if __name__ == "__main__":
    unittest.main()
