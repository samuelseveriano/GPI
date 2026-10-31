"""Ponto de entrada do GPI.exe (PyInstaller)."""
import multiprocessing
import os
import sys
import traceback

if __name__ == "__main__":
    multiprocessing.freeze_support()          # necessário no Windows para bibliotecas que criam processos
    try:
        from gpi.main import main
        code = main()
    except SystemExit:
        raise
    except BaseException:                     # noqa: BLE001
        # Sem isto, o PyInstaller (exe sem console) mostra uma caixa de diálogo e o processo fica parado.
        tb = traceback.format_exc()
        try:
            import logging
            logging.getLogger("gpi").critical("erro fatal na inicialização:\n%s", tb)
        except Exception:                     # noqa: BLE001
            pass
        try:
            from gpi.main import fatal
            fatal("Erro inesperado ao iniciar o GPI. Detalhes em logs/gpi.log.\n\n" + tb[-1500:])
        except Exception:                     # noqa: BLE001
            pass
        code = 1
    sys.exit(code)
