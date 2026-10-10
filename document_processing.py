"""Visibility-aware extraction; retain quote facts and quarantine hidden segments locally."""
import re
import unicodedata
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pymupdf
import tinycss2
from bs4 import BeautifulSoup, Comment


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if unicodedata.category(c) != 'Cf')


def declarations(value):
    return {item.lower_name: tinycss2.serialize(item.value).strip().lower()
            for item in tinycss2.parse_declaration_list(value, skip_comments=True, skip_whitespace=True)
            if item.type == 'declaration'}


def rgb(value):
    names = {'white': '#ffffff', 'black': '#000000', 'transparent': None}
    value = names.get(value, value)
    if not value:
        return None
    if re.fullmatch(r'#[0-9a-f]{3}', value):
        return tuple(int(c * 2, 16) / 255 for c in value[1:])
    if re.fullmatch(r'#[0-9a-f]{6}', value):
        return tuple(int(value[i:i+2], 16) / 255 for i in (1, 3, 5))
    numbers = re.fullmatch(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,[^)]+)?\)', value)
    return tuple(int(n) / 255 for n in numbers.groups()) if numbers else None


def visible_html(source):
    soup = BeautifulSoup(source, 'html.parser')
    styles = {}
    quarantined = []
    for sheet in soup.find_all('style'):
        for rule in tinycss2.parse_stylesheet(sheet.get_text(), skip_comments=True, skip_whitespace=True):
            if rule.type == 'qualified-rule':
                selector = tinycss2.serialize(rule.prelude).strip()
                try:
                    for element in soup.select(selector):
                        styles.setdefault(id(element), {}).update(declarations(tinycss2.serialize(rule.content)))
                except Exception:
                    quarantined.append({'reason': 'unsupported_css_selector', 'text': selector})
    for element in soup.find_all(True):
        styles.setdefault(id(element), {}).update(declarations(element.get('style', '')))
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        quarantined.append({'reason': 'html_comment', 'text': str(comment)})
        comment.extract()
    for element in list(soup.find_all(['script', 'style', 'head', 'template'])):
        if element.parent is not None:
            quarantined.append({'reason': 'non_rendered_markup', 'text': element.get_text()})
            element.decompose()
    def hidden_reason(element):
        chain = [element, *[parent for parent in element.parents if getattr(parent, 'name', None)]]
        foreground, background = None, (1, 1, 1)
        for ancestor in reversed(chain):
            style = styles.get(id(ancestor), {})
            if ancestor.has_attr('hidden') or style.get('display') == 'none' or style.get('visibility') in ('hidden', 'collapse'):
                return 'hidden_css_or_attribute'
            if style.get('opacity') in ('0', '0.0'):
                return 'zero_opacity'
            size = re.fullmatch(r'([\d.]+)(px|pt)?', style.get('font-size', ''))
            if size and float(size.group(1)) <= 1:
                return 'unreadably_small_font'
            foreground = rgb(style.get('color')) if style.get('color') else foreground
            background = rgb(style.get('background-color', style.get('background'))) or background
        if foreground is not None and max(abs(a-b) for a, b in zip(foreground, background)) < .02:
            return 'text_matches_background'
        return None
    for element in list(soup.find_all(True)):
        if element.parent is None:
            continue
        reason = hidden_reason(element)
        if reason:
            quarantined.append({'reason': reason, 'text': element.get_text('\n', strip=True)})
            element.decompose()
    return normalized(soup.get_text('\n', strip=True)), quarantined


def visible_pdf(path):
    text, quarantined = [], []
    with pymupdf.open(path) as document:
        for page_number, page in enumerate(document, 1):
            drawings = page.get_drawings()
            for block in page.get_text('dict', clip=pymupdf.INFINITE_RECT())['blocks']:
                for line in block.get('lines', []):
                    accepted = []
                    for span in line.get('spans', []):
                        value = span['text']
                        box = pymupdf.Rect(span['bbox'])
                        reason = None
                        background = (1, 1, 1)
                        for drawing in drawings:
                            if drawing.get('fill') and drawing['rect'].contains(box):
                                background = drawing['fill'][:3]
                        color = tuple(((span['color'] >> shift) & 255) / 255 for shift in (16, 8, 0))
                        if not page.rect.intersects(box):
                            reason = 'outside_page_bounds'
                        elif span['size'] <= 1:
                            reason = 'unreadably_small_font'
                        elif span.get('alpha', 255) == 0:
                            reason = 'zero_opacity'
                        elif max(abs(a-b) for a, b in zip(color, background)) < .02:
                            reason = 'text_matches_background'
                        if reason:
                            quarantined.append({'reason': reason, 'text': value, 'page': page_number,
                                                'font_size': span['size'], 'bbox': list(box), 'color': span['color']})
                        else:
                            accepted.append(value)
                    if accepted:
                        text.append(' '.join(accepted))
    if not text:
        raise ValueError('No readable PDF text; OCR or human review needed, not a purchasing refusal')
    return normalized('\n'.join(text)), quarantined


def process_document(path: Path):
    suffix = path.suffix.lower()
    if suffix in ('.html', '.htm'):
        text, quarantined = visible_html(path.read_text(encoding='utf-8'))
    elif suffix == '.pdf':
        text, quarantined = visible_pdf(path)
    elif suffix == '.eml':
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        body = message.get_body(preferencelist=('plain', 'html'))
        if not body:
            raise ValueError('Email has no readable body')
        content = body.get_content()
        text, quarantined = visible_html(content) if body.get_content_type() == 'text/html' else (normalized(content), [])
        for alternative in message.walk():
            if alternative.get_content_type() == 'text/html' and alternative is not body:
                _, excluded = visible_html(alternative.get_content())
                quarantined.extend(excluded)
                quarantined.append({'reason': 'non_selected_email_alternative', 'text': alternative.get_content()})
        headers = '\n'.join(f'{name}: {message.get(name, "")}' for name in ('From', 'To', 'Subject', 'Date'))
        text = headers + '\n\n' + text
    else:
        raise ValueError('Supported formats: HTML, PDF, .eml')
    return {'text': text, 'quarantined': quarantined,
            'limitations': 'Static CSS/PDF visibility heuristics, not a complete browser render or OCR; visible text remains untrusted.'}
