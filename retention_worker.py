"""Proceso de limpieza sin tráfico web; también admite --once para tareas programadas."""
import argparse
import logging
import os
import time
from pathlib import Path
from retention import purge_expired

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    options = parser.parse_args()
    directory = Path(os.environ.get('DATA_DIR',str(Path(__file__).parent/'data')))
    logging.basicConfig(level=logging.INFO)
    while True:
        database = directory/'asemaco.sqlite3'
        try:
            if database.exists():
                count=purge_expired(database,directory)
                logging.info('Limpieza completada: %s documentos eliminados.',count)
        except Exception:
            logging.exception('La limpieza falló; se reintentará en el siguiente ciclo.')
            if options.once: raise
        if options.once: break
        time.sleep(3600)
