"""בדיקות חוזה שמוודאות ששירות לא בריא מקבל טיפול אוטומטי."""

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class AutohealContractTests(unittest.TestCase):
    def test_production_compose_enables_autoheal_for_wzmlx(self):
        compose = (ROOT / "docker-compose.server.yml").read_text(encoding="utf-8")
        self.assertIn('autoheal: "true"', compose)
        self.assertIn("/health", compose)


if __name__ == "__main__":
    unittest.main()
