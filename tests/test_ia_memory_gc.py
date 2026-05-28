"""Tests ia_memory_gc."""

from __future__ import annotations

import os
import unittest


class TestMemoryGc(unittest.TestCase):
    def test_gc_runs_without_error(self) -> None:
        from ia_memory_gc import liberar_memoria_ciclo

        os.environ["IA_MEM_GC_ENABLE"] = "1"
        os.environ["IA_MEM_GC_VERBOSE"] = "0"
        loc = {"df_m15": object(), "df_h4": object()}
        liberar_memoria_ciclo(local_vars=loc)
        self.assertNotIn("df_m15", loc)


if __name__ == "__main__":
    unittest.main()
