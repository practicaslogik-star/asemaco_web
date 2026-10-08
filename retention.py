"""Conservación durante 15 meses naturales desde la finalización registrada."""
import calendar
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def expiry_after(created, months=15):
    from zoneinfo import ZoneInfo
    date = datetime.fromisoformat(created)
    madrid = ZoneInfo('Europe/Madrid')
    date = date.replace(tzinfo=madrid) if date.tzinfo is None else date.astimezone(madrid)
    month = date.year * 12 + date.month - 1 + months
    year, zero_month = divmod(month, 12)
    date = date.replace(year=year, month=zero_month + 1,
                        day=min(date.day, calendar.monthrange(year, zero_month + 1)[1]))
    return date.astimezone(timezone.utc).isoformat(timespec='seconds')


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def remove_documents(database, data_dir, *, doc_id=None, user_id=None, expired_before=None):
    """Borrado de registro y PDF; restaura el archivo si falla la transacción."""
    folder = Path(data_dir) / 'pdfs'
    staged = []
    with sqlite3.connect(database, timeout=30) as con:
        con.execute('BEGIN IMMEDIATE')
        # Recuperar una operación interrumpida entre el movimiento y el commit.
        for pending in folder.glob('*.pdf.deleting'):
            token = pending.name.removesuffix('.pdf.deleting')
            exists = con.execute('SELECT 1 FROM documents WHERE token=?', (token,)).fetchone()
            original = folder / (token + '.pdf')
            if exists and not original.exists(): pending.rename(original)
            else: pending.unlink(missing_ok=True)
        if expired_before is not None:
            rows = con.execute('SELECT id,token,user_id FROM documents WHERE root_id IN (SELECT root_id FROM documents GROUP BY root_id HAVING count(*)=count(finished_at) AND count(*)=count(expires_at) AND max(expires_at)<=? LIMIT 100)', (expired_before,)).fetchall()
        elif doc_id is not None and user_id is not None:
            target=con.execute('SELECT root_id FROM documents WHERE id=? AND user_id=?',(doc_id,user_id)).fetchone()
            rows=[]
            if target:
                blocked=con.execute('SELECT 1 FROM documents WHERE root_id=? AND (finished_at IS NULL OR delete_after IS NULL OR delete_after>?)',(target[0],utc_now())).fetchone()
                if not blocked: rows=con.execute('SELECT id,token,user_id FROM documents WHERE root_id=? AND user_id=?',(target[0],user_id)).fetchall()
        else: raise ValueError('Se necesita propietario o fecha de caducidad.')
        try:
            for ident, token, owner in rows:
                original = folder / (token + '.pdf')
                pending = folder / (token + '.pdf.deleting')
                if original.exists():
                    original.rename(pending); staged.append((original,pending))
                con.execute('INSERT INTO deca_events(document_id,user_id,event,at,detail) VALUES(?,?,?,?,?)',(ident,owner,'eliminacion_automatica' if expired_before else 'eliminacion_manual',utc_now(),''))
                con.execute('UPDATE deca_events SET detail=? WHERE document_id=?',('',ident))
                con.execute('DELETE FROM documents WHERE id=?', (ident,))
            con.commit()
        except Exception:
            con.rollback()
            for original,pending in staged:
                if pending.exists(): pending.rename(original)
            raise
        for original,pending in staged:
            try: pending.unlink(missing_ok=True)
            except OSError: logging.exception('No se pudo retirar un PDF pendiente de borrado; se reintentará.')
    return len(rows)


def purge_expired(database, data_dir, now=None):
    cutoff = now or utc_now()
    total = 0
    while True:
        count = remove_documents(database,data_dir,expired_before=cutoff)
        total += count
        if count == 0: return total
