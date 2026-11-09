"""Plain, printable reports built from validated audit results."""
from html import escape
from pathlib import Path

from .common import redact, validate_results
from .report_text import CASE_NAMES, CONTROL_NAMES, STATUS_NAMES, describe_result


class _Document:
    def __init__(self, output_path, title):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate
        regular = Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf')
        if not regular.exists():
            regular = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        bold = regular.with_name(regular.stem + '-Bold.ttf')
        if not regular.exists() or not bold.exists():
            raise RuntimeError('PDF tiếng Việt cần fonts-dejavu-core')
        if 'CIS-Plain' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('CIS-Plain', str(regular)))
            pdfmetrics.registerFont(TTFont('CIS-Plain-Bold', str(bold)))
        self.styles = {
            'body': ParagraphStyle('body', fontName='CIS-Plain', fontSize=10, leading=14, spaceAfter=7),
            'small': ParagraphStyle('small', fontName='CIS-Plain', fontSize=9, leading=12, spaceAfter=6),
            'title': ParagraphStyle('title', fontName='CIS-Plain-Bold', fontSize=17, leading=23, alignment=1, spaceAfter=12),
            'section': ParagraphStyle('section', fontName='CIS-Plain-Bold', fontSize=11, leading=15, spaceBefore=9, spaceAfter=6, keepWithNext=True),
            'cell': ParagraphStyle('cell', fontName='CIS-Plain', fontSize=9, leading=12),
        }
        self.story = []
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=44, rightMargin=44,
                                    topMargin=40, bottomMargin=38, title=title, author='')
        self.colors = colors

    def para(self, value, style='body'):
        from reportlab.platypus import Paragraph
        return Paragraph(escape(str(redact(value))), self.styles[style])

    def add(self, value, style='body'):
        self.story.append(self.para(value, style))

    def table(self, rows, proportions):
        from reportlab.platypus import Table, TableStyle
        table = Table([[self.para(cell, 'cell') for cell in row] for row in rows],
                      colWidths=[self.doc.width * part for part in proportions], repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.colors.HexColor('#F2F2F2')),
            ('GRID', (0, 0), (-1, -1), 0.4, self.colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        self.story.append(table)

    def build(self):
        def footer(canvas, document):
            canvas.saveState()
            canvas.setFont('CIS-Plain', 9)
            canvas.drawCentredString(self.doc.pagesize[0] / 2, 21, str(document.page))
            canvas.restoreState()
        self.doc.build(self.story, onFirstPage=footer, onLaterPages=footer)


def generate_pdf_report(results, output_path, *, source_path=None):
    from cis_lab.report import summarize_results
    rows = redact(validate_results(results))
    summary = summarize_results(rows)
    doc = _Document(output_path, 'KẾT QUẢ KIỂM TRA CASSANDRA')
    doc.add(doc.doc.title, 'title')
    doc.add('Chương trình đọc cấu hình và quyền truy cập, rồi so với chính sách được duyệt.')
    if not rows:
        doc.add('Chưa có dữ liệu kiểm tra. Không đưa ra kết luận đạt.')
    if any('FIXTURE' in row['evidence'].upper() or 'SIMULATED' in row['evidence'].upper() for row in rows):
        doc.add('DỮ LIỆU GIẢ LẬP: chỉ dùng để thử chương trình, không phải kết quả từ máy thật.')
    counts = summary['status_counts']
    doc.add('Kết quả: ' + ', '.join(str(counts[s]) + ' ' + STATUS_NAMES[s].lower() for s in STATUS_NAMES if counts.get(s)) + '.', 'section')
    if rows:
        doc.add(str(summary['conclusive_control_count']) + ' mã có kết luận đạt/không đạt trên ' + str(len(rows)) +
                ' bản ghi. Một mã có thể được kiểm tra trên nhiều máy.', 'small')
    table = [['Mã', 'Nội dung kiểm tra', 'Kết quả', 'Máy / cụm']]
    for cid, group in summary['controls'].items():
        if group['result_count']:
            table.append([cid, CONTROL_NAMES[cid], STATUS_NAMES[group['aggregate_status']], ', '.join(group['targets'])])
    if len(table) > 1:
        doc.table(table, [0.08, 0.36, 0.23, 0.33])
    if summary['missing_controls']:
        doc.add(str(len(summary['missing_controls'])) + ' mục còn lại chưa có kết quả.', 'small')
    doc.add('Giải thích kết quả', 'section')
    for cid in summary['controls']:
        group = [r for r in rows if r['control_id'] == cid and r['status'] not in ('NOT_IMPLEMENTED', 'NOT_APPLICABLE')]
        if cid == '3.5' and len(group) > 1 and all(r['status'] == 'PASS' for r in group):
            doc.add('3.5. Địa chỉ mạng của các node', 'section')
            addresses = []
            for row in group:
                config = row['actual'].get('config', {}) if isinstance(row['actual'], dict) else {}
                addresses.append(row['target'] + ': ' + str(config.get('listen_address', config.get('listen_interface', 'xem evidence'))))
            doc.add('; '.join(addresses) + '. Các node dùng đúng địa chỉ nội bộ được phép.')
            continue
        for row in group:
            doc.add(cid + '. ' + CONTROL_NAMES[cid] + ' (' + row['target'] + ')', 'section')
            lines = describe_result(row)
            for line in lines[:6]:
                doc.add(line)
            if len(lines) > 6:
                doc.add('Còn ' + str(len(lines)-6) + ' phát hiện. Xem results.json để đọc đầy đủ.', 'small')
    doc.add('Đây là kết quả đã lưu. Dữ liệu và bằng chứng chi tiết nằm trong results.json và thư mục evidence/.', 'small')
    doc.build()


def generate_comparison_pdf(cases, output_path, *, source_path=None):
    from cis_lab.report import summarize_results
    prepared = [(name, redact(validate_results(rows)), summarize_results(rows)) for name, rows in cases.items()]
    doc = _Document(output_path, 'KẾT QUẢ CÁC LẦN KIỂM TRA')
    doc.add(doc.doc.title, 'title')
    doc.add('Bảng dưới dùng kết quả thử đã lưu. Mỗi dòng là một lần kiểm tra riêng.')
    if any('FIXTURE' in r['evidence'].upper() or 'SIMULATED' in r['evidence'].upper() for _, rows, _ in prepared for r in rows):
        doc.add('Có dữ liệu giả lập. Không dùng làm bằng chứng từ máy thật.')
    table = [['Lần kiểm tra', 'Đạt', 'Không đạt', 'Rà soát', 'Lỗi', 'Chưa làm']]
    for name, _, summary in prepared:
        counts = summary['status_counts']
        table.append([CASE_NAMES.get(name, name), *[str(counts[s]) for s in ['PASS', 'FAIL', 'NEEDS_REVIEW', 'ERROR', 'NOT_IMPLEMENTED']]])
    doc.table(table, [0.34, 0.09, 0.16, 0.14, 0.10, 0.17])
    doc.add('Các số trong bảng đếm theo bản ghi. Không cộng các lần chạy để kết luận thêm mã CIS.', 'small')
    for name, rows, _ in prepared:
        if name != 'drift':
            continue
        doc.add('Sai lệch đã phát hiện', 'section')
        for row in rows:
            if row['status'] == 'FAIL':
                doc.add(row['control_id'] + '. ' + CONTROL_NAMES[row['control_id']], 'section')
                lines = describe_result(row)
                for line in lines[:6]:
                    doc.add(line)
                if len(lines) > 6:
                    doc.add('Còn ' + str(len(lines)-6) + ' phát hiện. Xem JSON để đọc đầy đủ.')
    doc.add('Sau khi khôi phục', 'section')
    for name, _, summary in prepared:
        if name in ('clean', 'drift', 'restored'):
            counts = summary['status_counts']
            doc.add(CASE_NAMES[name] + ': ' + str(counts['PASS']) + ' đạt, ' + str(counts['FAIL']) + ' không đạt, ' + str(counts['ERROR']) + ' lỗi.')
    not_done = sorted({r['control_id'] for _, rows, _ in prepared for r in rows if r['status'] == 'NOT_IMPLEMENTED'})
    if not_done:
        doc.add('Chưa triển khai: ' + ', '.join(not_done) + '.')
    doc.add('Plan hiện chỉ là đề xuất, chưa tự thay đổi quyền. Kết quả gốc và bằng chứng được giữ riêng cho từng lần kiểm tra.', 'small')
    doc.build()
