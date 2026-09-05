from pathlib import Path
import hashlib, json, os, sys, tempfile
from io import BytesIO
from PIL import Image

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
data_dir=Path(tempfile.mkdtemp(prefix='layervault-catalog-data-'))
fixtures=Path(tempfile.mkdtemp(prefix='layervault-catalog-fixtures-'))
os.environ['DATA_DIR']=str(data_dir)
os.environ['CATALOG_FIXTURE_DIR']=str(fixtures)

# Official vendor pages are intentionally represented by tiny deterministic
# fixtures; production discovers the same OpenGraph image and caches it locally.
anycubic_v2='https://store.anycubic.com/collections/uv-resin/products/standard-resin-v2'
(fixtures/('official-page-'+hashlib.sha1(anycubic_v2.encode()).hexdigest()+'.txt')).write_text(
    '<html><head><meta property="og:image" content="https://cdn.example.test/anycubic-standard-v2.png"></head></html>',encoding='utf-8')
image_buf=BytesIO(); Image.new('RGB',(48,64),'#d0d8dc').save(image_buf,format='PNG')
(fixtures/('official-image-'+hashlib.sha1(anycubic_v2.encode()).hexdigest()+'.png')).write_bytes(image_buf.getvalue())
anycubic_16k='https://store.anycubic.com/products/16k-standard-resin'
(fixtures/('official-page-'+hashlib.sha1(anycubic_16k.encode()).hexdigest()+'.txt')).write_text(
    '<meta property="og:image" content="https://cdn.example.test/anycubic-16k-bottle.png">',encoding='utf-8')
(fixtures/('official-image-'+hashlib.sha1(anycubic_16k.encode()).hexdigest()+'.png')).write_bytes(image_buf.getvalue())

# SpoolmanDB grouped source fixture
(fixtures/'spoolman-filaments.json').write_text(json.dumps({
    'manufacturer':'TestCo',
    'filaments':[{
        'name':'PLA Pro {color_name}','material':'PLA','density':1.24,
        'weights':[{'weight':1000,'spool_weight':210,'spool_type':'plastic'}],
        'diameters':[1.75], 'extruder_temp_range':[205,220], 'bed_temp_range':[50,60],
        'colors':[{'name':'Ocean Blue','hex':'1A73E8'}]
    }]
}),encoding='utf-8')

# Open Resin Alliance DragonFruit material fixture
ora_path='materials/elegoo/saturn-4-ultra-16k.json'
(fixtures/'ora-tree-df-plugin-sirayatech.json').write_text(json.dumps({'tree':[{'path':ora_path,'type':'blob'}]}),encoding='utf-8')
ora_key='ora-file-'+hashlib.sha1(f'df-plugin-sirayatech:{ora_path}'.encode()).hexdigest()+'.json'
(fixtures/ora_key).write_text(json.dumps([{
    'templateId':'siraya-fast-grey-test','brand':'Siraya Tech','name':'Fast ABS-Like Grey','resinFamily':'Fast ABS-Like',
    'bottleCapacityMl':1000,'bottlePrice':34.99,'currencyCode':'GBP','layerHeightMm':0.05,
    'normalExposureSec':2.2,'bottomExposureSec':28,'bottomLayerCount':5,'transitionLayerCount':5,
    'liftDistanceMm':3,'liftDistance2Mm':4,'liftSpeedMmMin':60,'liftSpeed2MmMin':180,
    'retractSpeedMmMin':180,'retractSpeed2MmMin':60,
    'bottomLiftDistanceMm':3,'bottomLiftDistance2Mm':4,'bottomLiftSpeedMmMin':45,'bottomLiftSpeed2MmMin':120,
    'bottomRetractSpeedMmMin':150,'bottomRetractSpeed2MmMin':60,'lightOffDelaySec':0.5,
    'waitTimeBeforeCureSec':0.8,'waitTimeAfterCureSec':0.5,'waitTimeAfterLiftSec':0.3,
    'projectorPwmPercent':100,'minimumAaAlphaPercent':20
}]),encoding='utf-8')

from fastapi.testclient import TestClient
from app.main import app, init_db
from app import catalog as catalog_module
c=TestClient(app)

for brand,name,kind in (
    ('Bambu Lab','PLA Basic','Filament'),('Prusament','PLA Galaxy Black','Filament'),
    ('Anycubic','PLA Basic','Filament'),('Deeplee','Rapid PLA+','Filament'),
    ('Anycubic','Standard Resin V2','Resin'),('ELEGOO','Water-Washable Resin','Resin'),
    ('SUNLU','Standard Resin','Resin'),
):
    assert catalog_module._official_material(brand,name,name,kind), (brand,name)
assert catalog_module._official_material('Anycubic','16K Standard Resin','High detail','Resin')['url'].endswith('/16k-standard-resin')
assert catalog_module._official_material('Anycubic','8K Standard Resin','High detail','Resin') is None

# Stale cache remains usable if an upstream refresh fails.
stale=(data_dir/'catalog-cache'/'stale-test.cache'); stale.parent.mkdir(parents=True,exist_ok=True); stale.write_text('cached fallback',encoding='utf-8')
orig_client=catalog_module.httpx.Client
catalog_module.httpx.Client=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('offline'))
try:
    assert catalog_module._fetch_text('stale-test','https://invalid.example.test',ttl=0)=='cached fallback'
finally:
    catalog_module.httpx.Client=orig_client
assert c.get('/health').json()['version']=='0.3.29'
providers=c.get('/api/catalog/providers').json()
assert {p['id'] for p in providers}=={'spoolman','openresin','manufacturer_resin'}
assert c.get('/api/catalog/search',params={'q':'PETG blue','provider':'openprinttag'}).status_code==400

# The manufacturer index is offline-safe and covers broad resin discovery
# independently of printer-specific community profiles.
official=c.get('/api/catalog/search',params={'q':'Anycubic ABS-Like','provider':'manufacturer_resin'}).json()
assert len(official['results']) >= 4 and all(x['provider']=='manufacturer_resin' for x in official['results'])
official_item=c.get('/api/catalog/item',params={'provider':'manufacturer_resin','key':official['results'][0]['key']}).json()
assert official_item['brand']=='Anycubic' and official_item['material_payload']['unit']=='ml'
official_import=c.post('/api/catalog/import',json={'provider':'manufacturer_resin','key':official_item['key'],'create_profile':False,'material_overrides':{'color':'Grey'}})
assert official_import.status_code==200,official_import.text
assert official_import.json()['material']['source_provider']=='manufacturer_resin'

# Major-vendor records retain both official product artwork and their separate
# colour chip, plus normalized technical/handling metadata.
v2_search=c.get('/api/catalog/search',params={'q':'Anycubic Standard Resin V2','provider':'manufacturer_resin'}).json()
v2_hit=next(x for x in v2_search['results'] if x['name']=='Standard Resin V2')
assert v2_hit['has_image'] is True
v2=c.get('/api/catalog/item',params={'provider':'manufacturer_resin','key':v2_hit['key']}).json()
assert v2['specs']['wavelength_nm']=='365–405' and v2['material_payload']['source_image_url']==anycubic_v2
catalog_image=c.get('/api/catalog/image',params={'provider':'manufacturer_resin','key':v2_hit['key']})
assert catalog_image.status_code==200 and catalog_image.headers['content-type']=='image/png'
v2_import=c.post('/api/catalog/import',json={'provider':'manufacturer_resin','key':v2_hit['key'],'create_profile':False,'material_overrides':{'color':'Grey','color_hex':'#8A8D91'}}).json()['material']
assert v2_import['has_source_image'] is True and v2_import['color_hex']=='#8A8D91' and v2_import['specs']['normal_exposure_s']=='2.5–3'
assert c.get(f"/api/materials/{v2_import['id']}/image").status_code==200
manual_16k=c.post('/api/materials',json={'name':'Anycubic · 16K Standard Resin','kind':'Resin','brand':'Anycubic','material':'High detail'}).json()
assert manual_16k['source_image_url']==anycubic_16k and manual_16k['specs']['hardness']=='83–85 HD'
manual_image=c.get(f"/api/materials/{manual_16k['id']}/image")
assert manual_image.status_code==200, manual_image.text

# Owned resin printer enables printer-specific ORA lookup.
printer=c.post('/api/printers',json={'name':'Saturn 4 Ultra 16K','technology':'MSLA / Resin','manufacturer':'Elegoo','model':'Saturn 4 Ultra 16K'}).json()

sp=c.get('/api/catalog/search',params={'q':'TestCo PLA','provider':'spoolman'}).json()
assert sp['results'] and sp['results'][0]['provider']=='spoolman'
sp_item=c.get('/api/catalog/item',params={'provider':'spoolman','key':sp['results'][0]['key']}).json()
assert sp_item['settings']['nozzle_temp_c']==212.5 and sp_item['settings']['bed_temp_c']==55.0
assert sp_item['specs']['density_g_cm3']==1.24 and sp_item['specs']['diameter_mm']==1.75
assert sp_item['specs']['nozzle_temp_c']==[205,220] and sp_item['specs']['empty_spool_weight_g']==210
imp=c.post('/api/catalog/import',json={'provider':'spoolman','key':sp_item['key'],'create_profile':True,'material_overrides':{'location':'Rack A','purchase_price':24.5}})
assert imp.status_code==200, imp.text
sp_imp=imp.json(); assert sp_imp['material']['source_provider']=='spoolman'; assert sp_imp['profile']['profile_origin']=='Recommended'

# A generic product-page photo is not used for a named filament colour. This
# prevents a green spool from displaying the vendor page's default orange roll.
bambu_green=catalog_module.official_artwork('Bambu Lab','Bambu Green','PLA Basic','Filament','Bambu Green')
assert bambu_green and bambu_green['url']=='' and bambu_green['product_url'].endswith('/pla-basic-filament')
bambu_row=c.post('/api/materials',json={'name':'Bambu Green','kind':'Filament','brand':'Bambu Lab','material':'PLA Basic','color':'Bambu Green','color_hex':'#00AE42'}).json()
assert bambu_row['source_image_url']=='' and bambu_row['product_url'].endswith('/pla-basic-filament')

ora=c.get('/api/catalog/search',params={'q':'Fast ABS','provider':'openresin','printer_id':printer['id']}).json()
assert ora['results'], ora
ora_item=c.get('/api/catalog/item',params={'provider':'openresin','key':ora['results'][0]['key'],'printer_id':printer['id']}).json()
assert ora_item['settings']['normal_exposure_s']==2.2
assert ora_item['settings']['lift_speed_mms']==1.0
assert ora_item['settings']['lift_speed_2_mms']==3.0
assert ora_item['settings']['bottom_lift_speed_mms']==0.75
imp3=c.post('/api/catalog/import',json={'provider':'openresin','key':ora_item['key'],'printer_id':printer['id'],'create_profile':True,'material_overrides':{'batch_lot':'R26-A'}})
assert imp3.status_code==200,imp3.text
ora_imp=imp3.json(); assert ora_imp['material']['unit']=='ml'; assert ora_imp['material']['batch_lot']=='R26-A'
assert ora_imp['profile']['printer_id']==printer['id']; assert ora_imp['profile']['source_provider']=='openresin'; assert ora_imp['profile']['settings']['normal_exposure_s']==2.2

# Multiple physical stock units may legitimately come from the same product source.
again=c.post('/api/catalog/import',json={'provider':'spoolman','key':sp_item['key'],'create_profile':False,'material_overrides':{'name':'Second physical spool'}})
assert again.status_code==200
materials=c.get('/api/materials').json(); assert len(materials)==7
assert sum(1 for m in materials if m['source_provider']=='spoolman')==2
profiles=c.get('/api/profiles').json(); assert any(p['source_provider']=='openresin' and p['profile_origin']=='Recommended' for p in profiles)

# Upgrade keeps a legacy local record but removes the retired source identity.
legacy=c.post('/api/materials',json={'name':'Legacy local spool','kind':'Filament','material':'PETG','source_provider':'openprinttag','source_key':'old-key'}).json()
init_db()
legacy_after=next(x for x in c.get('/api/materials').json() if x['id']==legacy['id'])
assert legacy_after['source_provider']=='' and legacy_after['source_key']==''

print('LayerVault v0.3.29 material catalogue/provider test: PASS')
