import unittest
from unittest.mock import patch

from app.main import app, lifespan


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_failure_is_critical_and_raised(self) -> None:
        startup_error = RuntimeError("database unavailable")

        with (
            patch("app.main.bootstrap_global_database", side_effect=startup_error),
            patch("app.main.cleanup_abandoned_attempt_workspaces") as cleanup,
            patch("app.main.logger") as logger,
        ):
            with self.assertRaises(RuntimeError):
                async with lifespan(app):
                    pass

        logger.critical.assert_called_once()
        cleanup.assert_not_called()

    async def test_startup_cleans_abandoned_ingestion_workspaces(self) -> None:
        with (
            patch("app.main.bootstrap_global_database"),
            patch("app.main.cleanup_abandoned_attempt_workspaces") as cleanup,
            patch("app.main.close_global_connection"),
        ):
            async with lifespan(app):
                pass

        cleanup.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
