"""Ponto de entrada do GPI.exe (PyInstaller)."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()          # necessário no Windows para bibliotecas que criam processos
    from gpi.main import main
    sys.exit(main())
