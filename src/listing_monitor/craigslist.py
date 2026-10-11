import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ''.join(c.text() if isinstance(c, Node) else c for c in self.children)

    def find(self, *, tag=None, cls=None, id=None):
        result = []
        if ((tag is None or self.tag == tag) and
            (cls is None or cls in self.attrs.get('class', '').split()) and
            (id is None or self.attrs.get('id') == id)):
            result.append(self)
        for c in self.children:
            if isinstance(c, Node):
                result.extend(c.find(tag=tag, cls=cls, id=id))
        return result


class Tree(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'br', 'img', 'input', 'meta', 'link', 'hr', 'source', 'wbr', 'area', 'embed'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def first_text(root, **kwargs):
    nodes = root.find(**kwargs)
    return ' '.join(nodes[0].text().split()) if nodes else ''


def structured(root, id):
    nodes = root.find(tag='script', id=id)
    if not nodes:
        raise ValueError(f'Missing structured data: {id}; possible challenge or changed markup')
    return json.loads(nodes[0].text())


def number(value):
    if value is None:
        return None
    match = re.fullmatch(r'\s*\$?(-?[\d,]+(?:\.\d+)?)\s*', str(value))
    return float(match[1].replace(',', '')) if match else None


def source_id(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not (parsed.hostname == 'craigslist.org' or
                                      (parsed.hostname or '').endswith('.craigslist.org')):
        raise ValueError('Unexpected listing host')
    match = re.search(r'/([A-Za-z0-9_-]+)(?:\.html)?/?$', parsed.path)
    if not match:
        raise ValueError('Unrecognized listing URL')
    return match[1]


# County assignment requires an exact advertised locality, never the search area.
CITY_COUNTIES = {}
for county, cities in {
    'San Francisco': ['San Francisco'],
    'San Mateo': ['San Mateo', 'South San Francisco', 'Daly City', 'Brisbane', 'Burlingame',
        'Millbrae', 'San Bruno', 'Belmont', 'San Carlos', 'Redwood City', 'Menlo Park',
        'Atherton', 'East Palo Alto', 'Foster City', 'Half Moon Bay', 'Pacifica',
        'Portola Valley', 'Woodside', 'El Granada', 'Montara', 'Moss Beach', 'Pescadero'],
    'Santa Clara': ['San Jose', 'Santa Clara', 'Sunnyvale', 'Mountain View', 'Palo Alto',
        'Los Altos', 'Los Altos Hills', 'Cupertino', 'Campbell', 'Saratoga', 'Los Gatos',
        'Milpitas', 'Morgan Hill', 'Gilroy', 'Monte Sereno', 'San Martin'],
}.items():
    CITY_COUNTIES.update({c.casefold(): (c, county) for c in cities})


def geography(locality, label):
    candidate = locality or label
    match = CITY_COUNTIES.get(candidate.strip().casefold())
    return {'city': match[0] if match else None, 'county': match[1] if match else None,
            'geo_provenance': 'structured_locality' if locality else 'exact_location_label',
            'advertised_locality': locality, 'location_label': label}


def price_period(price, title, category):
    # Tie an explicit period to the advertised amount. A bare housing price is an
    # assumption, recorded separately so later analysis can require explicit evidence.
    patterns = {'night': r'(?:nt|night|day|daily)', 'week': r'(?:wk|week|weekly)',
                'month': r'(?:mo|month|monthly)'}
    explicit = set()
    for period, pattern in patterns.items():
        for match in re.finditer(r'\$?([\d,]+(?:\.\d+)?)\s*(?:/|per\s+)\s*'+pattern+r'\b', title, re.I):
            if number(match[1]) == price:
                explicit.add(period)
    if len(explicit) == 1:
        return explicit.pop(), 'explicit_title'
    if explicit or re.search(r'\b(nightly|daily|weekly|per night|per week)\b|/\s*(nt|wk)\b', title, re.I):
        return 'unknown', 'ambiguous_title'
    return 'month', 'housing_default_assumption'


def parse_search(html, category):
    root = Tree(html).root
    data = structured(root, 'ld_searchpage_results')
    entries = data.get('itemListElement')
    if not isinstance(entries, list):
        raise ValueError('Search item list missing')
    nodes = root.find(tag='li', cls='cl-static-search-result')
    if len(nodes) != len(entries):
        raise ValueError('Structured/static search counts disagree')
    indexed = {int(e['position']): e['item'] for e in entries}
    if len(indexed) != len(entries):
        raise ValueError('Duplicate structured positions')
    listings = []
    for pos, node in enumerate(nodes):
        title = first_text(node, cls='title')
        item = indexed[pos]
        if ' '.join(item.get('name', '').split()) != title:
            raise ValueError('Structured/static listing titles disagree')
        links = node.find(tag='a')
        url = links[0].attrs['href']
        price = number(first_text(node, cls='price'))
        period, evidence = price_period(price, title, category)
        row = {'source_id': source_id(url), 'url': url, 'title': title,
               'price': price, 'price_period': period, 'period_evidence': evidence,
               'bedrooms': number(item.get('numberOfBedrooms')),
               'bathrooms': number(item.get('numberOfBathroomsTotal')),
               'latitude': number(item.get('latitude')), 'longitude': None,
               'category': category, 'short_term': category == 'sublets' or bool(re.search(
                   r'short.term|month.to.month|sublet|sublease|lease takeover', title, re.I)),
               'sqft': None, 'sqft_scope': 'unknown', 'advertiser_type': 'unknown'}
        try:
            row['longitude'] = float(item['longitude'])
        except (KeyError, TypeError, ValueError):
            pass
        row.update(geography(item.get('address', {}).get('addressLocality', ''),
                             first_text(node, cls='location')))
        listings.append(row)
    # Static pages currently have no independently verified total/pagination contract.
    return listings


def parse_detail(html):
    root = Tree(html).root
    item = structured(root, 'ld_posting_data')
    title = first_text(root, id='titletextonly')
    if not title:
        raise ValueError('Listing title missing; removed/challenged page')
    attrs = ' '.join(n.text() for n in root.find(cls='attrgroup'))
    housing = first_text(root, cls='housing')
    sqft = re.search(r'([\d,]+)\s*(?:ft2|sq\s*ft)', housing + ' ' + attrs, re.I)
    room = bool(re.search(r'\b(?:private|shared) room\b', attrs, re.I))
    data = {'title': title, 'canonical_post_id': None,
            'postal_code': item.get('address', {}).get('postalCode') or None,
            'sqft': number(sqft[1]) if sqft else None,
            'sqft_scope': 'unknown' if room else 'dwelling',
            'housing_type': next((t for t in ['apartment', 'condo', 'house', 'townhouse',
                 'duplex', 'cottage/cabin', 'manufactured'] if t in attrs.lower()), None),
            'room': room, 'attributes': ' '.join(attrs.split()),
            'posted_at': None, 'updated_at': None,
            'advertiser_type': 'unknown'}
    for n in root.find(cls='postinginfo'):
        match = re.search(r'post id:\s*(\d+)', n.text())
        if match:
            data['canonical_post_id'] = match[1]
        times = n.find(tag='time')
        if times:
            field = 'updated_at' if 'updated:' in n.text().lower() else 'posted_at'
            data[field] = times[0].attrs.get('datetime')
    for key, value in [('bedrooms', item.get('numberOfBedrooms')),
                       ('bathrooms', item.get('numberOfBathroomsTotal'))]:
        data[key] = number(value)
    data['advertised_locality'] = item.get('address', {}).get('addressLocality', '')
    data['map_accuracy_source_value'] = next((n.attrs.get('data-accuracy')
        for n in root.find(id='map')), None)
    return data
