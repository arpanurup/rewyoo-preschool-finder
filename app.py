import re, io, json, time
from urllib.parse import urlparse
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from ddgs import DDGS

st.set_page_config(page_title='Rewyoo Preschool Finder', page_icon='🏫', layout='wide')
FIELDS = ['Preschool Name','Branch Name','Website','Email','Phone Number','Alternate Phone','Full Address','Locality','Pincode','District','State','Country','Preschool Type','Category','Established Year']
CATEGORIES = {
 'Preschool':['preschool','pre school','playschool','play school','nursery school'],
 'Montessori':['montessori'],
 'Daycare + Preschool':['daycare','day care','child care','creche','crèche'],
 'Kindergarten':['kindergarten','lkg','ukg','early learning']
}
HEADERS={'User-Agent':'Mozilla/5.0 (compatible; RewyooPreschoolFinder/1.0; +https://rewyoo.com)'}

def clean(v): return re.sub(r'\s+',' ',str(v or '')).strip()
def norm(v): return re.sub(r'[^a-z0-9]','',str(v or '').lower())
def root_site(url):
 try:
  p=urlparse(url if url.startswith(('http://','https://')) else 'https://'+url)
  return f'{p.scheme}://{p.netloc}'.rstrip('/') if p.netloc else ''
 except Exception: return ''
def established_year(text):
 for pat in [r'(?:established|founded|started|since|est\.?)\s*(?:in\s*)?[:\-]?\s*((?:19|20)\d{2})',r'(?:established|founded)\s+(?:since\s+)?((?:19|20)\d{2})']:
  m=re.search(pat,text,re.I)
  if m and 1950 <= int(m.group(1)) <= 2026: return m.group(1)
 return ''
def jsonld(soup):
 names=[]; addresses=[]; years=[]
 for script in soup.find_all('script',type='application/ld+json'):
  try:
   raw=json.loads(script.string or script.get_text()); items=raw if isinstance(raw,list) else [raw]
   for item in items:
    if not isinstance(item,dict): continue
    if '@graph' in item: items.extend(item['@graph'] if isinstance(item['@graph'],list) else [item['@graph']])
    if item.get('name'): names.append(clean(item['name']))
    if item.get('foundingDate'):
     m=re.search(r'(?:19|20)\d{2}',str(item['foundingDate']))
     if m: years.append(m.group())
    a=item.get('address')
    if isinstance(a,dict):
     val=clean(', '.join(str(a.get(k,'')) for k in ['streetAddress','addressLocality','addressRegion','postalCode'] if a.get(k)))
     if val: addresses.append(val)
    elif isinstance(a,str): addresses.append(clean(a))
  except Exception: pass
 return (names[0] if names else '',addresses[0] if addresses else '',years[0] if years else '')
def extract_page(url,title,snippet):
 try:
  r=requests.get(url,headers=HEADERS,timeout=12,allow_redirects=True)
  if r.status_code>=400 or ('html' not in r.headers.get('Content-Type','') and '<html' not in r.text[:500].lower()): return None
  soup=BeautifulSoup(r.text,'html.parser')
  for x in soup(['script','style','noscript','svg','header','footer']): x.decompose()
  text=clean(soup.get_text(' ',strip=True))
  if len(text)<80: return None
  jname,jaddr,jyear=jsonld(soup)
  h1=clean(soup.find('h1').get_text(' ',strip=True) if soup.find('h1') else '')
  name=jname or h1 or clean(soup.title.get_text(' ',strip=True) if soup.title else title).split('|')[0].split(' - ')[0]
  emails=[e for e in sorted(set(re.findall(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}',text,re.I))) if not any(x in e.lower() for x in ['example.com','domain.com','wixpress.com'])]
  phones=[]
  for value in re.findall(r'(?:\+91[\s-]?)?[6-9]\d{9}',text):
   d=re.sub(r'\D','',value); d=d[2:] if d.startswith('91') and len(d)==12 else d
   if len(d)==10 and d not in phones: phones.append(d)
  for a in soup.select('a[href^="tel:"]'):
   d=re.sub(r'\D','',a.get('href','')); d=d[2:] if d.startswith('91') and len(d)==12 else d
   if len(d)==10 and d not in phones: phones.insert(0,d)
  addresses=[]
  for tag in soup.find_all('address'):
   v=clean(tag.get_text(' ',strip=True))
   if len(v)>18: addresses.append(v)
  for tag in soup.select('[itemprop="address"],[class*="address"],[id*="address"]'):
   v=clean(tag.get_text(' ',strip=True))
   if 20<len(v)<350: addresses.append(v)
  address=jaddr or (addresses[0] if addresses else '')
  pin=re.search(r'\b[1-9][0-9]{5}\b',address+' '+text)
  return {'name':name[:150],'website':root_site(r.url),'email':emails[0] if emails else '', 'phones':phones[:2], 'address':address,'pincode':pin.group() if pin else '', 'year':jyear or established_year(text),'text':(title+' '+snippet+' '+text[:5000]).lower()}
 except Exception: return None
def build_queries(locality,city,district,state,categories):
 place=', '.join(x for x in [locality,city,district,state,'India'] if x)
 words=[]
 for c in categories: words.extend(CATEGORIES[c])
 if not words: words=['preschool','playschool','montessori','kindergarten','daycare']
 q=[]
 for w in words:
  q += [f'{w} in {place}',f'{w} near {locality or city or district} {city} {state}']
 q += [f'preschools list {place} contact address',f'best playschools {place} official website',f'Montessori preschool {place} phone address']
 return list(dict.fromkeys(x.strip() for x in q if x.strip()))
def collect(locality,city,district,state,categories,limit,progress):
 terms=[x.lower() for x in [locality,city,district,state] if x]
 queries=build_queries(locality,city,district,state,categories); found={}; errors=[]
 for qi,q in enumerate(queries):
  progress(qi,len(queries),f'Searching: {q}')
  try:
   with DDGS() as ddgs: results=list(ddgs.text(q,max_results=12))
  except Exception as e:
   errors.append(f'{q}: {type(e).__name__}: {e}'); time.sleep(1); continue
  for item in results:
   url=item.get('href') or item.get('url') or ''
   if not url.startswith(('http://','https://')): continue
   host=urlparse(url).netloc.lower()
   if any(x in host for x in ['facebook.com','instagram.com','youtube.com','linkedin.com','justdial.com']): continue
   title=clean(item.get('title','')); snippet=clean(item.get('body','') or item.get('description',''))
   combined=(title+' '+snippet+' '+url).lower()
   if not any(w in combined for w in ['preschool','pre school','playschool','play school','montessori','kindergarten','nursery','daycare','day care']): continue
   page=extract_page(url,title,snippet)
   if not page: continue
   local_hit=any(t in combined for t in terms)
   preschool_hit=any(w in page['text'] for w in ['preschool','pre school','playschool','play school','montessori','kindergarten','nursery','daycare','day care','early learning'])
   category_hit=any(any(w in page['text'] for w in CATEGORIES[c]) for c in categories)
   if not preschool_hit or not (local_hit or any(t in page['text'] for t in terms)) or (categories and not category_hit): continue
   branch=next((x for x in [locality,city,district] if x and x.lower() in (title+' '+snippet).lower()),'')
   rec={'Preschool Name':page['name'],'Branch Name':branch,'Website':page['website'],'Email':page['email'],'Phone Number':page['phones'][0] if page['phones'] else '', 'Alternate Phone':page['phones'][1] if len(page['phones'])>1 else '', 'Full Address':page['address'],'Locality':locality,'Pincode':page['pincode'],'District':district,'State':state,'Country':'India','Preschool Type':', '.join(c for c,ws in CATEGORIES.items() if any(w in page['text'] for w in ws)) or 'Preschool','Category':', '.join(categories),'Established Year':page['year']}
   key=norm(rec['Website'] or rec['Preschool Name'])+'|'+norm(rec['Phone Number'])+'|'+norm(rec['Full Address'])
   if key.strip('|') and key not in found: found[key]=rec
   if len(found)>=limit: break
  progress(qi+1,len(queries),f'Completed {qi+1} of {len(queries)} searches')
  if len(found)>=limit: break
  time.sleep(.5)
 return list(found.values()),errors

def excel_bytes(records):
 out=io.BytesIO(); df=pd.DataFrame(records,columns=FIELDS)
 with pd.ExcelWriter(out,engine='openpyxl') as writer:
  df.to_excel(writer,index=False,sheet_name='Preschool Database'); ws=writer.sheets['Preschool Database']; ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
  for col in ws.columns: ws.column_dimensions[col[0].column_letter].width=min(max(max(len(str(c.value or '')) for c in col)+2,14),42)
 out.seek(0); return out.getvalue()

if 'records' not in st.session_state: st.session_state.records=[]
if 'history' not in st.session_state: st.session_state.history=[]
st.title('Rewyoo Preschool Finder')
st.caption('Search public preschool information across India and export branch-level records to Excel.')
with st.sidebar:
 st.subheader('Search location'); locality=st.text_input('Locality / Area',placeholder='Example: Whitefield'); city=st.text_input('City',placeholder='Example: Bengaluru'); district=st.text_input('District',placeholder='Example: Bengaluru Urban'); state=st.text_input('State',value='Karnataka')
 st.subheader('Preschool categories'); categories=st.multiselect('Select categories',list(CATEGORIES),default=list(CATEGORIES))
 limit=st.slider('Maximum records to collect',5,500,100,5); start=st.button('Start preschool search',type='primary',use_container_width=True); clear=st.button('Clear current results',use_container_width=True)
if clear: st.session_state.records=[]; st.rerun()
a,b,c=st.columns(3); a.metric('Records in current results',len(st.session_state.records)); b.metric('Searches in this session',len(st.session_state.history)); c.metric('Target records',limit)
if start:
 if not any([locality.strip(),city.strip(),district.strip(),state.strip()]): st.error('Enter at least one location field.')
 elif not categories: st.error('Select at least one category.')
 else:
  status=st.empty(); bar=st.progress(0)
  def progress(done,total,msg): status.info(msg); bar.progress(min(int(done/max(total,1)*100),100))
  with st.spinner('Searching public results and checking preschool pages...'): records,errors=collect(locality.strip(),city.strip(),district.strip(),state.strip(),categories,limit,progress)
  st.session_state.records=records; st.session_state.history.insert(0,{'Location':', '.join(x for x in [locality,city,district,state] if x),'Records Found':len(records),'Date':time.strftime('%Y-%m-%d %H:%M:%S')})
  bar.progress(100)
  if records: st.success(f'Search finished. {len(records)} preschool branch records collected.')
  elif errors: st.error('No records collected because search requests failed. Review the errors below.')
  else: st.warning('Search completed but no matching preschool pages were collected. Try a broader city or district search.')
  if errors:
   with st.expander(f'Search service errors ({len(errors)})'):
    for err in errors[:10]: st.code(err)
if st.session_state.records:
 st.subheader('Extracted Preschool Database'); st.dataframe(pd.DataFrame(st.session_state.records,columns=FIELDS),use_container_width=True,hide_index=True)
 st.download_button('Download Excel',data=excel_bytes(st.session_state.records),file_name=f'rewyoo_preschools_{time.strftime("%Y%m%d_%H%M%S")}.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',type='primary')
else: st.info('No preschool records are loaded yet. Enter a location and start a search.')
if st.session_state.history: st.subheader('Search History'); st.dataframe(pd.DataFrame(st.session_state.history),use_container_width=True,hide_index=True)
with st.expander('Coverage and data notes'):
 st.write('This app searches publicly accessible web results and preschool websites. It does not access a complete official national preschool registry. The record limit is a target, not a guarantee. Some websites block automated requests or do not publish contact details. Established Year is captured only when a public page or structured website data states a year; otherwise it remains blank. Results and history are held in the active Streamlit session and may not persist after the app restarts.')
