import io
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from qr_image import make_qr_png
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
FONT_DIR=Path(reportlab.__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("Asemaco",str(FONT_DIR/"Vera.ttf")))
pdfmetrics.registerFont(TTFont("AsemacoBold",str(FONT_DIR/"VeraBd.ttf")))
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER

def make_pdf(data,number,url,logo_bytes=None):
    out=io.BytesIO(); styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodySmall',fontName='Asemaco',fontSize=8,leading=10,spaceAfter=1))
    styles.add(ParagraphStyle(name='LabelSmall',fontName='AsemacoBold',fontSize=7,leading=9,textColor=HexColor('#676767')))
    styles.add(ParagraphStyle(name='SectionA',fontName='AsemacoBold',fontSize=9,leading=12,textColor=HexColor('#de6e14'),spaceBefore=5,spaceAfter=6))
    styles.add(ParagraphStyle(name='TitleA',fontName='AsemacoBold',fontSize=15,leading=18,textColor=HexColor('#30353a')))
    def p(value,style='BodySmall'): return Paragraph(escape(str(value or '—')).replace('\n','<br/>'),styles[style])
    def party(section):
        item=data.get(section,{})
        return [p(item.get('name')),p('NIF: '+item.get('nif','')),p(item.get('address')),p(' · '.join(filter(None,[item.get('city'),item.get('country')]))),p(' · '.join(filter(None,[item.get('phone'),item.get('email')])))]
    orange=HexColor('#ed7b22'); gray=HexColor('#e3e5e7'); width=515
    def box(rows,colwidths):
        t=Table(rows,colWidths=colwidths,hAlign='LEFT'); t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BOX',(0,0),(-1,-1),.5,gray),('INNERGRID',(0,0),(-1,-1),.4,gray),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)])); return t
    qrbuf=io.BytesIO(make_qr_png(url))
    logo=Image(io.BytesIO(logo_bytes) if logo_bytes else str(Path(__file__).parent/'static/asemaco.jpg'))
    scale=min(90/logo.imageWidth,90/logo.imageHeight)
    logo.drawWidth=logo.imageWidth*scale; logo.drawHeight=logo.imageHeight*scale
    # Cada logotipo conserva sus proporciones dentro del mismo espacio.
    header=Table([[logo,[p('DOCUMENTO DE CONTROL','TitleA'),Spacer(1,8),p(f'Nº {number:06d}'),p('DeCA · Transporte de mercancías')],Image(qrbuf,width=83,height=83)]],colWidths=[105,317,93])
    header.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    story=[header,box([[p('FECHA / HORA DEL TRANSPORTE','LabelSmall'),p('LUGAR DE EMISIÓN','LabelSmall')],[p(data.get('date','')+' · '+data.get('time','')),p(data.get('place'))]],[175,340]),p('01  REMITENTE / CARGADOR CONTRACTUAL','SectionA'),box([[party('sender')]],[width]),p('02  ORIGEN Y DESTINO','SectionA'),box([[p('Lugar de origen','LabelSmall'),p('Destino / descarga','LabelSmall')],[party('origin'),party('destination')]],[257.5,257.5]),p('03  TRANSPORTISTA EFECTIVO','SectionA'),box([[party('carrier')]],[width]),box([[p('MATRÍCULA VEHÍCULO','LabelSmall'),p('MATRÍCULA REMOLQUE','LabelSmall')],[p(data.get('vehicle')),p(data.get('trailer'))]],[257.5,257.5]),p('04  MERCANCÍAS','SectionA')]
    if data.get('_parent_number'):
        story.insert(1,box([[p('RECTIFICACIÓN DEL DOCUMENTO '+str(data['_parent_number']).zfill(6),'LabelSmall')],[p('Motivo: '+data.get('change_reason',''))],[p('Creación original: '+data.get('_original_created_at',''))],[p('Documento anterior: '+data.get('_parent_url',''))]],[width]))
    if data.get('_created_at'):
        stamp=datetime.fromisoformat(data['_created_at']).astimezone(timezone.utc)
        story.insert(1,p('Creación del fichero: '+stamp.strftime('%d/%m/%Y %H:%M:%S UTC')))
    if url.startswith('http://'): story.insert(1,p('PRUEBA LOCAL: dirección HTTP sin acceso operativo desde otros equipos.'))
    rows=[[p('Descripción','LabelSmall'),p('Cantidad','LabelSmall'),p('Código','LabelSmall')]]
    for item in data.get('goods',[]): rows.append([p(item['description']),p(item['quantity']),p(item['code'])])
    story += [box(rows,[320,80,115]),p('Peso / magnitud para determinar el peso: '+data.get('weight',''))]
    if data.get('weight_kind')=='alternative': story.append(p('Determinación alternativa del peso: '+data.get('weight_reason','')))
    driver=data.get('driver',{})
    story += [p('05  CONDUCTOR E INDICACIONES','SectionA'),box([[p(driver.get('name')),p('DNI: '+driver.get('nif','')),p('Tel.: '+driver.get('phone',''))]],[220,155,140])]
    for key,label in [('instructions','Instrucciones al conductor'),('responsibility','Responsabilidad conjunta'),('authorization','Autorización especial'),('attachments','Referencias de adjuntos'),('observations','Observaciones')]:
        if data.get(key): story.append(p(label+': '+data[key]))
    story += [Spacer(1,10),p('El QR abre directamente este PDF. El emisor debe entregarlo al conductor antes del inicio del servicio; si es una rectificación, debe entregar el nuevo PDF y QR.')]
    def footer(c,d):
        if data.get('_created_at'):
            instant=datetime.fromisoformat(data['_created_at']).astimezone(timezone.utc)
            c.setDateFormatter(lambda *args:instant.strftime('D:%Y%m%d%H%M%SZ'))
        c.setStrokeColor(orange); c.line(40,33,555,33); c.setFont('Asemaco',7); c.setFillColor(HexColor('#676767')); c.drawString(40,21,'DECA . Documento de control'); c.drawRightString(555,21,f'{number:06d} · Página {d.page}')
    doc=SimpleDocTemplate(out,pagesize=A4,rightMargin=40,leftMargin=40,topMargin=22,bottomMargin=44,title=f'Documento de control {number:06d}',author='DECA')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()
