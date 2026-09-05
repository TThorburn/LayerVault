from pathlib import Path
import hashlib, json, os, sys, tempfile
from io import BytesIO

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
dockerignore=(root/'.dockerignore').read_text(encoding='utf-8')
assert '!third_party/dragonfruit/plugins/anycubic/**' in dockerignore
assert '!third_party/dragonfruit/plugins/elegoo/**' in dockerignore
assert '!third_party/dragonfruit/plugins/athena/**' in dockerignore
assert '!third_party/uvtools/PrusaSlicer/printer/**' in dockerignore
data_dir=Path(tempfile.mkdtemp(prefix='layervault-printer-catalog-data-'))
fixtures=Path(tempfile.mkdtemp(prefix='layervault-printer-catalog-fixtures-'))
os.environ['DATA_DIR']=str(data_dir)
os.environ['PRINTER_CATALOG_FIXTURE_DIR']=str(fixtures)
os.environ['CATALOG_FIXTURE_DIR']=str(fixtures)

orca_path='resources/profiles/Creality/machine/Creality K1C 0.4 nozzle.json'
cover_path='resources/profiles/Creality/machine/Creality K1C_cover.png'
(fixtures/'orca-tree.json').write_text(json.dumps({'tree':[{'path':orca_path,'type':'blob'},{'path':cover_path,'type':'blob'}]}),encoding='utf-8')
(fixtures/('orca-file-'+hashlib.sha1(orca_path.encode()).hexdigest()+'.json')).write_text(json.dumps({
    'type':'machine','name':'Creality K1C 0.4 nozzle','printer_model':'Creality K1C',
    'printable_area':['0x0','220x0','220x220','0x220'],'printable_height':'250',
    'nozzle_diameter':['0.4'],'printer_structure':'CoreXY','extruder_type':'Direct Drive','gcode_flavor':'klipper'
}),encoding='utf-8')
# The image fixture key is based on source path rather than URL.
from PIL import Image
buf=BytesIO(); Image.new('RGB',(80,80),'white').save(buf,format='PNG')
(fixtures/'orca_resources_profiles_Creality_machine_Creality_K1C_0.4_nozzle.json.png').write_bytes(buf.getvalue())
(fixtures/'uvtools_PrusaSlicer_printer_Nova3D_Bene6.ini.png').write_bytes(buf.getvalue())

phrozen_page='https://us.phrozen3d.com/products/sonic-mini-8k'
(fixtures/('printer-official-page-'+hashlib.sha1(phrozen_page.encode()).hexdigest()+'.txt')).write_text(
    '<meta property="og:image" content="https://cdn.shopify.com/s/files/phrozen-sonic-mini-8k.png">',encoding='utf-8')
(fixtures/('official-printer-'+hashlib.sha1(phrozen_page.encode()).hexdigest()+'.png')).write_bytes(buf.getvalue())

uv_path='PrusaSlicer/printer/Elegoo Saturn 4 Ultra 12K.ini'
(fixtures/'uvtools-tree.json').write_text(json.dumps({'tree':[{'path':uv_path,'type':'blob'}]}),encoding='utf-8')
(fixtures/('uvtools-file-'+hashlib.sha1(uv_path.encode()).hexdigest()+'.ini')).write_text('''
bed_shape = 0x0,218.88x0,218.88x122.88,0x122.88
display_height = 122.88
display_pixels_x = 11520
display_pixels_y = 5120
display_width = 218.88
max_print_height = 220
printer_technology = SLA
display_orientation = landscape
sla_archive_format = SL1
min_exposure_time = 1
max_exposure_time = 120
''',encoding='utf-8')

from fastapi.testclient import TestClient
from app.main import app
from app import printer_catalog as pc
c=TestClient(app)
assert c.get('/health').json()['version']=='0.3.29'
assert {x['id'] for x in c.get('/api/printer-catalog/providers').json()}=={'orca','uvtools','dragonfruit'}

# Records describing the same physical model collapse across databases. The
# artwork-bearing record wins while useful dimensions from the other survive.
merged=pc._merge_catalogue_results([
    {'provider_id':'uvtools','key':'uv-photon','manufacturer':'Anycubic','model':'Photon M3','technology':'Resin','build_z':180,'image_url':''},
    {'provider_id':'dragonfruit','key':'df-photon','manufacturer':'Anycubic','model':'Anycubic Photon M3','technology':'Resin','build_x':163.84,'image_url':'dragonfruit://df-photon'},
])
assert len(merged)==1 and merged[0]['provider_id']=='dragonfruit'
assert merged[0]['image_url']=='dragonfruit://df-photon' and merged[0]['build_z']==180
assert set(merged[0]['source_providers'])=={'uvtools','dragonfruit'} and merged[0]['merged_source_count']==2

# Cross-database aliases collapse the exact duplicate shown in the UI while
# retaining DragonFruit's artwork and UVtools' machine specifications.
x6k=pc._merge_catalogue_results([
    {'provider_id':'uvtools','key':'uv-x6k','manufacturer':'Anycubic','model':'Photon Mono X 6K','technology':'Resin','build_z':245,'image_url':''},
    {'provider_id':'dragonfruit','key':'df-x6k','manufacturer':'Anycubic','model':'Photon Mono X 6K / M3 Plus','technology':'Resin','build_x':198.15,'image_url':'dragonfruit://df-x6k'},
])
assert len(x6k)==1 and x6k[0]['provider_id']=='dragonfruit'
assert x6k[0]['image_url']=='dragonfruit://df-x6k' and x6k[0]['build_z']==245

fdm=c.get('/api/printer-catalog/search',params={'q':'K1C','provider':'orca','technology':'fdm'}).json()
assert fdm['results'], fdm
k1=fdm['results'][0]
assert k1['manufacturer']=='Creality' and k1['model']=='Creality K1C'
assert [k1['build_x'],k1['build_y'],k1['build_z']]==[220.0,220.0,250.0]
assert k1['nozzle_mm']==0.4 and k1['image_url']
img=c.get('/api/printer-catalog/image',params={'provider':'orca','key':k1['key']})
assert img.status_code==200 and img.headers['content-type'].startswith('image/png') and len(img.content)>100
imp=c.post('/api/printer-catalog/import',json={'provider':'orca','key':k1['key'],'overrides':{'name':'Workshop K1C','serial_number':'K1C-001','location':'Bench'}})
assert imp.status_code==200,imp.text
owned=imp.json()['printer']
assert owned['source_provider']=='orca' and owned['source_license']=='AGPL-3.0'
assert owned['name']=='Workshop K1C' and owned['build_x']==220 and owned['nozzle_options']==[0.4]
assert c.get(f"/api/printers/{owned['id']}/image").status_code==200

res=c.get('/api/printer-catalog/search',params={'q':'Saturn 4 Ultra','provider':'uvtools','technology':'resin'}).json()
assert res['results'], res
sat=res['results'][0]
assert sat['manufacturer']=='Elegoo' and sat['model']=='Saturn 4 Ultra 12K'
assert [sat['build_x'],sat['build_y'],sat['build_z']]==[218.88,122.88,220.0]
assert [sat['resolution_x'],sat['resolution_y']]==[11520,5120]
assert round(sat['xy_resolution_x_um'],2)==19.0 and round(sat['xy_resolution_y_um'],2)==24.0
imp2=c.post('/api/printer-catalog/import',json={'provider':'uvtools','key':sat['key'],'overrides':{'name':'My Saturn','purchase_price':399}})
assert imp2.status_code==200,imp2.text
owned2=imp2.json()['printer']
assert owned2['source_provider']=='uvtools' and owned2['resolution_x']==11520 and owned2['screen_width_mm']==218.88
assert owned2['purchase_price']==399

# Bundled DragonFruit plugin presets supply local resin-printer artwork without a network call.
dragon=c.get('/api/printer-catalog/search',params={'q':'Photon M3','provider':'dragonfruit','technology':'resin'}).json()
assert dragon['results'], dragon
photon=next(item for item in dragon['results'] if item['model']=='Photon M3')
assert [photon['build_x'],photon['build_y'],photon['build_z']]==[163.84,102.4,180.0]
assert photon['source_license'].startswith('MIT') and photon['image_url'].startswith('dragonfruit://')
dragon_img=c.get('/api/printer-catalog/image',params={'provider':'dragonfruit','key':photon['key']})
assert dragon_img.status_code==200 and dragon_img.headers['content-type'].startswith('image/') and len(dragon_img.content)>100
imp3=c.post('/api/printer-catalog/import',json={'provider':'dragonfruit','key':photon['key'],'overrides':{'name':'Resin bench'}})
assert imp3.status_code==200,imp3.text
owned3=imp3.json()['printer']
assert owned3['source_provider']=='dragonfruit'
assert c.get(f"/api/printers/{owned3['id']}/image").status_code==200

# UVtools-only result cards are decorated from an exact retained DragonFruit
# match, and selected popular machines can fall back to exact official artwork.
uv_x6k=c.get('/api/printer-catalog/search',params={'q':'Photon Mono X 6K','provider':'uvtools','technology':'resin'}).json()['results'][0]
assert uv_x6k['image_url'].startswith('dragonfruit://')
assert c.get('/api/printer-catalog/image',params={'provider':'uvtools','key':uv_x6k['key']}).status_code==200
all_x6k=c.get('/api/printer-catalog/search',params={'q':'Photon Mono X 6K','provider':'all','technology':'resin'}).json()['results']
assert len([x for x in all_x6k if pc._printer_identity(x)=='anycubic:photonmonox6km3plus'])==1
phrozen=c.get('/api/printer-catalog/search',params={'q':'Sonic Mini 8K','provider':'uvtools','technology':'resin'}).json()['results']
mini=next(x for x in phrozen if x['model']=='Sonic Mini 8K')
assert mini['image_url']==phrozen_page
assert c.get('/api/printer-catalog/image',params={'provider':'uvtools','key':mini['key']}).status_code==200

# Exact artwork coverage for the previously blank UVtools resin families.
# These checks deliberately use model names as shipped by the retained INI
# files so punctuation and UVtools' Prusa naming quirk remain covered.
artwork_coverage={
    'Nova3D':['Bene4 Mono','Bene4','Bene5','Bene6','Elfin','Elfin2 Mono SE','Elfin2','Elfin3 Mini','Whale','Whale2','Whale3 Pro'],
    'Wanhao':['CGR Mini Mono','CGR Mono','D7','D8'],
    'UVtools':['Prusa SL1','Prusa SL1S SPEED'],
    'Elegoo':['Mars C','Mars','Saturn'],
    'Creality':['Halot Lite CL-89L','Halot Mage CL-103L','Halot Mage Pro CL-103','Halot Max CL-133','Halot One CL-60','Halot One Plus CL-79','Halot One Pro CL-70','Halot Ray CL925','Halot Sky CL-89','Halot Sky Plus CL-92','LD-002H','LD-002R','LD-006'],
    'EPAX':['DX1 PRO','DX10 Pro 5K','DX10 Pro 8K','E10 5K','E10 8K','E10 Mono','E6 Mono','X1','X1 4KS','X10','X10 4K Mono','X10 5K','X133 4K Mono','X133 6K','X156 4K Color','X1K 2K Mono'],
    'Longer':['Orange 10','Orange 120','Orange 30','Orange 4K'],
    'Phrozen':['Shuffle','Shuffle 4K','Shuffle Lite','Shuffle XL','Shuffle XL Lite','Sonic','Sonic 4K','Sonic Mega 8K','Sonic Mighty 4K','Sonic Mini','Sonic Mini 4K','Transform'],
    'Qidi':['I-Box Mono','S-Box','Shadow5.5','Shadow6.0 Pro'],
}
for maker, models in artwork_coverage.items():
    for model in models:
        artwork=pc.local_image_for_printer(maker,model)
        assert artwork and artwork.get('image_url'), (maker,model)

# Every visible result from the four expanded brand searches now has artwork.
# The historic Shuffle 16 profile is excluded because Phrozen does not list it
# as a released product and showing a guessed model photograph would be worse
# than omitting the unverified slicing preset.
for brand in ('EPAX','Longer','Phrozen','Qidi'):
    rows=pc.search(brand,'all','all',200)['results']
    assert rows and all(row.get('image_url') for row in rows), (brand,rows)
assert not any(row['model']=='Shuffle 16' for row in pc.search('Phrozen','uvtools','resin',200)['results'])

bene6=pc._uv_detail('PrusaSlicer/printer/Nova3D Bene6.ini')
assert bene6['image_url'].startswith('https://store.nova3dp.com/')
bene6_img=c.get('/api/printer-catalog/image',params={'provider':'uvtools','key':bene6['key']})
assert bene6_img.status_code==200 and bene6_img.headers['content-type'].startswith('image/')
elfin2=pc._uv_detail('PrusaSlicer/printer/Nova3D Elfin2.ini')
assert elfin2['image_url']=='printer-art://nova3d-elfin2.png'
elfin2_img=c.get('/api/printer-catalog/image',params={'provider':'uvtools','key':elfin2['key']})
assert elfin2_img.status_code==200 and len(elfin2_img.content)>1000

# Orca's fdm_* JSON files are inheritance templates, not separate Snapmaker
# products. Real variants remain searchable and retain their local covers.
snapmaker=pc._search_orca('Snapmaker',50)
assert snapmaker and all(not Path(row['key']).stem.casefold().startswith('fdm_') for row in snapmaker)
assert any(row.get('image_url') for row in snapmaker)
try:
    pc._orca_detail('resources/profiles/Snapmaker/machine/fdm_a250.json')
    raise AssertionError('Snapmaker inheritance profile was exposed as a printer')
except KeyError:
    pass

# Existing local copies remain editable while source provenance is preserved.
patch=c.patch(f"/api/printers/{owned2['id']}",json={'build_z':221,'notes':'Measured revision'}).json()
assert patch['build_z']==221 and patch['source_provider']=='uvtools' and patch['notes']=='Measured revision'

# Cached provider data remains usable if refresh fails.
stale=(data_dir/'catalog-cache'/'printers'/'stale-printer.cache'); stale.parent.mkdir(parents=True,exist_ok=True); stale.write_text('cached printer fallback',encoding='utf-8')
orig=pc.httpx.Client
pc.httpx.Client=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('offline'))
try:
    assert pc._fetch_text('stale-printer','https://invalid.example.test',ttl=0)=='cached printer fallback'
finally:
    pc.httpx.Client=orig

print('LayerVault v0.3.29 printer catalogue/provider test: PASS')
