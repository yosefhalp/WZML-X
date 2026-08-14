import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
README = ROOT / "README.md"


class RepositoryBrandingTests(unittest.TestCase):
    def test_readme_is_hebrew_and_points_to_yosef_repository(self):
        readme = README.read_text(encoding="utf-8")
        self.assertIn('<div dir="rtl"', readme)
        self.assertIn("WZML-X HE — המהדורה של יוסף", readme)
        self.assertIn("https://github.com/yosefhalp/WZML-X", readme)
        self.assertIn("git clone https://github.com/yosefhalp/WZML-X.git", readme)
        self.assertIn("https://github.com/SilentDemonSD/WZML-X", readme)

    def test_readme_documents_the_custom_workflows(self):
        readme = README.read_text(encoding="utf-8")
        for required in (
            "Userbot Premium",
            "4,194,304,000",
            "GoFile",
            "כמה קישורים",
            "מרכז השליטה",
            "גיבוי מצב",
            "גיבוי מלא",
            "Telegram Bot API",
            "HTTP `503`",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)

    def test_public_links_and_attribution_use_yosef_branding(self):
        sources = {
            "services": ROOT / "bot" / "modules" / "services.py",
            "session": ROOT / "bot" / "modules" / "gen_pyro_sess.py",
            "selector": ROOT / "web" / "templates" / "page.html",
            "dashboard": ROOT / "web" / "templates" / "landing.html",
        }
        for name, path in sources.items():
            with self.subTest(source=name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(
                    "yosefhalp" in text or "WZML-X HE" in text,
                    f"המיתוג של יוסף חסר בקובץ {path}",
                )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in sources.values())
        self.assertNotIn("https://www.github.com/SilentDemonSD/WZML-X", combined)
        self.assertNotIn("https://t.me/WZML_X", combined)

    def test_secret_files_remain_excluded_from_git(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for secret in (
            "config.py",
            ".env.server",
            "accounts/*",
            "*.zip",
            "*.tar",
        ):
            with self.subTest(secret=secret):
                self.assertIn(secret, ignore)

    def test_public_project_has_no_workspace_or_provider_context(self):
        forbidden = ("co" + "dex", "aka" + "mai", "אק" + "מי")
        roots = (
            ROOT / "README.md",
            ROOT / ".gitignore",
            ROOT / "config_sample.py",
            ROOT / "docker-compose.server.yml",
            ROOT / "bot",
            ROOT / "web",
            ROOT / "deploy",
            ROOT / "tests",
        )
        text_suffixes = {".md", ".py", ".sh", ".yml", ".yaml", ".json", ".js", ".html"}

        for root in roots:
            paths = (root,) if root.is_file() else root.rglob("*")
            for path in paths:
                if not path.is_file() or path.suffix.lower() not in text_suffixes:
                    continue
                normalized_name = path.as_posix().lower()
                text = path.read_text(encoding="utf-8").lower()
                for term in forbidden:
                    with self.subTest(path=path, term=term):
                        self.assertNotIn(term.lower(), normalized_name)
                        self.assertNotIn(term.lower(), text)

    def test_standalone_repository_has_no_external_push_workflow(self):
        workflow = ROOT / ".github" / "workflows" / "sync-wz-deploy.yml"
        self.assertFalse(workflow.exists())


if __name__ == "__main__":
    unittest.main()
