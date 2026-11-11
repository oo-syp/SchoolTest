# -*- coding: utf-8 -*-
"""Запуск SchoolTest из исходников и точка входа для PyInstaller.

SchoolTest.exe --pyrun solution.py — запуск решения ученика встроенным Python
(если Python не установлен на компьютере). Обрабатывается до загрузки программы,
чтобы запуск был быстрым."""
import sys

if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "--pyrun":
    import os
    import runpy
    path = sys.argv[2]
    sys.argv = [path]
    sys.path[0:0] = [os.path.dirname(os.path.abspath(path))]
    for s in (sys.stdin, sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    code = 0
    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(code)

from schooltest.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
