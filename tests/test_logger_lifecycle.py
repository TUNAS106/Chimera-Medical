import io
import os
import tempfile
import unittest
from unittest.mock import patch

import daily_execution_auto
import daily_execution_auto_attack


class LoggerLifecycleTests(unittest.TestCase):
    def _assert_flush_after_close_is_safe(self, logger_class):
        terminal = io.StringIO()
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "daemon.log")
            with patch("sys.stdout", terminal):
                logger = logger_class(path)
            logger.write("completed\n")
            logger.close()

            # Python flushes sys.stdout again during interpreter shutdown. A
            # closed backing file must not turn a successful run into rc=120.
            logger.flush()
            logger.close()

            with open(path, encoding="utf-8") as log_file:
                self.assertEqual(log_file.read(), "completed\n")
            self.assertEqual(terminal.getvalue(), "completed\n")

    def test_normal_logger_survives_final_flush(self):
        self._assert_flush_after_close_is_safe(daily_execution_auto.Logger)

    def test_attack_logger_survives_final_flush(self):
        self._assert_flush_after_close_is_safe(
            daily_execution_auto_attack.Logger
        )


if __name__ == "__main__":
    unittest.main()
