"""Anchor quote fields and apply handbook rules independently of model instructions."""
import re
from decimal import Decimal

from models import Recommendation


def handbook_rules(handbook):
    sections = re.split(r'^## ', handbook, flags=re.M)
    approved = set()
    known = set()
    maxima = {}
    for section in sections:
        if section.startswith('5.'):
            for line in section.splitlines():
                cells = [c.strip() for c in line.strip('|').split('|')]
                if len(cells) >= 5 and re.fullmatch(r'[A-Z]{3}', cells[0]):
                    approved.add(cells[1])
                    known.add(cells[1])
        if section.startswith('6.'):
            for line in section.splitlines():
                cells = [c.strip() for c in line.strip('|').split('|')]
                if len(cells) == 2 and cells[0] not in ('Vendor', '---') and line.startswith('|'):
                    known.add(cells[0])
        if section.startswith('9.'):
            for line in section.splitlines():
                cells = [c.strip() for c in line.strip('|').split('|')]
                if len(cells) >= 5 and re.fullmatch(r'CC-[A-Z]{2}-\d{3}', cells[0]):
                    maxima[cells[0]] = Decimal(cells[4].lstrip('$'))
    if not approved or not maxima:
        raise ValueError('Cannot parse authoritative handbook tables')
    return approved, known, maxima


def quote_fields(text, handbook, vendor_heading=None):
    """Extract explicit quote labels; prose instructions cannot rewrite labeled numbers."""
    _, known, _ = handbook_rules(handbook)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Prefer a standalone vendor heading/signature; this is a fact anchor, not approval.
    vendor = vendor_heading.strip() if vendor_heading else next((line for line in lines if line in known), None)
    if vendor is None:
        vendor = next((line.split(':', 1)[1].strip() for line in lines if re.match(r'(?i)^vendor\s*:', line)), None)
    def field(pattern, transform):
        matches = list(re.finditer(pattern, text, re.I | re.M))
        # Repeated explicit labels with conflicting numbers require review; never use hidden prose revisions.
        values = [transform(match.group(1)) for match in matches]
        return values[0] if values and all(value == values[0] for value in values) else None
    sku = field(r'^(?:Campus Customs SKU|Item)\s*:?\s*(?:[^\n]*\()?\b(CC-[A-Z]{2}-\d{3})\b', str)
    if sku is None:
        matches = set(re.findall(r'\bCC-[A-Z]{2}-\d{3}\b', text))
        sku = next(iter(matches)) if len(matches) == 1 else None
    return {'vendor': vendor, 'sku': sku,
            'unit_price': field(r'^Unit price\s*:?\s*\$([\d,]+(?:\.\d+)?)', lambda value: float(value.replace(',', ''))),
            'lead_time_days': field(r'^Lead time\s*:?\s*(\d+)\s*(?:business\s+)?days?', int),
            'minimum_order': field(r'^Minimum order\s*:?\s*(\d+)\s*units?', int)}


def decide(fields, handbook):
    approved, _, maxima = handbook_rules(handbook)
    failed = []
    if not fields['vendor']:
        failed.append('vendor is unknown')
    elif fields['vendor'] not in approved:
        failed.append('vendor is not approved')
    maximum = maxima.get(fields['sku'])
    if maximum is None:
        failed.append('SKU maximum unit cost is unknown')
    elif fields['unit_price'] is None:
        failed.append('unit price is unknown')
    elif Decimal(str(fields['unit_price'])) > maximum:
        failed.append('unit price exceeds the handbook maximum')
    for field, limit, label in [('lead_time_days', 21, 'quoted lead time'), ('minimum_order', 600, 'minimum order')]:
        if fields[field] is None:
            failed.append(f'{label} is unknown')
        elif fields[field] > limit:
            failed.append(f'{label} exceeds {limit}')
    if failed:
        reason = 'Do not recommend because ' + '; '.join(failed) + '.'
    else:
        reason = 'Recommend because the vendor is approved, the unit price is within the SKU maximum, the quoted day count is at most 21 (business-day wording is retained without calendar conversion), and the minimum order is at most 600 units.'
    return Recommendation(**fields, decision='do_not_recommend' if failed else 'recommend', reason=reason)
