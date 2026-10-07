import io
import qrcode


def make_qr_png(url):
    """El mismo QR para el PDF y la imagen que se entrega al conductor."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=12, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    output = io.BytesIO()
    qr.make_image(fill_color='black', back_color='white').save(output, format='PNG')
    return output.getvalue()
