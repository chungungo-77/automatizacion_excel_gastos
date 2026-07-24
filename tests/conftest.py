import sys
from pathlib import Path

# Permite que pytest encuentre limpiar_gastos.py aunque se corra desde
# cualquier carpeta (ej. `pytest` desde la raíz del repo).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
