import sqlite3,tempfile,unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch
from app import create_app
from werkzeug.security import generate_password_hash
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.app=create_app({'TESTING':True,'SECRET_KEY':'test-only','DATA_DIR':self.tmp.name,'PUBLIC_BASE_URL':'http://localhost','SESSION_COOKIE_SECURE':False})
  with sqlite3.connect(self.app.config['DATABASE']) as c:
   for email,role in [('uno@test.es','member'),('dos@test.es','member'),('admin@test.es','admin')]: c.execute('INSERT INTO users(email,password,role,must_change) VALUES(?,?,?,0)',(email,generate_password_hash('Prueba-segura-123'),role))
  self.a,self.b,self.admin,self.public=[self.app.test_client() for _ in range(4)]
  self.responses=[]
  for cl in (self.a,self.b,self.admin,self.public):
   original=cl.open
   def tracked(*args,_open=original,**kwargs):
    r=_open(*args,**kwargs); self.responses.append(r); return r
   cl.open=tracked
  for cl,email in [(self.a,'uno@test.es'),(self.b,'dos@test.es'),(self.admin,'admin@test.es')]:
   cl.get('/login'); self.post(cl,'/login',email=email,password='Prueba-segura-123')
 def tearDown(self):
  for r in self.responses: r.close()
  self.tmp.cleanup()
 def post(self,cl,path,**data):
  with cl.session_transaction() as s: data['csrf']=s['csrf']
  return cl.post(path,data=data)
 def document(self,cl,source=None,**override):
  d={'date':(datetime.now(ZoneInfo('Europe/Madrid'))+timedelta(days=1)).strftime('%Y-%m-%d'),'time':'10:00','place':'Madrid','vehicle':'1234 ABC','trailer':'R1234','driver_name':'Conductor ejemplo','driver_nif':'ID123','driver_phone':'600000000','goods_0':'Material <especial> & embalado','quantity_0':'12 palés','code_0':'MAT01','weight':'8000 kg','public_consent':'yes','before_departure':'yes','driver_delivery':'yes','articulated':'yes','special_authorization':'no'}
  for section in ('sender','origin','destination','carrier'):
   for k,v in {'name':section.title()+' Ejemplo SL','nif':'B00000000','address':'Calle Ejemplo, 10','city':'28000 Madrid','country':'España','phone':'600000000','email':'ejemplo@test.es'}.items(): d[section+'_'+k]=v
  d.update(override)
  r=self.post(cl,f'/documents/{source}/correct' if source else '/documents/new',**d); self.assertEqual(r.status_code,302); self.assertIn('/documents/',r.location); id=int(r.location.rsplit('/',1)[1])
  with sqlite3.connect(self.app.config['DATABASE']) as c: row=c.execute('SELECT token,number FROM documents WHERE id=?',(id,)).fetchone()
  return id,*row
 def test_isolation(self):
  self.post(self.a,'/profile',name='Empresa privada UNO',nif='B001'); self.assertNotIn(b'Empresa privada UNO',self.b.get('/profile').data)
  self.post(self.a,'/catalogs',name='Cargador privado UNO',nif='B001'); self.assertIn(b'Cargador privado UNO',self.a.get('/catalogs').data); self.assertNotIn(b'Cargador privado UNO',self.b.get('/catalogs').data)
  self.post(self.b,'/catalogs',action='delete',id='1'); self.assertIn(b'Cargador privado UNO',self.a.get('/catalogs').data); self.assertEqual(self.b.get('/admin').status_code,403)
 def test_pdf_public_revocation_and_numbering(self):
  id,token,n=self.document(self.a); self.assertEqual(n,1)
  for suffix in ('','/download'): self.assertEqual(self.b.get(f'/documents/{id}'+suffix).status_code,404)
  r=self.public.get('/d/'+token); self.assertEqual(r.status_code,200); self.assertTrue(r.data.startswith(b'%PDF')); self.assertEqual(r.data,self.a.get(f'/documents/{id}/download').data)
  self.post(self.b,f'/documents/{id}/revoke'); self.assertEqual(self.public.get('/d/'+token).status_code,200)
  self.assertEqual(self.post(self.a,f'/documents/{id}/revoke').status_code,409)
  self.eligible(id)
  self.post(self.a,f'/documents/{id}/revoke'); self.assertEqual(self.public.get('/d/'+token).status_code,404); self.assertEqual(self.a.get(f'/documents/{id}/download').status_code,200)
  self.assertEqual(self.document(self.a)[2],2); self.assertEqual(self.document(self.b)[2],1)
 def test_csrf_and_protection(self):
  self.assertEqual(self.a.post('/profile',data={'name':'Cambio'}).status_code,400); self.assertEqual(self.public.get('/documents/new').status_code,302); self.assertEqual(self.public.get('/d/'+'x'*43).status_code,404)
 def test_deactivation(self):
  _,token,_=self.document(self.a); self.post(self.admin,'/admin',action='toggle',id='1'); self.assertEqual(self.a.get('/').status_code,302); self.assertEqual(self.public.get('/d/'+token).status_code,200)
  self.post(self.admin,'/admin',action='toggle',id='1'); self.assertEqual(self.public.get('/d/'+token).status_code,200)
 def test_password_reset(self):
  self.post(self.admin,'/admin',action='reset',id='1',password='Temporal-nueva-123'); self.assertEqual(self.a.get('/').status_code,302)
  self.a.get('/login'); self.assertTrue(self.post(self.a,'/login',email='uno@test.es',password='Temporal-nueva-123').location.endswith('/password')); self.assertTrue(self.a.get('/documents/new').location.endswith('/password'))
  self.post(self.a,'/password',current='Temporal-nueva-123',password='Definitiva-nueva-456',confirm='Definitiva-nueva-456'); self.assertEqual(self.a.get('/').status_code,200)
 def test_pages_render(self):
  for path in ['/','/profile','/catalogs','/documents/new','/password']: self.assertEqual(self.a.get(path).status_code,200,path)
  self.assertEqual(self.admin.get('/admin').status_code,200)

 def test_generation_failure_preserves_number(self):
  with patch('app.make_pdf',side_effect=RuntimeError('simulated')):
   with self.assertLogs(self.app.logger,level='ERROR'):
    with self.assertRaises(AssertionError): self.document(self.a)
  with sqlite3.connect(self.app.config['DATABASE']) as c:
   self.assertEqual(c.execute('SELECT count(*) FROM documents').fetchone()[0],0)
   self.assertEqual(c.execute('SELECT next_number FROM users WHERE id=1').fetchone()[0],1)
  self.assertEqual(self.document(self.a)[2],1)
 def test_login_throttle(self):
  cl=self.public;cl.get('/login')
  for _ in range(8): self.post(cl,'/login',email='inexistente@test.es',password='incorrecta')
  self.assertEqual(self.post(cl,'/login',email='inexistente@test.es',password='incorrecta').status_code,429)

 def logo(self,color='blue',size=(800,200)):
  import io
  from PIL import Image
  stream=io.BytesIO();Image.new('RGBA',size,color).save(stream,format='PNG');stream.seek(0);return stream
 def test_company_logo_isolation_and_immutable_pdf(self):
  import io
  from PIL import Image
  from pdf_document import make_pdf
  self.post(self.a,'/profile',name='Empresa UNO',nif='B001',logo=(self.logo(),'logo.png'))
  r=self.a.get('/profile/logo');self.assertEqual(r.status_code,200);original=r.data
  with Image.open(io.BytesIO(original)) as im: self.assertEqual(im.size,(600,150));self.assertEqual(im.format,'JPEG')
  self.assertEqual(self.b.get('/profile/logo').status_code,404);self.assertEqual(self.public.get('/profile/logo').status_code,302)
  with patch('app.make_pdf',wraps=make_pdf) as renderer:
   _,token,_=self.document(self.a);self.assertEqual(renderer.call_args.kwargs['logo_bytes'],original)
   self.document(self.b);self.assertIsNone(renderer.call_args.kwargs['logo_bytes'])
  immutable=self.public.get('/d/'+token).data
  self.post(self.a,'/profile',name='Empresa UNO editada',nif='B001');self.assertEqual(self.a.get('/profile/logo').data,original)
  self.post(self.a,'/profile',name='Empresa UNO',nif='B001',logo=(self.logo('red'),'nuevo.png'))
  replacement=self.a.get('/profile/logo').data;self.assertNotEqual(replacement,original);self.assertEqual(self.public.get('/d/'+token).data,immutable)
  with patch('app.make_pdf',wraps=make_pdf) as renderer:
   self.document(self.a);self.assertEqual(renderer.call_args.kwargs['logo_bytes'],replacement)
  self.post(self.a,'/profile',name='Empresa UNO',nif='B001',remove_logo='yes');self.assertEqual(self.a.get('/profile/logo').status_code,404);self.assertEqual(self.public.get('/d/'+token).data,immutable)
  with patch('app.make_pdf',wraps=make_pdf) as renderer:
   self.document(self.a);self.assertIsNone(renderer.call_args.kwargs['logo_bytes'])
 def test_invalid_logo_keeps_profile_and_saved_logo(self):
  import io
  self.post(self.a,'/profile',name='Empresa UNO',nif='B001',logo=(self.logo(),'logo.png'));original=self.a.get('/profile/logo').data
  for upload in [(io.BytesIO(b'<svg>invalid</svg>'),'logo.png'),(io.BytesIO(b'x'*(2*1024*1024+1)),'large.png'),(self.logo(size=(5000,3300)),'huge.png')]:
   r=self.post(self.a,'/profile',name='No guardar',nif='B002',logo=upload)
   self.assertEqual(r.status_code,200);self.assertIn(b'notice error',r.data);self.assertEqual(self.a.get('/profile/logo').data,original);self.assertNotIn(b'No guardar',self.a.get('/profile').data)
  self.assertEqual(self.post(self.a,'/profile',name='UNO',nif='B001',logo=(io.BytesIO(b'x'*(3*1024*1024)),'large.png')).status_code,413)

 def test_qr_and_bundle_downloads(self):
  import io
  from zipfile import ZipFile
  from PIL import Image
  from qr_image import make_qr_png
  id,token,_=self.document(self.a)
  r=self.a.get(f'/documents/{id}/qr');self.assertEqual(r.status_code,200);self.assertEqual(r.mimetype,'image/png');self.assertIn('QR_documento_000001.png',r.headers['Content-Disposition'])
  expected_url='http://localhost/d/'+token;self.assertEqual(r.data,make_qr_png(expected_url))
  with Image.open(io.BytesIO(r.data)) as image:
   self.assertEqual(image.format,'PNG');self.assertGreaterEqual(image.width,400)
  bundle=self.a.get(f'/documents/{id}/bundle');self.assertEqual(bundle.status_code,200)
  with ZipFile(io.BytesIO(bundle.data)) as z:
   self.assertEqual(set(z.namelist()),{'Documento_control_000001.pdf','QR_documento_000001.png'})
   self.assertEqual(z.read('QR_documento_000001.png'),r.data)
   self.assertEqual(z.read('Documento_control_000001.pdf'),self.public.get('/d/'+token).data)
  self.assertIn(b'Descargar QR en PNG',self.a.get(f'/documents/{id}').data)
  for suffix in ('qr','bundle'):
   self.assertEqual(self.b.get(f'/documents/{id}/{suffix}').status_code,404)
   self.assertEqual(self.public.get(f'/documents/{id}/{suffix}').status_code,302)
  self.app.config['PUBLIC_BASE_URL']='http://other.test'
  self.assertEqual(self.a.get(f'/documents/{id}/qr').data,make_qr_png(expected_url))
  self.eligible(id)
  self.post(self.a,f'/documents/{id}/revoke')
  for suffix in ('qr','bundle'):self.assertEqual(self.a.get(f'/documents/{id}/{suffix}').status_code,404)
  self.assertEqual(self.public.get('/d/'+token).status_code,404)
  self.assertEqual(self.a.get(f'/documents/{id}/download').status_code,200)
 def test_legacy_document_qr(self):
  import json
  from qr_image import make_qr_png
  id,token,_=self.document(self.a)
  with sqlite3.connect(self.app.config['DATABASE']) as c:
   data=json.loads(c.execute('SELECT data FROM documents WHERE id=?',(id,)).fetchone()[0]);data.pop('_public_url')
   c.execute('UPDATE documents SET data=? WHERE id=?',(json.dumps(data),id))
  self.assertEqual(self.a.get(f'/documents/{id}/qr').data,make_qr_png('http://localhost/d/'+token))

 def test_owner_delete_removes_file_and_both_qr_links(self):
  from pathlib import Path
  id,token,_=self.document(self.a);path=Path(self.tmp.name)/'pdfs'/f'{token}.pdf'
  self.assertTrue(path.exists())
  self.assertEqual(self.post(self.b,f'/documents/{id}/delete',confirm_delete='yes').status_code,404);self.assertTrue(path.exists())
  self.assertEqual(self.post(self.a,f'/documents/{id}/delete').status_code,400)
  self.assertEqual(self.a.post(f'/documents/{id}/delete',data={'confirm_delete':'yes'}).status_code,400)
  self.assertEqual(self.post(self.a,f'/documents/{id}/delete',confirm_delete='yes').status_code,409)
  self.eligible(id)
  page=self.a.get(f'/documents/{id}').data
  self.assertIn(b'15 meses',page);self.assertIn(b'Eliminar documento definitivamente',page);self.assertIn(b'confirm_delete',page)
  self.assertEqual(self.post(self.a,f'/documents/{id}/delete',confirm_delete='yes').status_code,302)
  self.assertFalse(path.exists());self.assertEqual(self.public.get('/d/'+token).status_code,404)
  for suffix in ('','/download','/qr','/bundle'):self.assertEqual(self.a.get(f'/documents/{id}'+suffix).status_code,404)
  with sqlite3.connect(self.app.config['DATABASE']) as c:self.assertEqual(c.execute('SELECT count(*) FROM documents').fetchone()[0],0)
  self.assertEqual(self.document(self.a)[2],2)
 def test_expiry_blocks_access_and_purge_frees_files(self):
  from pathlib import Path
  from retention import utc_now
  id,token,_=self.document(self.a);other,other_token,_=self.document(self.b)
  path=Path(self.tmp.name)/'pdfs'/f'{token}.pdf'
  with sqlite3.connect(self.app.config['DATABASE']) as c:c.execute('UPDATE documents SET expires_at=? WHERE id=?',('2000-01-01T00:00:00+00:00',id))
  self.eligible(id,expired=True)
  self.assertEqual(self.public.get('/d/'+token).status_code,404)
  for suffix in ('','/download','/qr','/bundle'):self.assertEqual(self.a.get(f'/documents/{id}'+suffix).status_code,404)
  r=self.app.test_cli_runner().invoke(args=['purge-expired']);self.assertEqual(r.exit_code,0,r.output);self.assertIn('1',r.output)
  self.assertFalse(path.exists());self.assertEqual(self.public.get('/d/'+other_token).status_code,200)
  self.assertTrue((Path(self.tmp.name)/'pdfs'/f'{other_token}.pdf').exists())
 def test_calendar_month_expiry(self):
  from retention import expiry_after
  self.assertEqual(expiry_after('2026-11-30T12:00:00+01:00'),'2028-02-29T11:00:00+00:00')
  self.assertEqual(expiry_after('2025-11-30T12:00:00+01:00'),'2027-02-28T11:00:00+00:00')
  self.assertEqual(expiry_after('2026-09-30T12:00:00+02:00'),'2027-12-30T11:00:00+00:00')
 def test_failed_delete_preserves_document(self):
  from pathlib import Path
  id,token,_=self.document(self.a)
  self.eligible(id)
  with patch('retention.Path.rename',side_effect=OSError('simulated')):
   with self.assertLogs(self.app.logger,level='ERROR'):
    self.assertEqual(self.post(self.a,f'/documents/{id}/delete',confirm_delete='yes').status_code,302)
  self.assertTrue((Path(self.tmp.name)/'pdfs'/f'{token}.pdf').exists());self.assertEqual(self.public.get('/d/'+token).status_code,200)
 def test_legacy_retention_migration(self):
  import json
  from pathlib import Path
  from app import SCHEMA
  from retention import expiry_after
  with tempfile.TemporaryDirectory() as directory:
   database=Path(directory)/'asemaco.sqlite3'
   with sqlite3.connect(database) as c:
    c.executescript(SCHEMA);c.execute('INSERT INTO users(email,password) VALUES(?,?)',('legacy@test.es','test'))
    c.execute('INSERT INTO documents(user_id,number,token,created,data) VALUES(?,?,?,?,?)',(1,1,'a'*43,'2026-01-31T12:00:00+01:00','{}'))
   app=create_app({'TESTING':True,'SECRET_KEY':'test','DATA_DIR':directory,'PUBLIC_BASE_URL':'http://localhost','SESSION_COOKIE_SECURE':False})
   with sqlite3.connect(database) as c:self.assertEqual(c.execute('SELECT expires_at FROM documents').fetchone()[0],None)
   create_app({'TESTING':True,'SECRET_KEY':'test','DATA_DIR':directory,'PUBLIC_BASE_URL':'http://localhost','SESSION_COOKIE_SECURE':False})

 def eligible(self,id,expired=False):
  with sqlite3.connect(self.app.config['DATABASE']) as c:
   root=c.execute('SELECT root_id FROM documents WHERE id=?',(id,)).fetchone()[0]
   c.execute('UPDATE documents SET finished_at=?,delete_after=?,expires_at=? WHERE root_id=?',('2000-01-01T00:00:00+00:00','2001-01-01T00:00:00+00:00','2001-04-01T00:00:00+00:00' if expired else '2099-01-01T00:00:00+00:00',root))
 def test_rectification_preserves_original_and_requires_reason(self):
  id,token,n=self.document(self.a);original=self.public.get('/d/'+token).data
  self.assertEqual(self.b.get(f'/documents/{id}/correct').status_code,404)
  self.assertEqual(self.a.get(f'/documents/{id}/correct').status_code,200)
  with self.assertRaises(AssertionError):self.document(self.a,source=id,change_reason='')
  new,new_token,_=self.document(self.a,source=id,change_reason='Cambio de vehículo',vehicle='5678 DEF')
  self.assertNotEqual(token,new_token);self.assertEqual(self.public.get('/d/'+token).data,original)
  with sqlite3.connect(self.app.config['DATABASE']) as c:
   row=c.execute('SELECT parent_id,root_id,pdf_sha256,data FROM documents WHERE id=?',(new,)).fetchone()
   self.assertEqual(row[0],id);self.assertEqual(row[1],id);self.assertEqual(len(row[2]),64)
   self.assertIn('Cambio de vehículo',row[3]);self.assertIn('5678 DEF',row[3])
  self.assertEqual(self.a.get(f'/documents/{id}/correct').status_code,409)
  self.assertIn(b'Versiones de este servicio',self.a.get(f'/documents/{new}').data)
  self.eligible(new)
  self.assertEqual(self.post(self.a,f'/documents/{id}/delete',confirm_delete='yes').status_code,302)
  self.assertEqual(self.public.get('/d/'+token).status_code,404);self.assertEqual(self.public.get('/d/'+new_token).status_code,404)
 def test_finish_starts_protected_retention_and_blocks_corrections(self):
  from retention import expiry_after
  current=datetime.now(ZoneInfo('Europe/Madrid'))
  id,token,n=self.document(self.a,date=current.strftime('%Y-%m-%d'),time=current.strftime('%H:%M'))
  self.assertEqual(self.post(self.b,f'/documents/{id}/finish',confirm_finish='yes',finished_at='2000-01-01T00:00:00').status_code,404)
  self.assertEqual(self.post(self.a,f'/documents/{id}/finish',confirm_finish='yes',finished_at='2000-01-01T00:00:00').status_code,409)
  now=datetime.now(ZoneInfo('Europe/Madrid')).strftime('%Y-%m-%dT%H:%M:%S')
  self.assertEqual(self.post(self.a,f'/documents/{id}/finish',confirm_finish='yes',finished_at=now).status_code,302)
  with sqlite3.connect(self.app.config['DATABASE']) as c:
   end,expiry,earliest=c.execute('SELECT finished_at,expires_at,delete_after FROM documents WHERE id=?',(id,)).fetchone()
   self.assertEqual(expiry,expiry_after(end));self.assertEqual(earliest,expiry_after(end,months=12))
  self.assertEqual(self.a.get(f'/documents/{id}/correct').status_code,409)
  self.assertEqual(self.post(self.a,f'/documents/{id}/revoke').status_code,409)
  self.assertEqual(self.post(self.a,f'/documents/{id}/delete',confirm_delete='yes').status_code,409)
  self.assertEqual(self.public.get('/d/'+token).status_code,200)
 def test_independent_worker_purges_closed_versions_only(self):
  import os,sys,subprocess
  from pathlib import Path
  original,token,_=self.document(self.a)
  correction,new_token,_=self.document(self.a,source=original,change_reason='Vehículo sustituido',vehicle='0000 XYZ')
  unfinished,open_token,_=self.document(self.a)
  self.eligible(correction,expired=True)
  env=dict(os.environ,DATA_DIR=self.tmp.name)
  subprocess.run([sys.executable,'retention_worker.py','--once'],env=env,check=True,capture_output=True)
  with sqlite3.connect(self.app.config['DATABASE']) as c:
   self.assertEqual(c.execute('SELECT id FROM documents').fetchall(),[(unfinished,)])
   self.assertEqual(c.execute("SELECT count(*) FROM deca_events WHERE event='eliminacion_automatica'").fetchone()[0],2)
   self.assertEqual(c.execute("SELECT count(*) FROM deca_events WHERE document_id IN (?,?) AND detail!=''",(original,correction)).fetchone()[0],0)
  self.assertFalse((Path(self.tmp.name)/'pdfs'/f'{token}.pdf').exists())
  self.assertFalse((Path(self.tmp.name)/'pdfs'/f'{new_token}.pdf').exists())
  self.assertEqual(self.public.get('/d/'+open_token).status_code,200)
 def test_unfinished_documents_are_not_purged(self):
  id,token,_=self.document(self.a)
  with sqlite3.connect(self.app.config['DATABASE']) as c:c.execute('UPDATE documents SET created=? WHERE id=?',('2000-01-01T00:00:00+00:00',id))
  r=self.app.test_cli_runner().invoke(args=['purge-expired']);self.assertEqual(r.exit_code,0)
  self.assertEqual(self.public.get('/d/'+token).status_code,200)
 def test_pdf_integrity_failure_blocks_delivery(self):
  from pathlib import Path
  id,token,_=self.document(self.a);path=Path(self.tmp.name)/'pdfs'/f'{token}.pdf';path.write_bytes(b'changed')
  with self.assertLogs(self.app.logger,level='ERROR'):self.assertEqual(self.public.get('/d/'+token).status_code,503)
  self.assertEqual(self.a.get(f'/documents/{id}/bundle').status_code,503)
 def test_maximum_pdf_size_rolls_back(self):
  with patch('app.make_pdf',return_value=b'x'*5_000_001):
   with self.assertLogs(self.app.logger,level='ERROR'):
    with self.assertRaises(AssertionError):self.document(self.a)
  with sqlite3.connect(self.app.config['DATABASE']) as c:
   self.assertEqual(c.execute('SELECT count(*) FROM documents').fetchone()[0],0)
   self.assertEqual(c.execute('SELECT next_number FROM users WHERE id=1').fetchone()[0],1)
 def test_required_fields_and_conditional_validation(self):
  for field,value in [('weight',''),('weight','0 kg'),('weight','-5 kg'),('sender_address',''),('origin_city',''),('destination_address',''),('trailer',''),('driver_delivery',''),('before_departure',''),('special_authorization',''),('date','2000-01-01')]:
   with self.subTest(field=field):
    with self.assertRaises(AssertionError):self.document(self.a,**{field:value})
  with self.assertRaises(AssertionError):self.document(self.a,special_authorization='yes',authorization='')
  self.document(self.a,special_authorization='yes',authorization='AUT-123')
  self.document(self.a,articulated='no',trailer='')
  with self.assertRaises(AssertionError):self.document(self.a,weight_kind='alternative',weight_reason='')
  self.document(self.a,weight_kind='alternative',weight='10 m3',weight_reason='Densidad 500 kg/m3. Carga a granel sin báscula.')
 def test_metadata_timestamp_matches_record(self):
  import re
  id,token,_=self.document(self.a)
  data=self.public.get('/d/'+token).data
  with sqlite3.connect(self.app.config['DATABASE']) as c:stamp=c.execute('SELECT created FROM documents WHERE id=?',(id,)).fetchone()[0]
  from datetime import timezone
  expected=datetime.fromisoformat(stamp).astimezone(timezone.utc).strftime('D:%Y%m%d%H%M%SZ').encode()
  self.assertIn(b'/CreationDate ('+expected+b')',data);self.assertIn(b'/ModDate ('+expected+b')',data)
