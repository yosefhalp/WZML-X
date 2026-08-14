import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class DockerBuildContextTests(unittest.TestCase):
    def test_runtime_data_and_secrets_are_not_baked_into_the_image(self):
        ignored = {
            line.strip()
            for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertTrue(
            {
                ".git",
                "accounts",
                "downloads",
                "runtime",
                "config.py",
                ".env.*",
                "*.zip",
                "*.tar",
                "*.tar.gz",
            }.issubset(ignored)
        )


if __name__ == "__main__":
    unittest.main()
