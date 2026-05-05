import unittest
from unittest.mock import patch

from app.main import app, lifespan


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_failure_is_critical_and_raised(self) -> None:
        startup_error = RuntimeError("database unavailable")

        with (
            patch("app.main.bootstrap_global_database", side_effect=startup_error),
            patch("app.main.logger") as logger,
        ):
            with self.assertRaises(RuntimeError):
                async with lifespan(app):
                    pass

        logger.critical.assert_called_once()


if __name__ == "__main__":
    unittest.main()
