import time
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

def limpiar_documentos_y_qr():
    # Configurar la ruta a la base de datos y carpeta de datos
    directory = Path(os.environ.get('DATA_DIR', str(Path(__file__).parent / 'data')))
    db_path = directory / 'asemaco_new.sqlite3'
    
    if not db_path.exists():
        print(f"Esperando a que la base de datos {db_path} sea creada...")
        return

    bbdd = sqlite3.connect(db_path)
    bbdd.row_factory = sqlite3.Row
    cursor = bbdd.cursor()

    try:
        # Obtener todos los documentos
        documentos = cursor.execute('SELECT * FROM documents').fetchall()
        ahora = datetime.now(timezone.utc)

        borrados = 0
        qrs_anulados = 0

        for row in documentos:
            if not row['created']:
                continue
            
            fecha_creacion = datetime.fromisoformat(row['created'])
            # Asegurarse de tener zona horaria para comparar
            if fecha_creacion.tzinfo is None:
                fecha_creacion = fecha_creacion.replace(tzinfo=timezone.utc)
            
            diferencia_tiempo = ahora - fecha_creacion

            # 1. Borrar documento y PDF después de 15 meses (450 días)
            if diferencia_tiempo > timedelta(days=450):
                print(f"Borrando documento {row['id']} por tener más de 450 días.")
                pdf_path = directory / 'pdfs' / f'{row["token"]}.pdf'
                if pdf_path.is_file():
                    try:
                        pdf_path.unlink(missing_ok=True)
                    except Exception as e:
                        print(f"Error al borrar PDF físico: {e}")
                
                cursor.execute('DELETE FROM documents WHERE id=?', (row['id'],))
                borrados += 1
            
            # 2. Borrar (invalidar) el QR después de 7 días
            elif diferencia_tiempo > timedelta(days=7):
                # Si el token existe y es un QR activo (no empieza por caducado_)
                if row['token'] and not row['token'].startswith('caducado_'):
                    print(f"Caducando QR del documento {row['id']} por tener más de 7 días.")
                    # Modificamos el token en base de datos para que el enlace QR original deje de funcionar
                    cursor.execute("UPDATE documents SET token = 'caducado_' || token WHERE id=?", (row['id'],))
                    qrs_anulados += 1

        bbdd.commit()
        
        if borrados > 0 or qrs_anulados > 0:
            print(f"Limpieza completada: {borrados} documentos borrados, {qrs_anulados} QRs caducados.")
            
    except Exception as e:
        print(f"Error durante la limpieza: {e}")
        bbdd.rollback()
    finally:
        bbdd.close()

if __name__ == '__main__':
    print("Iniciando worker personalizado de AsemaCo (Limpieza cada hora)...")
    while True:
        limpiar_documentos_y_qr()
        time.sleep(3600)  # Dormir 1 hora (3600 segundos)
