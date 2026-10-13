import time
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import smtplib
from email.message import EmailMessage
import ssl
from dotenv import load_dotenv

load_dotenv()

def enviar_correo_aviso_borrado(destinatario_usuario, numero_documento):
    remitente = (os.getenv("MAIL_USERNAME") or "").strip()
    password = (os.getenv("MAIL_PASSWORD") or "").strip().replace(" ", "")

    if not remitente or not password:
        print("Error: Credenciales de correo MAIL_USERNAME o MAIL_PASSWORD no configuradas para el aviso.")
        return

    msg = EmailMessage()
    msg["Subject"] = f"Aviso importante: Su documento #{numero_documento:06d} va a ser eliminado pronto"
    msg["From"] = remitente
    msg["To"] = destinatario_usuario  # <--- Envío al correo del usuario
    
    msg.set_content(
        f"Estimado socio,\n\n"
        f"Le informamos que el documento de control número #{numero_documento:06d} "
        f"alcanzará su período de conservación legal de 15 meses en aproximadamente 15 días.\n\n"
        f"Una vez transcurrido ese plazo, el documento y su PDF asociado serán eliminados "
        f"permanentemente de nuestros sistemas según la política de retención.\n\n"
        f"Si necesita conservar una copia, por favor descárguela desde su área de socios antes de esa fecha.\n\n"
        f"Atentamente,\n"
        f"Administración ASEMACO"
    )

    try:
        contexto_ssl = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20, context=contexto_ssl) as smtp:
            smtp.login(remitente, password)
            smtp.send_message(msg)
            print(f"Correo de aviso de borrado enviado con éxito a: {destinatario_usuario}")
    except Exception as e:
        print(f"Error al enviar el correo de aviso a {destinatario_usuario}: {e}")

def limpiar_documentos_y_qr(data_dir=None):
    if data_dir is not None:
        directory = Path(data_dir)
    else:
        directory = Path(os.environ.get('DATA_DIR', str(Path(__file__).parent / 'data')))
    db_path = directory / 'asemaco_new.sqlite3'
    
    if not db_path.exists():
        return

    bbdd = sqlite3.connect(db_path)
    bbdd.row_factory = sqlite3.Row
    cursor = bbdd.cursor()

    try:
        # Hacemos JOIN con la tabla users para obtener el correo del propietario del documento
        query = '''
            SELECT d.*, u.email as user_email 
            FROM documents d 
            JOIN users u ON d.user_id = u.id
        '''
        documentos = cursor.execute(query).fetchall()
        ahora = datetime.now(timezone.utc)

        borrados = 0
        qrs_anulados = 0
        avisos_enviados = 0

        for row in documentos:
            if not row['created']:
                continue
            
            fecha_creacion = datetime.fromisoformat(row['created'])
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
            
            # 2. Enviar correo de aviso 15 días antes del borrado (entre 435 y 436 días)
            # Usamos un control de eventos o una marca para no enviar el correo repetidas veces cada hora.
            elif timedelta(days=435) <= diferencia_tiempo <= timedelta(days=436):
                # Comprobamos si ya se envió este aviso para evitar duplicados
                aviso_previo = cursor.execute(
                    "SELECT id FROM deca_events WHERE document_id=? AND event=?", 
                    (row['id'], 'aviso_borrado_enviado')
                ).fetchone()

                if not aviso_previo:
                    print(f"El documento {row['id']} cumple 15 meses en 15 días. Enviando aviso a {row['user_email']}...")
                    enviar_correo_aviso_borrado(row['user_email'], row['number'])
                    
                    # Registramos el evento para no volver a enviarlo
                    cursor.execute(
                        "INSERT INTO deca_events(document_id, user_id, event, at, detail) VALUES(?,?,?,?,?)",
                        (row['id'], row['user_id'], 'aviso_borrado_enviado', ahora.isoformat(timespec='seconds'), f"Aviso enviado a {row['user_email']}")
                    )
                    avisos_enviados += 1

            # 3. Desactivar el QR después de 7 días
            elif diferencia_tiempo > timedelta(days=7):
                if not row['revoked']:
                    cursor.execute("UPDATE documents SET revoked = 1 WHERE id=?", (row['id'],))
                    cursor.execute("INSERT INTO deca_events(document_id,user_id,event,at,detail) VALUES(?,?,?,?,?)",
                                   (row['id'], row['user_id'], 'desactivacion_qr_automatica', ahora.isoformat(timespec='seconds'), 'Caducidad automatica tras 7 dias'))
                    qrs_anulados += 1

        bbdd.commit()
        
        if borrados > 0 or qrs_anulados > 0 or avisos_enviados > 0:
            print(f"Limpieza y avisos completados: {borrados} borrados, {qrs_anulados} QRs caducados, {avisos_enviados} avisos enviados.")
            
    except Exception as e:
        print(f"Error durante la limpieza y avisos: {e}")
        bbdd.rollback()
    finally:
        bbdd.close()

if __name__ == '__main__':
    print("Iniciando worker personalizado de AsemaCo...")
    while True:
        limpiar_documentos_y_qr()
        time.sleep(3600)