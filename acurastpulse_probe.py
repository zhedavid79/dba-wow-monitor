from __future__ import annotations

import json, re
import requests
from bs4 import BeautifulSoup

URL='https://www.acurastpulse.com/phones'
H={'User-Agent':'Mozilla/5.0','Accept-Language':'en-US,en;q=0.9'}

r=requests.get(URL,headers=H,timeout=30)
r.raise_for_status()
soup=BeautifulSoup(r.text,'html.parser')
links=[]
for a in soup.find_all('a',href=True):
    href=a.get('href','')
    text=' '.join(a.stripped_strings)
    if re.fullmatch(r'/phones/\d+',href):
        links.append({'href':href,'text':text[:500]})

print(json.dumps({
    'status':r.status_code,
    'bytes':len(r.content),
    'phone_links':len(links),
    'sample':links[:12],
    's20fe':[x for x in links if 's20 fe' in x['text'].lower()],
    'oneplus8t':[x for x in links if 'oneplus 8t' in x['text'].lower()],
    'pagination_hrefs':sorted(set(a.get('href') for a in soup.find_all('a',href=True) if 'page' in a.get('href','').lower()))[:30],
    'next_data': bool(soup.find('script',id='__NEXT_DATA__')),
},ensure_ascii=False,indent=2))
