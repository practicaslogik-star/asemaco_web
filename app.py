import os, json, sqlite3, secrets, hashlib, time, io, re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from urllib.parse import urlparse
import click
from PIL import Image as PillowImage, ImageOps, UnidentifiedImageError
from flask import Flask, g, request, session, redirect, url_for, render_template, flash, abort, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from pdf_document import make_pdf
from qr_image import make_qr_png
from zipfile import ZipFile, ZIP_DEFLATED
from retention import expiry_after, utc_now, purge_expired, remove_documents
from datetime import datetime
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent

PROFILE_FIELDS = [('name','Razón social'),('nif','NIF / CIF'),('address','Dirección'),('city','Código postal y población'),('country','País'),('phone','Teléfono'),('email','Correo electrónico')]

CAT_FIELDS = {
 'cargadores': PROFILE_FIELDS,
 'origenes': PROFILE_FIELDS,
 'destinos': PROFILE_FIELDS,
 'transportistas': PROFILE_FIELDS,
 'conductores': [('name','Nombre y apellidos'),('nif','DNI / identificación'),('phone','Teléfono')],
 'vehiculos': [('name','Matrícula del vehículo'),('trailer','Matrícula del remolque')]
}
CAT_NAMES = {'cargadores':'Cargadores','origenes':'Orígenes','destinos':'Destinos','transportistas':'Transportistas','conductores':'Conductores','vehiculos':'Vehículos'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member', active INTEGER NOT NULL DEFAULT 1, must_change INTEGER NOT NULL DEFAULT 1, auth_version INTEGER NOT NULL DEFAULT 1, profile TEXT NOT NULL DEFAULT '{}', next_number INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), number INTEGER NOT NULL, token TEXT NOT NULL UNIQUE, created TEXT NOT NULL, data TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id,number));
CREATE TABLE IF NOT EXISTS deca_events(id INTEGER PRIMARY KEY,document_id INTEGER,user_id INTEGER,event TEXT,at TEXT,detail TEXT);
CREATE TABLE IF NOT EXISTS login_limits(key TEXT PRIMARY KEY, failures INTEGER NOT NULL, blocked_until REAL NOT NULL DEFAULT 0, updated REAL NOT NULL);
'''


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY'), DATA_DIR=os.environ.get('DATA_DIR',str(ROOT/'data')), PUBLIC_BASE_URL=os.environ.get('PUBLIC_BASE_URL',''), SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE','1')=='1',PERMANENT_SESSION_LIFETIME=timedelta(hours=8),MAX_CONTENT_LENGTH=128*1024)
    if test_config: app.config.update(test_config)
    if os.environ.get('TRUST_ONE_PROXY')=='1': app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1)
    if not app.config['SECRET_KEY'] or (not app.config['TESTING'] and (len(app.config['SECRET_KEY'])<32 or app.config['SECRET_KEY'].startswith('PENDIENTE'))): raise RuntimeError('Configura SECRET_KEY con un valor aleatorio antes de arrancar.')
    base = app.config['PUBLIC_BASE_URL'].rstrip('/')
    parsed = urlparse(base)
    if not base or parsed.scheme not in ('http','https') or not parsed.netloc or parsed.path or parsed.username or parsed.password or parsed.query or parsed.fragment or 'PENDIENTE' in base:
        raise RuntimeError('PUBLIC_BASE_URL debe ser el origen de la aplicación, por ejemplo https://documentos.tudominio.es')
    if not app.config['TESTING'] and parsed.scheme != 'https' and parsed.hostname not in ('localhost','127.0.0.1'):
        raise RuntimeError('Utiliza HTTPS en producción.')
    app.config['PUBLIC_BASE_URL']=base
    app.config['TRUSTED_HOSTS']=[parsed.hostname] + (['localhost','127.0.0.1'] if app.config['TESTING'] or parsed.hostname in ('localhost','127.0.0.1') else [])
    directory=Path(app.config['DATA_DIR']); directory.mkdir(parents=True,exist_ok=True)
    (directory/'pdfs').mkdir(exist_ok=True)
    (directory/'logos').mkdir(exist_ok=True)
    app.config['DATABASE']=str(directory/'asemaco_new.sqlite3')
    with sqlite3.connect(app.config['DATABASE']) as con:
        con.execute('PRAGMA journal_mode=WAL'); con.execute('PRAGMA foreign_keys=ON'); con.executescript(SCHEMA)
        con.execute('BEGIN IMMEDIATE')
        columns={r[1] for r in con.execute('PRAGMA table_info(documents)')}
        for name,kind in [('expires_at','TEXT'),('finished_at','TEXT'),('delete_after','TEXT'),('parent_id','INTEGER'),('root_id','INTEGER'),('pdf_sha256','TEXT'),('legacy','INTEGER NOT NULL DEFAULT 1')]:
            if name not in columns: con.execute(f'ALTER TABLE documents ADD COLUMN {name} {kind}')
        # No inventar fechas de finalización de documentos existentes.
        con.execute('UPDATE documents SET root_id=id WHERE root_id IS NULL')
        con.execute('UPDATE documents SET expires_at=NULL,delete_after=NULL WHERE finished_at IS NULL')
        con.execute('CREATE INDEX IF NOT EXISTS documents_expiry ON documents(expires_at)')
    cleanup_state={'last':0}

    def db():
        if 'db' not in g:
            g.db=sqlite3.connect(app.config['DATABASE'],timeout=15); g.db.row_factory=sqlite3.Row; g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @app.teardown_appcontext
    
    def close_db(error):
        con=g.pop('db',None)
        if con: con.close()

    @app.before_request

    def before():
        if time.monotonic()-cleanup_state['last']>=3600:
            try:
                purge_expired(app.config['DATABASE'],directory)
                cleanup_state['last']=time.monotonic()
            except Exception: app.logger.exception('No se pudo completar la limpieza automática.')
        request.max_content_length=3*1024*1024 if request.endpoint=='profile' else 128*1024
        if 'csrf' not in session: session['csrf']=secrets.token_urlsafe(32)
        g.user=None
        if session.get('uid'):
            u=db().execute('SELECT * FROM users WHERE id=? AND active=1',(session['uid'],)).fetchone()
            if u and u['auth_version']==session.get('av'): g.user=u
            else: session.clear()
        if request.method=='POST':
            supplied=request.form.get('csrf','')
            if not supplied or not secrets.compare_digest(supplied,session.get('csrf','')): abort(400,'La sesión del formulario ha caducado. Recarga la página.')
        if g.user and g.user['must_change'] and request.endpoint not in ('password','logout','static'):
            if not request.path.startswith('/d/'): return redirect(url_for('password'))

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='SAMEORIGIN'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
        response.headers['X-Robots-Tag']='noindex, nofollow, noarchive'
        if request.endpoint!='static': response.headers['Cache-Control']='no-store'
        if app.config['SESSION_COOKIE_SECURE']: response.headers['Strict-Transport-Security']='max-age=31536000'
        return response

    @app.context_processor
    def context(): return dict(profile_fields=PROFILE_FIELDS,cat_fields=CAT_FIELDS,cat_names=CAT_NAMES,csrf=session.get('csrf',''),user=g.user,local_test=base.startswith('http://'))

    @app.template_filter('expiry_date')
    def expiry_date(value):
        if not value: return 'Pendiente de finalizar servicio'
        return datetime.fromisoformat(value).astimezone(ZoneInfo('Europe/Madrid')).strftime('%d/%m/%Y')

    def login_required(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            if not g.user: return redirect(url_for('login'))
            return fn(*args,**kwargs)
        return wrapped

    def admin_required(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args,**kwargs):
            if g.user['role']!='admin': abort(403)
            return fn(*args,**kwargs)
        return wrapped

    dummy_hash=generate_password_hash(secrets.token_urlsafe(24))

    # ruta para la pagina de forgot paswword
    @app.route('/forgot-password', methods=['GET', 'POST'])
    def forgot_password():
        if request.method == 'POST':
            
            flash('Si el correo existe, se han enviado las instrucciones a tu bandeja.', 'success')
            return redirect(url_for('login'))
        # redirigir a la pagina de olvidar la contraseña 
        return render_template('forgot_password.html')

    @app.route('/login',methods=['GET','POST'])
    def login():
        if g.user: return redirect(url_for('home'))
        if request.method=='POST':
            email=request.form.get('email','').strip().lower()[:254]; pw=request.form.get('password','')[:256]
            now=time.time(); keys=[hashlib.sha256(('ip:'+request.remote_addr).encode()).hexdigest(),hashlib.sha256(('email:'+email).encode()).hexdigest()]
            limits=[db().execute('SELECT * FROM login_limits WHERE key=?',(key,)).fetchone() for key in keys]
            if any(r and r['blocked_until']>now for r in limits):
                flash('Demasiados intentos. Espera 15 minutos para volver a probar.','error'); return render_template('login.html'),429
            u=db().execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
            ok=check_password_hash(u['password'] if u else dummy_hash,pw)
            if u and u['active'] and ok:
                session.clear(); session.update(uid=u['id'],av=u['auth_version'],csrf=secrets.token_urlsafe(32)); session.permanent=True
                db().execute('DELETE FROM login_limits WHERE key=?',(keys[1],)); db().commit()
                return redirect(url_for('password' if u['must_change'] else 'home'))
            for key, r in zip(keys,limits):
                count=(r['failures'] if r and now-r['updated']<900 else 0)+1
                db().execute('INSERT OR REPLACE INTO login_limits VALUES(?,?,?,?)',(key,count,now+900 if count>=8 else 0,now))
            db().commit(); flash('Correo o contraseña incorrectos, o cuenta desactivada.','error')
        return render_template('login.html')

    @app.post('/logout')
    def logout(): session.clear(); return redirect(url_for('login'))

    @app.route('/password',methods=['GET','POST'])
    @login_required
    def password():
        if request.method=='POST':
            pw=request.form.get('password','')
            if not check_password_hash(g.user['password'],request.form.get('current','')): flash('La contraseña actual no es correcta.','error')
            elif not 12<=len(pw)<=128 or pw!=request.form.get('confirm'): flash('Usa entre 12 y 128 caracteres y confirma la misma contraseña.','error')
            elif check_password_hash(g.user['password'],pw): flash('Elige una contraseña diferente a la actual.','error')
            else:
                db().execute('UPDATE users SET password=?,must_change=0,auth_version=auth_version+1 WHERE id=?',(generate_password_hash(pw),g.user['id'])); db().commit()
                session['av']=g.user['auth_version']+1; flash('Contraseña actualizada.','success'); return redirect(url_for('home'))
        return render_template('password.html')

    @app.get('/')
    @login_required
    def home():

        row=db().execute('SELECT * FROM documents ' \
        'WHERE user_id=? AND (expires_at IS NULL OR expires_at>?) ' \
        'ORDER BY number DESC LIMIT 1',(g.user['id'],utc_now())).fetchone()
        #llamar funcion para borrar los docuemntos y pdf asociados al entrar en la pagina 
        docs=db().execute('SELECT * FROM documents WHERE user_id=? AND (expires_at IS NULL OR expires_at>?) ORDER BY number DESC',(g.user['id'],utc_now())).fetchall()
        return render_template('home.html',docs=[dict(r,info=json.loads(r['data'])) for r in docs],profile=json.loads(g.user['profile']),count_entries=db().execute('SELECT count(*) FROM entries WHERE user_id=?',(g.user['id'],)).fetchone()[0])

    def clean(fields): return {key:request.form.get(key,'').strip()[:300] for key,label in fields}

    @app.route('/profile',methods=['GET','POST'])
    @login_required
    def profile():
        p=json.loads(g.user['profile'])
        if request.method=='POST':
            previous=p.get('logo','')
            p=clean(PROFILE_FIELDS)
            if previous: p['logo']=previous
            upload=request.files.get('logo')
            remove=request.form.get('remove_logo')=='yes'
            new_path=None
            if not p['name'] or not p['nif']: flash('Completa la razón social y el NIF.','error')
            else:
                try:
                    if upload and upload.filename:
                        if remove: raise ValueError('Elige subir un logotipo o quitar el actual, no ambas opciones.')
                        raw=upload.read(2*1024*1024+1)
                        if len(raw)>2*1024*1024: raise ValueError('El logotipo debe ocupar como máximo 2 MB.')
                        try:
                            with PillowImage.open(io.BytesIO(raw)) as source:
                                if source.format not in ('PNG','JPEG') or source.width*source.height>16_000_000:
                                    raise ValueError('Utiliza una imagen PNG o JPG de hasta 16 megapíxeles.')
                                source.load()
                                image=ImageOps.exif_transpose(source).convert('RGBA')
                                image.thumbnail((600,600))
                                canvas=PillowImage.new('RGB',image.size,'white'); canvas.paste(image,mask=image.getchannel('A'))
                                result=io.BytesIO(); canvas.save(result,format='JPEG',quality=85,optimize=True)
                        except (UnidentifiedImageError,OSError,PillowImage.DecompressionBombError) as exc:
                            raise ValueError('No se pudo leer la imagen. Utiliza un archivo PNG o JPG válido.') from exc
                        p['logo']=secrets.token_hex(16)+'.jpg'
                        new_path=directory/'logos'/p['logo']
                        with new_path.open('xb') as output: output.write(result.getvalue())
                    elif remove: p.pop('logo',None)
                    db().execute('UPDATE users SET profile=? WHERE id=?',(json.dumps(p,ensure_ascii=False),g.user['id'])); db().commit()
                except ValueError as exc:
                    if new_path: new_path.unlink(missing_ok=True)
                    p.pop('logo',None)
                    if previous: p['logo']=previous
                    flash(str(exc),'error')
                except Exception:
                    db().rollback()
                    if new_path: new_path.unlink(missing_ok=True)
                    p.pop('logo',None)
                    if previous: p['logo']=previous
                    app.logger.exception('Error guardando perfil'); flash('No se pudieron guardar los datos. Vuelve a intentarlo.','error')
                else:
                    if previous and p.get('logo')!=previous:
                        old=logo_path(previous)
                        if old: old.unlink(missing_ok=True)
                    flash('Datos de empresa guardados. El logotipo se aplicará a los nuevos PDF.','success')
        return render_template('profile.html',profile=p,has_logo=bool(logo_path(p.get('logo',''))))

    def logo_path(name):
        # Solo nombres internos aleatorios; nunca rutas recibidas del usuario.
        import re
        if not re.fullmatch(r'[0-9a-f]{32}\.jpg',name): return None
        path=directory/'logos'/name
        return path if path.is_file() else None

    @app.get('/profile/logo')
    @login_required
    def profile_logo():
        path=logo_path(json.loads(g.user['profile']).get('logo',''))
        if not path: abort(404)
        return send_file(path,mimetype='image/jpeg',conditional=False)

    @app.route('/datos_habituales',methods=['GET','POST'])
    @login_required
    def datos_habituales():
        kind=request.args.get('kind','cargadores')
        if kind not in CAT_FIELDS: abort(404)
        if request.method=='POST':
            action = request.form.get('action')
            if action == 'delete':
                if g.user['role'] == 'admin':
                    db().execute('DELETE FROM entries WHERE id=? AND kind=?',(request.form.get('id'),kind))
                else:
                    db().execute('DELETE FROM entries WHERE id=? AND user_id=? AND kind=?',(request.form.get('id'),g.user['id'],kind))
                db().commit()
                flash('Registro eliminado. Los documentos generados se conservan.','success')
            elif action == 'edit':
                data = clean(CAT_FIELDS[kind])
                if not data.get('name'):
                    flash('Completa el nombre o matrícula.', 'error')
                else:
                    if g.user['role'] == 'admin':
                        db().execute('UPDATE entries SET data=? WHERE id=? AND kind=?', (json.dumps(data, ensure_ascii=False), request.form.get('id'), kind))
                    else:
                        db().execute('UPDATE entries SET data=? WHERE id=? AND user_id=? AND kind=?', (json.dumps(data, ensure_ascii=False), request.form.get('id'), g.user['id'], kind))
                    db().commit()
                    flash('Registro actualizado correctamente.', 'success')
            else:
                data=clean(CAT_FIELDS[kind])
                if not data['name']: flash('Completa el nombre o matrícula.','error')
                elif db().execute('SELECT count(*) FROM entries WHERE user_id=?',(g.user['id'],)).fetchone()[0]>=2000: flash('Se ha alcanzado el límite de registros.','error')
                else:
                    db().execute('INSERT INTO entries(user_id,kind,data) VALUES(?,?,?)',(g.user['id'],kind,json.dumps(data,ensure_ascii=False))); db().commit(); flash('Registro guardado.','success')
            return redirect(url_for('datos_habituales',kind=kind))
        
        if g.user['role'] == 'admin':
            rows=db().execute('SELECT * FROM entries WHERE kind=? ORDER BY id DESC',(kind,)).fetchall()
        else:
            rows=db().execute('SELECT * FROM entries WHERE user_id=? AND kind=? ORDER BY id DESC',(g.user['id'],kind)).fetchall()
        return render_template('datos_habituales.html',kind=kind,entries=[dict(r,info=json.loads(r['data'])) for r in rows])

    #
    @app.route('/documents/<int:source_id>/correct',methods=['GET','POST'])
    @app.route('/documents/new',methods=['GET','POST'])
    @login_required
    def new_document(source_id=None):
        try:
            source=None
            if source_id:
                source=db().execute('SELECT * FROM documents WHERE id=? AND user_id=?',(source_id,g.user['id'])).fetchone()
                if not source: abort(404)
                latest=db().execute('SELECT max(id) FROM documents WHERE root_id=?',(source['root_id'],)).fetchone()[0]
                if source['finished_at'] or latest!=source_id: abort(409,'Rectifica la última versión de un servicio sin finalizar.')
            p=json.loads(g.user['profile']); rows=db().execute('SELECT * FROM entries WHERE user_id=?',(g.user['id'],)).fetchall()
            catalog={k:[dict(id=r['id'],**json.loads(r['data'])) for r in rows if r['kind']==k] for k in CAT_FIELDS}
            now=datetime.now(ZoneInfo('Europe/Madrid'))
            planned_default=now+timedelta(minutes=30)
            data={'date':planned_default.strftime('%Y-%m-%d'),'time':planned_default.strftime('%H:%M'),'place':p.get('city',''),'carrier':p,'goods':[]}
        except Exception:
            app.logger.exception('Error preparando nuevo documento')
            raise
        if source:
            data=json.loads(source['data']); data['change_reason']=''
        if request.method=='POST':
            data={k:request.form.get(k,'').strip()[:500] for k in ['date','time','place','vehicle','trailer','instructions','responsibility','authorization','attachments','observations','weight']}
            data.update({section:{k:request.form.get(section+'_'+k,'').strip()[:300] for k,_ in fields} for section,fields in [('sender',PROFILE_FIELDS),('origin',PROFILE_FIELDS),('destination',PROFILE_FIELDS),('carrier',PROFILE_FIELDS),('driver',CAT_FIELDS['conductores'])]})
            data['goods']=[{'description':request.form.get('goods_'+str(i),'').strip()[:200],'quantity':request.form.get('quantity_'+str(i),'').strip()[:30],'code':request.form.get('code_'+str(i),'').strip()[:80]} for i in range(7) if request.form.get('goods_'+str(i),'').strip()]
            data['articulated']=request.form.get('articulated')=='yes'
            data['special_authorization']=request.form.get('special_authorization')=='yes'
            data['weight_kind']=request.form.get('weight_kind','kg')
            data['weight_reason']=request.form.get('weight_reason','').strip()[:500]
            data['change_reason']=request.form.get('change_reason','').strip()[:500]
            
            errors=[]
            if request.form.get('articulated') not in ('yes','no') or request.form.get('special_authorization') not in ('yes','no'): errors.append('Indica si hay remolque y si se requiere autorización especial.')
            for s in ['sender','origin','destination','carrier']:
                if not data[s]['name'] or not data[s]['nif']: errors.append('Completa nombre y NIF de cargador, origen, destino y transportista.') ; break
            if not data['sender']['address'] or not data['sender']['city']: errors.append('Completa domicilio y población del cargador contractual.')
            for site in ('origin','destination'):
                if not data[site]['address'] or not data[site]['city']: errors.append('Completa dirección y población del origen y destino.')
            if not data['weight'] or not any(c.isdigit() for c in data['weight']): errors.append('Indica el peso en kg o una magnitud alternativa que permita determinarlo.')
            if data['weight_kind']=='kg':
                amount=re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*(?:kg)?',data['weight'],re.IGNORECASE)
                if not amount or float(amount.group(1).replace(',','.'))<=0: errors.append('Indica un peso positivo en kg, sin separador de miles (ejemplo: 8000 kg).')
            if data['weight_kind'] not in ('kg','alternative'): errors.append('Indica la forma de determinar el peso.')
            if data['weight_kind']=='alternative' and not data['weight_reason']: errors.append('Explica la magnitud alternativa y por qué no puede determinarse el peso exacto.')
            if data['articulated'] and not data['trailer']: errors.append('Indica la matrícula del remolque o semirremolque.')
            if data['special_authorization'] and not data['authorization']: errors.append('Identifica la autorización especial de circulación.')
            if source and not data['change_reason']: errors.append('Indica el motivo de la rectificación.')
            if request.form.get('driver_delivery')!='yes': errors.append('Confirma que entregarás el PDF y el nuevo QR al conductor.')
            if not source and request.form.get('before_departure')!='yes': errors.append('Confirma que el servicio todavía no ha comenzado.')
            if not data['vehicle'] or not data['driver']['name'] or not data['goods']: errors.append('Completa vehículo, conductor y al menos una mercancía.')
            try:
                planned=datetime.strptime(data['date']+' '+data['time'],'%Y-%m-%d %H:%M').replace(tzinfo=ZoneInfo('Europe/Madrid'))
                if not source and planned+timedelta(minutes=1)<now: errors.append('La fecha/hora prevista de inicio no puede ser anterior a la generación del DeCA.')
            except ValueError: errors.append('La fecha u hora no es válida.')
            if request.form.get('public_consent')!='yes': errors.append('Confirma que el documento será accesible mediante su QR.')
            if errors:
                for e in errors: flash(e,'error')
            else:
                con=db(); token=secrets.token_urlsafe(32)
                try:
                    con.execute('BEGIN IMMEDIATE')
                    if source:
                        current=con.execute('SELECT * FROM documents WHERE id=?',(source_id,)).fetchone()
                        latest=con.execute('SELECT max(id) FROM documents WHERE root_id=?',(source['root_id'],)).fetchone()[0]
                        if not current or current['finished_at'] or latest!=source_id: raise ValueError('El servicio ha cambiado; recarga su ficha.')
                    number=con.execute('SELECT next_number FROM users WHERE id=?',(g.user['id'],)).fetchone()[0]
                    # Generar antes de guardar evita registros con PDF inválido.
                    custom_logo=logo_path(p.get('logo',''))
                    logo_bytes=custom_logo.read_bytes() if custom_logo else None
                    data['_public_url']=app.config['PUBLIC_BASE_URL']+'/d/'+token
                    stamp=now.isoformat(timespec='seconds')
                    data['_created_at']=stamp
                    data['_modified_at']=stamp
                    if source:
                        data['_parent_number']=source['number'];data['_parent_url']=document_url(source)
                        data['_original_created_at']=json.loads(source['data']).get('_original_created_at',source['created'])
                    pdf=make_pdf(data,number,data['_public_url'],logo_bytes=logo_bytes)
                    if len(pdf)>5_000_000: raise ValueError('El PDF supera el máximo de 5 MB.')
                    pdf_path=directory/'pdfs'/f'{token}.pdf'
                    with pdf_path.open('xb') as output: output.write(pdf)
                    ident=con.execute('SELECT max(value)+1 FROM (SELECT coalesce(max(id),0) value FROM documents UNION ALL SELECT coalesce(max(document_id),0) FROM deca_events)').fetchone()[0]
                    root=source['root_id'] if source else ident
                    cur=con.execute('INSERT INTO documents(id,user_id,number,token,created,data,parent_id,root_id,pdf_sha256,legacy) VALUES(?,?,?,?,?,?,?,?,?,0)',(ident,g.user['id'],number,token,stamp,json.dumps(data,ensure_ascii=False),source_id,root,hashlib.sha256(pdf).hexdigest()))
                    event(ident,'rectificacion' if source else 'creacion',json.dumps({'parent_id':source_id,'motivo':data['change_reason']},ensure_ascii=False))
                    con.execute('UPDATE users SET next_number=next_number+1 WHERE id=?',(g.user['id'],))
                    
                    if request.form.get('save_all_data') == '1':
                        existing_rows = con.execute('SELECT kind, data FROM entries WHERE user_id=?', (g.user['id'],)).fetchall()
                        saved_names = {k: set() for k in ['cargadores', 'origenes', 'destinos', 'transportistas', 'vehiculos', 'conductores']}
                        for r in existing_rows:
                            try: saved_names[r['kind']].add(json.loads(r['data']).get('name', '').strip().lower())
                            except: pass

                        def save_if_new(kind, item_data):
                            if not item_data or not item_data.get('name'): return
                            if item_data['name'].strip().lower() not in saved_names.get(kind, set()):
                                con.execute('INSERT INTO entries(user_id, kind, data) VALUES(?, ?, ?)', (g.user['id'], kind, json.dumps(item_data, ensure_ascii=False)))
                                saved_names[kind].add(item_data['name'].strip().lower())

                        for section, kind in [('sender', 'cargadores'), ('origin', 'origenes'), ('destination', 'destinos'), ('carrier', 'transportistas')]:
                            save_if_new(kind, data.get(section, {}))
                        
                        if data.get('vehicle'):
                            save_if_new('vehiculos', {'name': data['vehicle'], 'trailer': data.get('trailer', '')})
                            
                        save_if_new('conductores', data.get('driver', {}))

                    if request.form.get('hide_save_warning') == '1':
                        p = json.loads(g.user['profile'])
                        if not p.get('hide_save_warning'):
                            p['hide_save_warning'] = True
                            con.execute('UPDATE users SET profile=? WHERE id=?', (json.dumps(p, ensure_ascii=False), g.user['id']))

                    con.commit()
                except Exception:
                    con.rollback()
                    (directory/'pdfs'/f'{token}.pdf').unlink(missing_ok=True)
                    app.logger.exception('Error generando documento'); flash('No se pudo guardar el documento. Tus datos siguen en el formulario.','error')
                else: return redirect(url_for('document',doc_id=cur.lastrowid))
        return render_template('new.html',data=data,catalog=catalog,next_number=g.user['next_number'],source=source)

    @app.get('/documents/<int:doc_id>')
    @login_required
    def document(doc_id):
        row=db().execute('SELECT * FROM documents WHERE id=? AND user_id=? AND (expires_at IS NULL OR expires_at>?)',(doc_id,g.user['id'],utc_now())).fetchone()
        if not row: abort(404)
        info=json.loads(row['data'])
        versions=db().execute('SELECT * FROM documents WHERE root_id=? AND user_id=? ORDER BY id',(row['root_id'],g.user['id'])).fetchall()
        events=db().execute('SELECT * FROM deca_events WHERE document_id IN (SELECT id FROM documents WHERE root_id=?) ORDER BY id',(row['root_id'],)).fetchall()
        #comprobar
      

        return render_template(
            'document.html',
            doc=row,info=info,
            public_url=document_url(row),
            versions=versions,
            events=events,
            qr_activo=not row['token'].startswith('caducado_'),
            can_delete=bool(row['delete_after'] and row['delete_after']<=utc_now()),
            finished_default=datetime.now(ZoneInfo('Europe/Madrid')).strftime('%Y-%m-%dT%H:%M:%S'))

    def document_url(row):
        return json.loads(row['data']).get('_public_url') or app.config['PUBLIC_BASE_URL']+'/d/'+row['token']

    def shareable_owned_document(doc_id):
        row=db().execute('SELECT * FROM documents WHERE id=? AND user_id=? AND revoked=0 AND (expires_at IS NULL OR expires_at>?)',(doc_id,g.user['id'],utc_now())).fetchone()
        if not row: abort(404)
        return row

    @app.get('/documents/<int:doc_id>/qr')
    @login_required
    def download_qr(doc_id):
        row=shareable_owned_document(doc_id)
        return send_file(io.BytesIO(make_qr_png(document_url(row))),mimetype='image/png',as_attachment=True,download_name=f'QR_documento_{row["number"]:06d}.png')

    @app.get('/documents/<int:doc_id>/bundle')
    @login_required
    def download_bundle(doc_id):
        row=shareable_owned_document(doc_id)
        path=directory/'pdfs'/f'{row["token"]}.pdf'
        if not path.is_file(): abort(503)
        contents=path.read_bytes()
        if row['pdf_sha256'] and hashlib.sha256(contents).hexdigest()!=row['pdf_sha256']: abort(503)
        output=io.BytesIO()
        with ZipFile(output,'w',ZIP_DEFLATED) as archive:
            archive.writestr(f'Documento_control_{row["number"]:06d}.pdf',contents)
            archive.writestr(f'QR_documento_{row["number"]:06d}.png',make_qr_png(document_url(row)))
        output.seek(0)
        return send_file(output,mimetype='application/zip',as_attachment=True,download_name=f'Documento_y_QR_{row["number"]:06d}.zip')

    @app.get('/documents/<int:doc_id>/download')
    @login_required
    def download(doc_id):
        row=db().execute('SELECT * FROM documents WHERE id=? AND user_id=? AND (expires_at IS NULL OR expires_at>?)',(doc_id,g.user['id'],utc_now())).fetchone()
        if not row: abort(404)
        return pdf_response(row,True)

    def pdf_response(row,attachment=False):
        path=directory/'pdfs'/f'{row["token"]}.pdf'
        if not path.is_file(): abort(503)
        contents=path.read_bytes()
        if row['pdf_sha256'] and hashlib.sha256(contents).hexdigest()!=row['pdf_sha256']:
            app.logger.error('Integridad de PDF incorrecta: documento %s',row['id']); abort(503)
        return send_file(io.BytesIO(contents),mimetype='application/pdf',as_attachment=attachment,download_name=f'Documento_control_{row["number"]:06d}.pdf',conditional=False)

    @app.get('/d/<token>')
    def public_document(token):
        if len(token)!=43: abort(404)
        row=db().execute('SELECT d.* FROM documents d JOIN users u ON u.id=d.user_id WHERE d.token=? AND d.revoked=0 AND (d.expires_at IS NULL OR d.expires_at>?)',(token,utc_now())).fetchone()
        if not row: abort(404)

        
        return pdf_response(row)

    def owned(doc_id):
        row=db().execute('SELECT * FROM documents WHERE id=? AND user_id=?',(doc_id,g.user['id'])).fetchone()
        if not row: abort(404)
        return row

    def event(doc_id,kind,detail=''):
        db().execute('INSERT INTO deca_events(document_id,user_id,event,at,detail) VALUES(?,?,?,?,?)',(doc_id,g.user['id'],kind,utc_now(),detail))

    @app.post('/documents/<int:doc_id>/finish')
    @login_required
    def finish_service(doc_id):
        row=owned(doc_id)
        if row['finished_at']: abort(409,'El servicio ya está finalizado.')
        if request.form.get('confirm_finish')!='yes': abort(400)
        try:
            entered=datetime.fromisoformat(request.form.get('finished_at',''))
            if entered.tzinfo is not None: raise ValueError()
            ended=entered.replace(tzinfo=ZoneInfo('Europe/Madrid')).astimezone(timezone.utc)
            end=ended.isoformat(timespec='seconds')
            if ended>datetime.now(timezone.utc): raise ValueError()
        except ValueError: abort(400,'Introduce una finalización válida, no futura.')
        con=db(); con.execute('BEGIN IMMEDIATE')
        versions=con.execute('SELECT * FROM documents WHERE root_id=? ORDER BY id',(row['root_id'],)).fetchall()
        if any(r['finished_at'] or datetime.fromisoformat(r['created'])>ended for r in versions):
            con.rollback(); abort(409,'La finalización debe ser posterior a la creación de todas las versiones.')
        latest_data=json.loads(versions[-1]['data'])
        try:
            planned=datetime.strptime(latest_data['date']+' '+latest_data['time'],'%Y-%m-%d %H:%M').replace(tzinfo=ZoneInfo('Europe/Madrid'))
        except (ValueError,KeyError): planned=None
        if planned and ended<planned:
            con.rollback(); abort(409,'La finalización no puede ser anterior al inicio del transporte.')
        con.execute('UPDATE documents SET finished_at=?,delete_after=?,expires_at=? WHERE root_id=?',(end,expiry_after(end,months=12),expiry_after(end),row['root_id']))
        event(doc_id,'finalizacion',end); con.commit()
        flash('Servicio finalizado. Se conservarán todas sus versiones durante 15 meses desde esta fecha.','success')
        return redirect(url_for('document',doc_id=doc_id))

    @app.post('/documents/<int:doc_id>/revoke')
    @login_required
    def revoke(doc_id):
        row=owned(doc_id)
        if not row['delete_after'] or row['delete_after']>utc_now(): abort(409,'El QR se mantiene disponible durante la conservación mínima de un año desde la finalización.')
        db().execute('UPDATE documents SET revoked=1 WHERE root_id=?',(row['root_id'],));event(doc_id,'desactivacion_qr');db().commit()
        flash('QR desactivados. Los PDF se conservan hasta completar los 15 meses.','success')
        return redirect(url_for('document',doc_id=doc_id))

    @app.post('/documents/<int:doc_id>/restore')
    @login_required
    def restore_query(doc_id):
        row=owned(doc_id)
        if request.form.get('confirm_restore')!='yes': abort(400)
        db().execute('UPDATE documents SET revoked=0 WHERE root_id=?',(row['root_id'],));event(doc_id,'reactivacion_qr');db().commit()
        flash('Consulta por QR reactivada.','success');return redirect(url_for('document',doc_id=doc_id))

    @app.post('/documents/<int:doc_id>/delete')
    @login_required
    def delete_document(doc_id):
        row=owned(doc_id)
        if request.form.get('confirm_delete')!='yes': abort(400)
        if not row['delete_after'] or row['delete_after']>utc_now(): abort(409,'Borrado bloqueado: registra la finalización y conserva el documento al menos un año desde esa fecha.')
        try: count=remove_documents(app.config['DATABASE'],directory,doc_id=doc_id,user_id=g.user['id'])
        except Exception:
            app.logger.exception('No se pudo eliminar documento');flash('No se pudo eliminar el documento. Vuelve a intentarlo.','error');return redirect(url_for('document',doc_id=doc_id))
        if not count: abort(409,'Las versiones aún están protegidas por conservación.')
        flash('Servicio y todas sus versiones eliminados. Sus QR ya no funcionan.','success');return redirect(url_for('home'))

    @app.cli.command('purge-expired')
    def purge_command():
        click.echo(f'Documentos eliminados: {purge_expired(app.config["DATABASE"],directory)}')

    @app.route('/admin',methods=['GET','POST'])
    @admin_required
    def admin():
        if request.method=='POST':
            action=request.form.get('action')
            if action=='create':
                email=request.form.get('email','').strip().lower()[:254]; name=request.form.get('name','').strip()[:300]; pw=request.form.get('password','')
                if not name or '@' not in email or not 12<=len(pw)<=128: flash('Introduce empresa, correo y contraseña temporal de al menos 12 caracteres.','error')
                else:
                    try:
                        db().execute('INSERT INTO users(email,password,profile) VALUES(?,?,?)',(email,generate_password_hash(pw),json.dumps({'name':name},ensure_ascii=False))); db().commit(); flash('Socio creado. Debe cambiar la contraseña temporal al entrar.','success')
                    except sqlite3.IntegrityError: flash('Ese correo ya tiene una cuenta.','error')
            elif action in ('toggle','reset'):
                u=db().execute("SELECT * FROM users WHERE id=? AND role='member'",(request.form.get('id'),)).fetchone()
                if not u: abort(404)
                if action=='toggle': db().execute('UPDATE users SET active=1-active,auth_version=auth_version+1 WHERE id=?',(u['id'],)); flash('Estado de la cuenta actualizado.','success')
                else:
                    pw=request.form.get('password','')
                    if not 12<=len(pw)<=128: flash('La contraseña temporal necesita entre 12 y 128 caracteres.','error'); return redirect(url_for('admin'))
                    db().execute('UPDATE users SET password=?,must_change=1,auth_version=auth_version+1 WHERE id=?',(generate_password_hash(pw),u['id'])); flash('Contraseña restablecida. Entrega la contraseña temporal al socio.','success')
                db().commit()
            return redirect(url_for('admin'))
        users=db().execute("SELECT id,email,active,profile FROM users WHERE role='member' ORDER BY id DESC").fetchall()
        return render_template('admin.html',members=[dict(r,info=json.loads(r['profile'])) for r in users])

    @app.cli.command('create-admin')
    @click.option('--email',prompt=True)
    @click.option('--password',prompt=True,hide_input=True,confirmation_prompt=True)
    def create_admin(email,password):
        if len(password)<12: raise click.ClickException('Usa al menos 12 caracteres.')
        try:
            db().execute("INSERT INTO users(email,password,role,must_change,profile) VALUES(?,?,'admin',0,?)",(email.strip().lower(),generate_password_hash(password),json.dumps({'name':'Administración ASEMACO'}))); db().commit()
        except sqlite3.IntegrityError: raise click.ClickException('El correo ya existe.')
        click.echo('Administrador creado.')


    @app.errorhandler(404)
    def not_found(error): return render_template('error.html',message='El documento o la página no está disponible. El enlace puede haber sido desactivado.'),404
    @app.errorhandler(403)
    def forbidden(error): return render_template('error.html',message='Tu cuenta no tiene acceso a esta página.'),403
    @app.errorhandler(400)
    def bad_request(error): return render_template('error.html',message='Solicitud no válida. Recarga la página e inténtalo de nuevo.'),400
    @app.errorhandler(409)
    def conflict(error): return render_template('error.html',message=error.description),409
    @app.errorhandler(413)
    def too_large(error): return render_template('error.html',message='El archivo o formulario supera el tamaño permitido. El logotipo debe ocupar como máximo 2 MB.'),413
    return app

