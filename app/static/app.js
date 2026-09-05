let THREE = null;
let OrbitControls = null;
let STLLoader = null;
let OBJLoader = null;
let ThreeMFLoader = null;
let STLExporter = null;
let threeEnginePromise = null;
let TransformControls = null;
let BufferGeometryUtils = null;
let ManifoldEngine = null;
let workshopEnginePromise = null;

async function ensureThreeEngine() {
  if (THREE && OrbitControls && STLLoader && OBJLoader && ThreeMFLoader && STLExporter) return true;
  if (!threeEnginePromise) {
    threeEnginePromise = Promise.all([
      import('three'),
      import('three/addons/controls/OrbitControls.js'),
      import('three/addons/loaders/STLLoader.js'),
      import('three/addons/loaders/OBJLoader.js'),
      import('three/addons/loaders/3MFLoader.js'),
      import('three/addons/exporters/STLExporter.js')
    ]).then(([three, controls, stl, obj, threeMF, exporter]) => {
      THREE = three;
      OrbitControls = controls.OrbitControls;
      STLLoader = stl.STLLoader;
      OBJLoader = obj.OBJLoader;
      ThreeMFLoader = threeMF.ThreeMFLoader;
      STLExporter = exporter.STLExporter;
      return true;
    }).catch(err => {
      threeEnginePromise = null;
      throw new Error(`3D viewer engine failed to load: ${err?.message || err}`);
    });
  }
  return threeEnginePromise;
}

async function ensureWorkshopEngine() {
  await ensureThreeEngine();
  if (TransformControls && BufferGeometryUtils && ManifoldEngine) return true;
  if (!workshopEnginePromise) {
    workshopEnginePromise = Promise.all([
      import('three/addons/controls/TransformControls.js'),
      import('three/addons/utils/BufferGeometryUtils.js'),
      import('manifold-3d')
    ]).then(async ([transform, geometryUtils, manifold]) => {
      TransformControls = transform.TransformControls;
      BufferGeometryUtils = geometryUtils;
      ManifoldEngine = await manifold.default({locateFile:()=>'/static/vendor/manifold/manifold.wasm'});
      ManifoldEngine.setup();
      return true;
    }).catch(err => {
      workshopEnginePromise = null;
      throw new Error(`Workshop tools failed to load: ${err?.message || err}`);
    });
  }
  return workshopEnginePromise;
}

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const content = $('#content');

function safeStorageGet(key, fallback = '') {
  try { return window.localStorage?.getItem(key) ?? fallback; }
  catch { return fallback; }
}
function safeStorageSet(key, value) {
  try { window.localStorage?.setItem(key, value); return true; }
  catch { return false; }
}

const THEMES = [
  {id:'frost',name:'Frost',note:'The original airy blue glass'},
  {id:'midnight',name:'Midnight',note:'Deep navy glass for low light'},
  {id:'aurora',name:'Aurora',note:'Teal, violet and electric blue'},
  {id:'sunset',name:'Sunset',note:'Warm coral and berry highlights'},
  {id:'ocean',name:'Ocean',note:'Calm cyan and coastal blue glass'},
  {id:'orchid',name:'Orchid',note:'Playful lilac and pink glass'},
  {id:'forest',name:'Forest',note:'Fresh jade and botanical green'},
  {id:'nebula',name:'Nebula',note:'Cosmic violet and sapphire glass'},
];
function currentTheme(){const value=document.documentElement.dataset.theme||safeStorageGet('layervault-theme','frost');return THEMES.some(x=>x.id===value)?value:'frost';}
function applyTheme(theme,announce=false){
  const next=THEMES.some(x=>x.id===theme)?theme:'frost';
  document.documentElement.dataset.theme=next;
  safeStorageSet('layervault-theme',next);
  const themeColors={midnight:'#090f20',sunset:'#fff4f5',aurora:'#f1fbff',ocean:'#eefbff',orchid:'#fbf4ff',forest:'#f1fbf5',nebula:'#f5f1ff'};
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content',themeColors[next]||'#f3f7ff');
  $$('.theme-option').forEach(button=>{const active=button.dataset.themeChoice===next;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
  if(announce)toast(`${THEMES.find(x=>x.id===next)?.name||'Frost'} theme applied`);
}
applyTheme(currentTheme());

const PREVIEWABLE = new Set(['.stl', '.obj', '.3mf']);
const state = {
  page: 'dashboard',
  models: [],
  projects: [],
  materials: [],
  printers: [],
  profiles: [],
  jobs: [],
  collections: [],
  selectedIds: new Set(),
  jobStatus: '',
  jobQuery: '',
  jobPrinter: '',
  jobMaterial: '',
  taxonomy: { categories: [], tags: [] },
  workshopModelId: null,
  workshopDesignId: null,
  workshopDesigns: [],
  library: {
    q: '',
    category: '',
    extension: '',
    status: '',
    favorite: false,
    tag: '',
    sort: 'newest',
    view: safeStorageGet('layervault-library-view', 'grid'),
    collectionId: '',
    unfiled: false,
    visibleCount: 120
  }
};

const pageMeta = {
  dashboard: ['Dashboard', 'Your workshop at a glance.'],
  library: ['Model Library', 'Store, search and curate every printable asset.'],
  projects: ['Projects', 'Group parts, variants and print plans into complete builds.'],
  workshop: ['Workshop', 'Design printable parts in the integrated SketchForge workspace.'],
  materials: ['Materials & Stock', 'Physical bottles, spools, stock levels, cost and usage history.'],
  printers: ['Printers & Profiles', 'Owned machines and the recipes that work on each one.'],
  jobs: ['Print Lab', 'Record exact settings, outcomes and recipes worth repeating.'],
  settings: ['Settings', 'Backups, schedules and local workspace preferences.']
};

function esc(v = '') {
  return String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}
function fmtBytes(n = 0) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1073741824) return `${(n / 1048576).toFixed(1)} MB`;
  return `${(n / 1073741824).toFixed(2)} GB`;
}
function fmtDate(v) {
  if (!v) return '—';
  try { return new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(v)); }
  catch { return v; }
}
function fmtDateTime(v) {
  if (!v) return 'Not yet';
  try { return new Intl.DateTimeFormat('en-GB', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' }).format(new Date(v)); }
  catch { return v; }
}
function dims(m) {
  return [m.width_mm, m.depth_mm, m.height_mm].every(v => v != null)
    ? `${Number(m.width_mm).toFixed(1)} × ${Number(m.depth_mm).toFixed(1)} × ${Number(m.height_mm).toFixed(1)} mm`
    : 'Dimensions unavailable';
}
function healthClass(grade='') { return grade==='Healthy'?'healthy':grade==='Review'?'review':grade==='Issues'?'issues':'unknown'; }
function healthMini(m) { return m.health ? `<span class="health-mini ${healthClass(m.health.grade)}" title="Model Health ${esc(m.health.score)} / 100">${m.health.grade==='Healthy'?'✓':m.health.grade==='Review'?'!':'×'} ${esc(m.health.score)}</span>` : ''; }
function toast(msg, bad = false) {
  const el = document.createElement('div');
  el.className = `toast${bad ? ' bad' : ''}`;
  el.textContent = msg;
  $('#toastWrap').append(el);
  setTimeout(() => el.remove(), 3500);
}
async function api(url, opt = {}) {
  const r = await fetch(url, opt);
  if (!r.ok) {
    let d = {};
    try { d = await r.json(); } catch { /* ignore */ }
    throw new Error(d.detail || `${r.status} ${r.statusText}`);
  }
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : r;
}
function jsonOpt(method, data) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) };
}

let modalReturnFocus = null;
function focusables(root) {
  return $$('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])', root).filter(el => !el.closest('.hidden'));
}
function confirmAction(title, message, confirmLabel = 'Delete') {
  return new Promise(resolve => {
    const dialog = $('#confirmDialog');
    const returnFocus = document.activeElement;
    $('#confirmTitle').textContent = title;
    $('#confirmMessage').textContent = message;
    $('#confirmAccept').textContent = confirmLabel;
    dialog.classList.remove('hidden');
    document.body.classList.add('dialog-open');
    const finish = value => { dialog.classList.add('hidden'); document.body.classList.remove('dialog-open'); cleanup(); if (returnFocus?.isConnected) returnFocus.focus({preventScroll:true}); resolve(value); };
    const cancel = () => finish(false);
    const accept = () => finish(true);
    const key = e => {
      if (e.key === 'Escape') { e.preventDefault(); cancel(); }
      if (e.key === 'Tab') {
        const f = focusables(dialog); if (!f.length) return;
        const first=f[0], last=f[f.length-1];
        if (e.shiftKey && document.activeElement===first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement===last) { e.preventDefault(); first.focus(); }
      }
    };
    const cleanup = () => { $('#confirmCancel').removeEventListener('click', cancel); $('#confirmAccept').removeEventListener('click', accept); $('.confirm-backdrop', dialog).removeEventListener('click', cancel); dialog.removeEventListener('keydown', key); };
    $('#confirmCancel').addEventListener('click', cancel); $('#confirmAccept').addEventListener('click', accept); $('.confirm-backdrop', dialog).addEventListener('click', cancel); dialog.addEventListener('keydown', key);
    requestAnimationFrame(() => $('#confirmCancel').focus());
  });
}
function empty(title, text, button = '') {
  return `<div class="empty"><div><strong>${esc(title)}</strong><span>${esc(text)}</span>${button ? `<div style="margin-top:14px">${button}</div>` : ''}</div></div>`;
}
function tagsHtml(tags = [], clickable = false) {
  return tags.slice(0, 4).map(t => `<span class="tag" ${clickable ? `data-tag-filter="${esc(t)}"` : ''}>${esc(t)}</span>`).join('')
    + (tags.length > 4 ? `<span class="tag">+${tags.length - 4}</span>` : '');
}
function statusClass(s = '') { return String(s).toLowerCase().replace(/\s+/g, '-'); }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function previewable(m) { return PREVIEWABLE.has(m.extension); }
const THUMB_RENDER_VERSION = '3';
const DEFAULT_THUMB_VIEW = { yaw_deg: 22, pitch_deg: 18, zoom: 1 };
function thumbUrl(m) { const rev=encodeURIComponent(String(m.updated_at||'').slice(0,23)); return `/api/models/${m.id}/thumbnail?v=${THUMB_RENDER_VERSION}-${encodeURIComponent(m.sha256?.slice(0,8) || '')}-${rev}`; }
function lazyThumbAttrs(m, alt='') { return `loading="lazy" decoding="async" fetchpriority="low" src="${thumbUrl(m)}" alt="${esc(alt)}"`; }
function techFamily(v='') { return /resin|msla|sla|dlp/i.test(v) ? 'Resin' : 'FDM'; }
function sourceName(v='') { return ({spoolman:'SpoolmanDB',openresin:'Open Resin Alliance',manufacturer_resin:'Official Resin Catalogues',orca:'OrcaSlicer',uvtools:'UVtools',dragonfruit:'DragonFruit'})[v] || v || ''; }
function sourceBadge(v='', label='') { return v ? `<span class="source-badge source-${esc(v)}">${esc(label||sourceName(v))}</span>` : ''; }
function printerSpecs(p={}) { const parts=[]; if(p.build_x&&p.build_y&&p.build_z) parts.push(`${Number(p.build_x).toFixed(Number(p.build_x)%1?1:0)} × ${Number(p.build_y).toFixed(Number(p.build_y)%1?1:0)} × ${Number(p.build_z).toFixed(Number(p.build_z)%1?1:0)} mm`); if(p.resolution_x&&p.resolution_y) parts.push(`${p.resolution_x} × ${p.resolution_y} px`); if(p.xy_resolution_x_um||p.xy_resolution_y_um){const a=p.xy_resolution_x_um?Number(p.xy_resolution_x_um).toFixed(1):'—',b=p.xy_resolution_y_um?Number(p.xy_resolution_y_um).toFixed(1):a;parts.push(`XY ${a}${a!==b?` × ${b}`:''} μm`);} if(p.nozzle_mm) parts.push(`${p.nozzle_mm} mm nozzle`); return parts; }
function printerImageTag(p, cls='printer-photo') { return (p?.has_custom_image || p?.source_image_url) ? `<img class="${cls}" src="/api/printers/${encodeURIComponent(p.id)}/image?v=${encodeURIComponent(p.custom_image_asset_id||p.source_imported_at||'source')}" alt="${esc(p.name||p.model||'Printer')}" loading="lazy" decoding="async" onerror="this.closest('.printer-media')?.classList.add('image-failed');this.remove()">` : ''; }
function materialImageTag(m, cls='material-photo') { return (m?.has_custom_image || m?.has_source_image || m?.source_image_url) ? `<img class="${cls}" src="/api/materials/${encodeURIComponent(m.id)}/image?v=${encodeURIComponent(m.custom_image_asset_id||m.source_imported_at||'source')}" alt="${esc(m.name||'Material')}" loading="lazy" decoding="async" onerror="this.closest('.material-media')?.classList.add('image-failed');this.remove()">` : ''; }
function catalogMaterialImage(m, cls='catalog-product-image') { const colour=esc(m?.color_hex||'#808080'),resin=/resin/i.test(`${m?.kind||''} ${m?.technology||''}`);return m?.has_image ? `<span class="catalog-material-image-wrap"><img class="${cls}" src="/api/catalog/image?${new URLSearchParams({provider:m.provider,key:m.key})}" alt="${esc([m.brand,m.name].filter(Boolean).join(' ')||'Material')}" loading="lazy" decoding="async" onerror="this.closest('.catalog-material-image-wrap')?.classList.add('image-failed');this.remove()"><i class="catalog-swatch mini" style="background:${colour}"></i></span>` : `<span class="catalog-material-image-wrap generated-material ${resin?'resin-bottle':'filament-spool'}" style="--catalog-material-color:${colour}" aria-label="${esc(m?.color||'Recorded material colour')}"><i class="generated-pack"></i><i class="catalog-swatch mini" style="background:${colour}"></i></span>`; }
function materialSpecsHtml(specs={}, limit=8) { const labels={density_g_cm3:'Density',diameter_mm:'Diameter',diameter_tolerance_mm:'Diameter tolerance',nozzle_temp_c:'Nozzle temperature',bed_temp_c:'Bed temperature',package_weight_g:'Package weight',empty_spool_weight_g:'Empty spool',max_print_speed_mms:'Maximum speed',wavelength_nm:'Wavelength',normal_exposure_s:'Normal exposure',bottom_exposure_s:'Bottom exposure',drying:'Drying guidance',cleaning:'Cleaning',finish:'Finish',pattern:'Pattern',spool_type:'Spool type'}; const units={density_g_cm3:'g/cm³',diameter_mm:'mm',diameter_tolerance_mm:'mm',nozzle_temp_c:'°C',bed_temp_c:'°C',package_weight_g:'g',empty_spool_weight_g:'g',max_print_speed_mms:'mm/s',wavelength_nm:'nm',normal_exposure_s:'s',bottom_exposure_s:'s'}; const rows=Object.entries(specs||{}).filter(([,v])=>v!==null&&v!==''&&v!==undefined&&typeof v!=='object').slice(0,limit); return rows.length?`<div class="material-spec-grid">${rows.map(([k,v])=>`<div><small>${esc(labels[k]||k.replaceAll('_',' '))}</small><strong>${esc(Array.isArray(v)?v.join('–'):v)}${units[k]?` ${units[k]}`:''}</strong></div>`).join('')}</div>`:''; }
function money(v) { return v == null || v === '' || Number.isNaN(Number(v)) ? '—' : new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP'}).format(Number(v)); }
function settingDefs(technology='FDM') {
  if (techFamily(technology)==='Resin') return [
    ['layer_height_mm','Layer height','mm',0.01],['pixel_size_um','XY pixel size','μm',1],['normal_exposure_s','Normal exposure / cure','s',0.1],['bottom_exposure_s','Bottom exposure','s',0.1],['bottom_layers','Bottom layers','',1],
    ['transition_layers','Transition layers','',1],['lift_distance_mm','Lift distance 1','mm',0.1],['lift_distance_2_mm','Lift distance 2','mm',0.1],['lift_speed_mms','Lift speed 1','mm/s',0.1],['lift_speed_2_mms','Lift speed 2','mm/s',0.1],
    ['retract_distance_mm','Retract distance','mm',0.1],['retract_speed_mms','Retract speed 1','mm/s',0.1],['retract_speed_2_mms','Retract speed 2','mm/s',0.1],['retract_wait_s','Retract / settle time','s',0.1],
    ['bottom_lift_distance_mm','Bottom lift distance 1','mm',0.1],['bottom_lift_distance_2_mm','Bottom lift distance 2','mm',0.1],['bottom_lift_speed_mms','Bottom lift speed 1','mm/s',0.1],['bottom_lift_speed_2_mms','Bottom lift speed 2','mm/s',0.1],
    ['bottom_retract_speed_mms','Bottom retract speed 1','mm/s',0.1],['bottom_retract_speed_2_mms','Bottom retract speed 2','mm/s',0.1],['wait_before_print_s','Wait before print','s',0.1],['light_off_delay_s','Light-off delay','s',0.1],
    ['wait_before_cure_s','Wait before cure','s',0.1],['wait_after_cure_s','Wait after cure','s',0.1],['wait_after_lift_s','Wait after lift','s',0.1],['projector_pwm_percent','Projector PWM','%',1],['minimum_aa_alpha_percent','Minimum AA alpha','%',1],
    ['anti_aliasing','Anti-aliasing','',1],['resin_temperature_c','Resin temperature','°C',0.5],['post_cure_minutes','Post-cure time','min',0.5]
  ];
  return [
    ['layer_height_mm','Layer height','mm',0.01],['first_layer_height_mm','First-layer height','mm',0.01],['nozzle_temp_c','Nozzle temperature','°C',1],['first_layer_temp_c','First-layer nozzle temp','°C',1],['bed_temp_c','Bed temperature','°C',1],
    ['print_speed_mms','Print speed','mm/s',1],['outer_wall_speed_mms','Outer wall speed','mm/s',1],['inner_wall_speed_mms','Inner wall speed','mm/s',1],['infill_speed_mms','Sparse infill speed','mm/s',1],['solid_infill_speed_mms','Solid infill speed','mm/s',1],['top_surface_speed_mms','Top surface speed','mm/s',1],['first_layer_speed_mms','First-layer speed','mm/s',1],['travel_speed_mms','Travel speed','mm/s',1],
    ['acceleration_mms2','Print acceleration','mm/s²',1],['travel_acceleration_mms2','Travel acceleration','mm/s²',1],
    ['retraction_distance_mm','Retraction distance','mm',0.1],['retraction_speed_mms','Retraction speed','mm/s',1],['fan_percent','Part cooling fan','%',1],['flow_percent','Flow ratio','%',0.1],
    ['wall_count','Wall count','',1],['top_layers','Top shell layers','',1],['bottom_layers_fdm','Bottom shell layers','',1],['infill_percent','Infill','%',1],['nozzle_mm','Nozzle diameter','mm',0.1],['line_width_mm','Line width','mm',0.01],['first_layer_line_width_mm','First-layer line width','mm',0.01],
    ['support_density_percent','Support density','%',1],['support_speed_mms','Support speed','mm/s',1],['support_interface_layers','Support interface layers','',1],['brim_width_mm','Brim width','mm',0.1],['skirt_loops','Skirt loops','',1],['max_volumetric_speed_mm3s','Max volumetric speed','mm³/s',0.1]
  ];
}
function settingsEditor(technology='FDM', values={}) {
  return `<div class="settings-editor" data-settings-tech="${esc(techFamily(technology))}"><div class="settings-editor-head"><div><span class="kicker">${esc(techFamily(technology))} recipe</span><strong>Actual settings used</strong><small>This snapshot stays attached to the print even if the profile changes later.</small></div><span class="status">${esc(techFamily(technology))}</span></div><div class="settings-grid">${settingDefs(technology).map(([key,label,unit,step])=>`<div class="setting-field"><label>${esc(label)}</label><div><input type="number" step="${step}" data-setting="${key}" value="${esc(values?.[key] ?? '')}">${unit?`<span>${esc(unit)}</span>`:''}</div></div>`).join('')}</div></div>`;
}
function collectSettings(root=document) { const out={}; $$('[data-setting]',root).forEach(i=>{if(i.value!=='')out[i.dataset.setting]=Number(i.value)}); return out; }
function settingLabel(key, technology='FDM') { return settingDefs(technology).find(x=>x[0]===key)?.[1] || key.replaceAll('_',' '); }
function settingUnit(key, technology='FDM') { return settingDefs(technology).find(x=>x[0]===key)?.[2] || ''; }
function settingsSummary(settings={}, technology='FDM', limit=4) { const priority=techFamily(technology)==='Resin'?['layer_height_mm','normal_exposure_s','bottom_exposure_s','lift_speed_mms','retract_wait_s']:['layer_height_mm','nozzle_temp_c','bed_temp_c','print_speed_mms','retraction_distance_mm']; return priority.filter(k=>settings?.[k]!=null).slice(0,limit).map(k=>`<span><b>${esc(settings[k])}${esc(settingUnit(k,technology))}</b>${esc(settingLabel(k,technology))}</span>`).join(''); }
function failureChoices(technology='FDM') { return techFamily(technology)==='Resin' ? ['Build plate adhesion','Support failure','Layer separation','Under-exposure','Over-exposure','Suction / cupping','Warping','Resin contamination','FEP / release issue','Other'] : ['Bed adhesion','Warping','Stringing','Under-extrusion','Over-extrusion','Layer shift','Clogged nozzle','Support failure','Bridging','Other']; }
function failurePicker(technology='FDM', selected=[]) { return `<div class="failure-picker">${failureChoices(technology).map(x=>`<label><input type="checkbox" data-failure-tag value="${esc(x)}" ${selected.includes(x)?'checked':''}><span>${esc(x)}</span></label>`).join('')}</div>`; }
function resultMetricPicker(values={}) { return `<div class="result-subratings">${[['quality','Surface / detail'],['reliability','Reliability'],['supports','Supports / cleanup']].map(([k,l])=>`<div><label>${l}</label><select data-result-metric="${k}"><option value="">Not rated</option>${[1,2,3,4,5].map(n=>`<option value="${n}" ${Number(values?.[k])===n?'selected':''}>${n} / 5</option>`).join('')}</select></div>`).join('')}</div>`; }

function modelSearchPickerHtml(prefix, models, placeholder='Search your model library…') {
  return `<div class="model-search-picker" id="${prefix}Picker"><div class="model-search-input"><span aria-hidden="true">⌕</span><input id="${prefix}Search" autocomplete="off" placeholder="${esc(placeholder)}" role="combobox" aria-expanded="false" aria-controls="${prefix}Results"><button type="button" class="model-search-clear hidden" id="${prefix}Clear" aria-label="Clear selected model">×</button></div><input id="${prefix}Value" type="hidden"><div class="model-search-results hidden" id="${prefix}Results" role="listbox"></div></div>`;
}
function bindModelSearchPicker(prefix, models, {onSelect=null, emptyText='No matching models'}={}) {
  const input=$(`#${prefix}Search`),value=$(`#${prefix}Value`),results=$(`#${prefix}Results`),clear=$(`#${prefix}Clear`),picker=$(`#${prefix}Picker`);
  if(!input||!value||!results)return null;
  const searchable=models.map(model=>({model,text:[model.title,model.original_filename,model.category,...(model.tags||[])].join(' ').toLowerCase()}));
  const close=()=>{results.classList.add('hidden');input.setAttribute('aria-expanded','false');picker?.classList.remove('open');};
  const choose=model=>{value.value=model.id;input.value=model.title;clear?.classList.remove('hidden');close();onSelect?.(model);};
  const render=(query='')=>{const q=query.trim().toLowerCase(),matches=searchable.filter(item=>!q||item.text.includes(q)).slice(0,8);results.innerHTML=matches.length?matches.map(({model})=>`<button type="button" role="option" data-model-search-result="${model.id}"><span class="model-search-result-thumb">${previewable(model)?`<img src="${thumbUrl(model)}" alt="" loading="lazy" onerror="this.remove()">`:`<i>${esc(model.extension.slice(1).toUpperCase())}</i>`}</span><span><strong>${esc(model.title)}</strong><small>${esc(model.category||'Unsorted')} · ${esc(model.original_filename)}</small></span>${model.parent_model_id?`<em>${esc(model.version_label||'Version')}</em>`:''}</button>`).join(''):`<div class="model-search-no-results"><strong>${esc(emptyText)}</strong><small>Try part of the title, filename, category or tag.</small></div>`;results.classList.remove('hidden');input.setAttribute('aria-expanded','true');picker?.classList.add('open');$$('[data-model-search-result]',results).forEach(button=>button.onclick=e=>{e.preventDefault();e.stopPropagation();const model=models.find(item=>item.id===button.dataset.modelSearchResult);if(model)choose(model);});};
  input.onfocus=()=>render(input.value===models.find(model=>model.id===value.value)?.title?'':input.value);
  input.oninput=()=>{value.value='';clear?.classList.add('hidden');render(input.value);onSelect?.(null);};
  input.onkeydown=e=>{if(e.key==='Escape')return close();if(e.key==='ArrowDown'){e.preventDefault();results.querySelector('button')?.focus();}if(e.key==='Enter'){const first=results.querySelector('[data-model-search-result]');if(first){e.preventDefault();first.click();}}};
  input.onblur=()=>setTimeout(close,120);
  clear?.addEventListener('click',()=>{value.value='';input.value='';clear.classList.add('hidden');onSelect?.(null);input.focus();render('');});
  return {value,input,choose,close};
}

function jobModelPickerHtml() {
  return `<div class="field wide"><label>Models in this print</label><div class="job-model-picker"><div class="job-model-search"><span aria-hidden="true">⌕</span><input id="jobModelSearch" type="search" autocomplete="off" placeholder="Search your model library…"><small>Tick every model on the plate, then set how many copies are being printed.</small></div><div id="jobModelOptions" class="job-model-options"></div><div id="jobModelSelected" class="job-model-selected"></div></div></div>`;
}
function bindJobModelPicker(models, initial=[]) {
  const selected=new Map();
  (initial||[]).forEach(item=>{const id=item.model_id||item.id;if(id&&models.some(model=>model.id===id))selected.set(id,Math.max(1,Number(item.quantity)||1));});
  const search=$('#jobModelSearch'),options=$('#jobModelOptions'),chosen=$('#jobModelSelected');
  const modelText=model=>[model.title,model.original_filename,model.category,...(model.tags||[])].join(' ').toLowerCase();
  const renderSelected=()=>{const entries=[...selected.entries()];chosen.innerHTML=entries.length?`<div class="job-model-selected-head"><strong>${entries.length} model${entries.length===1?'':'s'} selected</strong><span>${entries.reduce((sum,[,quantity])=>sum+quantity,0)} total part${entries.reduce((sum,[,quantity])=>sum+quantity,0)===1?'':'s'}</span></div>${entries.map(([id,quantity])=>{const model=models.find(item=>item.id===id);return `<div class="job-model-row" data-job-model-row="${id}"><span class="job-model-thumb">${model&&previewable(model)?`<img src="${thumbUrl(model)}" alt="" loading="lazy" onerror="this.remove()">`:`<i>${esc(model?.extension?.slice(1).toUpperCase()||'3D')}</i>`}</span><span class="grow"><strong>${esc(model?.title||'Model')}</strong><small>${esc(model?.original_filename||'Library model')}</small></span><div class="job-model-quantity"><button type="button" data-job-model-dec="${id}" aria-label="Decrease ${esc(model?.title||'model')} quantity">−</button><input type="number" min="1" max="999" value="${quantity}" data-job-model-qty="${id}" aria-label="${esc(model?.title||'Model')} quantity"><button type="button" data-job-model-inc="${id}" aria-label="Increase ${esc(model?.title||'model')} quantity">＋</button></div></div>`;}).join('')}`:`<div class="job-model-none"><span>◇</span><div><strong>No models selected</strong><small>A print can still be logged without linking a library model.</small></div></div>`;
    $$('[data-job-model-dec]',chosen).forEach(button=>button.onclick=()=>{const id=button.dataset.jobModelDec,current=selected.get(id)||1;if(current<=1){selected.delete(id);renderOptions();}else selected.set(id,current-1);renderSelected();});
    $$('[data-job-model-inc]',chosen).forEach(button=>button.onclick=()=>{const id=button.dataset.jobModelInc;selected.set(id,Math.min(999,(selected.get(id)||1)+1));renderSelected();});
    $$('[data-job-model-qty]',chosen).forEach(input=>input.onchange=()=>{selected.set(input.dataset.jobModelQty,Math.max(1,Math.min(999,Number(input.value)||1)));renderSelected();});
  };
  const renderOptions=()=>{const query=(search?.value||'').trim().toLowerCase(),matches=models.filter(model=>!query||modelText(model).includes(query)).slice(0,10);options.innerHTML=matches.length?matches.map(model=>`<label class="job-model-option"><input type="checkbox" value="${model.id}" ${selected.has(model.id)?'checked':''}><span class="job-model-check">✓</span><span><strong>${esc(model.title)}</strong><small>${esc(model.category||'Unsorted')} · ${esc(model.original_filename)}</small></span></label>`).join(''):`<div class="job-model-no-results">No models match “${esc(search?.value||'')}”.</div>`;$$('input[type=checkbox]',options).forEach(input=>input.onchange=()=>{if(input.checked)selected.set(input.value,selected.get(input.value)||1);else selected.delete(input.value);renderSelected();});renderSelected();};
  search?.addEventListener('input',debounce(renderOptions,100));renderOptions();
  return {get value(){return [...selected.entries()].map(([model_id,quantity])=>({model_id,quantity}));}};
}

function setPage(page) {
  disposeDetailPreview();
  if (state.page === 'workshop' && page !== 'workshop') disposeViewer();
  if (state.page === 'workshop' && page !== 'workshop') disposeSketchForgeBridge();
  state.page = page;
  document.body.dataset.page = page;
  $$('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  $('.sidebar').classList.remove('open');
  $('#navScrim')?.classList.remove('show');
  window.scrollTo({top:0,left:0,behavior:'auto'});
  renderPage();
  requestAnimationFrame(() => window.scrollTo({top:0,left:0,behavior:'auto'}));
}

async function refreshCore() {
  const [models, projects, materials, printers, profiles, jobs, taxonomy, collections] = await Promise.all([
    api('/api/models'), api('/api/projects'), api('/api/materials'), api('/api/printers'), api('/api/profiles'), api('/api/jobs'), api('/api/taxonomy'), api('/api/collections')
  ]);
  jobs.forEach(job=>{if(job.models?.length)job.model_title=job.models.map(item=>`${item.title}${item.quantity>1?` × ${item.quantity}`:''}`).join(' · ');});
  Object.assign(state, { models, projects, materials, printers, profiles, jobs, taxonomy, collections });
}

async function renderPage() {
  content.innerHTML = empty('Loading your workspace', 'Reading the local LayerVault database.');
  try {
    if (state.page === 'dashboard') return renderDashboard();
    if (state.page === 'library') return renderLibrary();
    if (state.page === 'projects') return renderProjects();
    if (state.page === 'workshop') return renderSketchForge();
    if (state.page === 'materials') return renderMaterials();
    if (state.page === 'printers') return renderPrinters();
    if (state.page === 'jobs') return renderJobs();
    if (state.page === 'settings') return renderSettings();
  } catch (e) {
    content.innerHTML = empty('Could not load this page', e.message);
    toast(e.message, true);
  }
}

let sketchForgeBridgeListener = null;

function disposeSketchForgeBridge() {
  if (sketchForgeBridgeListener) window.removeEventListener('message', sketchForgeBridgeListener);
  sketchForgeBridgeListener = null;
}

function resolveSketchForgeUrl() {
  const configured = (document.body.dataset.sketchforgeUrl || '').trim();
  if (configured) return configured.replace(/\/+$/, '');
  return `${window.location.protocol}//${window.location.hostname}:3004`;
}

function sketchForgeEditorUrl() {
  const url = new URL('/', `${resolveSketchForgeUrl()}/`);
  url.searchParams.set('editor', '1');
  url.searchParams.set('layervaultOrigin', window.location.origin);
  return url.toString();
}

async function sendModelToSketchForge(modelId) {
  const model = state.models.find(item => item.id === modelId);
  const frame = $('#sketchForgeFrame');
  if (!model || !frame?.contentWindow || frame.dataset.ready !== 'true') throw new Error('SketchForge is still starting');
  const response = await fetch(`/api/models/${encodeURIComponent(model.id)}/file`, {cache:'no-store'});
  if (!response.ok) throw new Error('Could not read the selected LayerVault model');
  const buffer = await response.arrayBuffer();
  frame.contentWindow.postMessage({
    type: 'layervault:import-model',
    name: model.original_filename || `${model.title}${model.extension || '.stl'}`,
    mimeType: response.headers.get('content-type') || 'application/octet-stream',
    buffer,
  }, new URL(resolveSketchForgeUrl()).origin, [buffer]);
}

function sketchForgeLibraryModal() {
  const models = state.models.filter(model => ['.stl','.obj','.step','.stp'].includes(String(model.extension || '').toLowerCase()));
  openModal(
    'Import from Model Library',
    models.length
      ? `<div class="sketchforge-import-intro"><span>SF</span><div><strong>Start a SketchForge project from a stored model</strong><small>STL, OBJ and STEP files are transferred locally into SketchForge. Your original LayerVault file is not changed.</small></div></div>${modelSearchPickerHtml('sketchForgeModel', models, 'Search compatible models…')}`
      : empty('No compatible models yet', 'Add an STL, OBJ or STEP file to the Model Library first.'),
    models.length ? '<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="sendSketchForgeModel" disabled>Import into SketchForge</button>' : '<button class="primary" data-close-modal>Close</button>',
    'Workshop · SketchForge',
  );
  if (!models.length) return;
  let selected = null;
  bindModelSearchPicker('sketchForgeModel', models, {onSelect:model=>{selected=model;$('#sendSketchForgeModel').disabled=!model;}});
  $('#sendSketchForgeModel').onclick = async event => {
    const button = event.currentTarget;
    if (!selected) return;
    button.disabled = true;
    button.textContent = 'Importing…';
    try {
      await sendModelToSketchForge(selected.id);
      closeModal();
      toast(`${selected.title} sent to SketchForge`);
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Import into SketchForge';
      toast(error.message, true);
    }
  };
}

async function renderSketchForge() {
  disposeSketchForgeBridge();
  disposeViewer();
  state.models = await api('/api/models');
  const baseUrl = resolveSketchForgeUrl();
  const editorUrl = sketchForgeEditorUrl();
  const pendingModelId = state.workshopModelId;
  state.workshopModelId = null;
  content.innerHTML = `
    <section class="sketchforge-shell" aria-label="SketchForge 3D Workshop">
      <header class="sketchforge-bar">
        <div class="sketchforge-mark" aria-hidden="true">SF</div>
        <div class="sketchforge-title"><span class="kicker">Integrated local-first CAD editor</span><div><strong>SketchForge</strong><small>by Formsmith746 and contributors</small></div></div>
        <div class="sketchforge-status checking" id="sketchForgeStatus"><i></i>Starting web editor…</div>
        <div class="sketchforge-note">Private designs stay in this browser · save important designs to <b>Shared</b> for LayerVault backups</div>
        <div class="sketchforge-actions">
          <button class="ghost" type="button" id="importSketchForgeModel">＋ Import library model</button>
          <a class="ghost" href="https://github.com/Formsmith746/SketchForge-3D" target="_blank" rel="noopener noreferrer">Source & credit ↗</a>
          <button class="primary" type="button" id="openSketchForge">Open full screen ↗</button>
        </div>
      </header>
      <div class="sketchforge-frame-wrap">
        <div class="sketchforge-loading" id="sketchForgeLoading"><div class="boot-spinner" aria-hidden="true"></div><strong>Opening SketchForge</strong><span>Loading the browser-native workplane and geometry tools—no streamed desktop or VNC.</span></div>
        <iframe id="sketchForgeFrame" title="SketchForge 3D editor" src="about:blank" allow="clipboard-read; clipboard-write; fullscreen" allowfullscreen></iframe>
      </div>
    </section>`;
  const frame = $('#sketchForgeFrame');
  const loading = $('#sketchForgeLoading');
  const status = $('#sketchForgeStatus');
  const expectedOrigin = new URL(baseUrl).origin;
  sketchForgeBridgeListener = event => {
    if (event.origin !== expectedOrigin || event.source !== frame.contentWindow) return;
    if (event.data?.type === 'sketchforge:layervault-import-received') toast(`${event.data.name || 'Model'} opened as a SketchForge project`);
  };
  window.addEventListener('message', sketchForgeBridgeListener);
  const connect = async () => {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 7000);
      await fetch(`${baseUrl}/api/shared-projects`, {mode:'no-cors', cache:'no-store', signal:controller.signal});
      clearTimeout(timeout);
      status.className = 'sketchforge-status online';
      status.innerHTML = '<i></i>Web editor connected';
      frame.addEventListener('load', () => {
        frame.dataset.ready = 'true';
        loading?.classList.add('loaded');
        if (pendingModelId) setTimeout(() => sendModelToSketchForge(pendingModelId).catch(error => toast(error.message, true)), 750);
      }, {once:true});
      frame.src = editorUrl;
    } catch (_) {
      status.className = 'sketchforge-status offline';
      status.innerHTML = '<i></i>SketchForge service offline';
      loading.innerHTML = `<div class="sketchforge-offline">!</div><strong>SketchForge is still starting</strong><span>Start the supplied Docker Compose stack, then try again. The first build installs the web editor dependencies.</span><button class="ghost" type="button" id="retrySketchForge">Try again</button>`;
      $('#retrySketchForge')?.addEventListener('click', renderSketchForge);
    }
  };
  connect();
  $('#importSketchForgeModel').onclick = sketchForgeLibraryModal;
  $('#openSketchForge').onclick = () => window.open(editorUrl, '_blank', 'noopener,noreferrer');
}

async function renderDashboard() {
  const s = await api('/api/stats');
  content.innerHTML = `
    <div class="hero">
      <div>
        <span class="kicker">Local-first 3D workspace</span>
        <h2>Keep every model, material and successful print recipe in one place.</h2>
        <p>LayerVault organises the files around your printing workflow without touching the originals. Catalogue downloads, plan builds, keep proven printer settings and prepare models in the Workshop from one local Docker app.</p>
      </div>
      <div class="hero-actions">
        <button class="primary" data-action="pick-upload">＋ Add models</button>
        <button class="ghost" data-action="new-project">New project</button>
      </div>
    </div>
    <div class="stats">
      <div class="stat"><small>Models</small><strong>${s.models}</strong><em>${fmtBytes(s.bytes)} stored locally</em></div>
      <div class="stat"><small>Projects</small><strong>${s.projects}</strong><em>organised builds</em></div>
      <div class="stat"><small>Stock items</small><strong>${s.materials}</strong><em>${s.low_stock||0} low-stock bottle/spool${Number(s.low_stock)===1?'':'s'}</em></div>
      <div class="stat"><small>Printers</small><strong>${s.printers||0}</strong><em>owned machines</em></div>
      <div class="stat"><small>Recorded prints</small><strong>${s.prints}</strong><em>successful prints</em></div>
    </div>
    <div class="section-head">
      <div><h2>Recently added</h2><p>Your newest files, ready to organise or prepare.</p></div>
      <button class="small-btn" data-page-jump="library">View full library</button>
    </div>
    ${s.recent.length ? `<div class="grid">${s.recent.map(modelCard).join('')}</div>` : empty('Your library is empty', 'Upload an STL, OBJ or 3MF to start building your catalogue.', '<button class="primary" data-action="pick-upload">Add your first model</button>')}
    ${s.categories.length ? `
      <div class="section-head"><div><h2>Categories</h2><p>Quick access to the model categories you use most.</p></div></div>
      <div class="list">${s.categories.map(c => `
        <div class="list-row">
          <div class="file-orb" style="width:38px;height:38px;border-radius:10px;font-size:9px">${esc(c.category.slice(0, 3).toUpperCase())}</div>
          <div class="grow"><strong>${esc(c.category)}</strong><small>${c.c} model${c.c === 1 ? '' : 's'}</small></div>
          <button class="small-btn" data-library-category="${esc(c.category)}">Browse category</button>
        </div>`).join('')}</div>` : ''}
  `;
}

function backupScopeChoices(scopes=[], selected=[]) {
  return `<div class="backup-scope-grid">${scopes.map(scope=>`<label class="backup-scope-option"><input type="checkbox" data-backup-scope value="${esc(scope.id)}" ${selected.includes(scope.id)?'checked':''}><span><i aria-hidden="true">✓</i><strong>${esc(scope.label)}</strong><small>${esc({database:'Complete local database and workspace configuration.',devices:'Physical printers and reusable slicing profiles.',materials:'Stock records, purchases and material usage.',models:'Catalogue metadata and every stored model file.',projects:'Project plans and editable Workshop designs.',print_logs:'Print recipes, results, ratings and photos.'}[scope.id]||'Included in this backup.')}</small></span></label>`).join('')}</div>`;
}
function backupFrequencyLabel(schedule={}) {
  const time=esc(schedule.time_local||'02:00');
  if(schedule.frequency==='daily')return `Every day at ${time}`;
  if(schedule.frequency==='monthly')return `Day ${esc(schedule.month_day||1)} of each month at ${time}`;
  return `${['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][Number(schedule.weekday)||0]} at ${time}`;
}
function themePickerHtml(){
  const active=currentTheme();
  return `<section class="settings-card theme-card"><div class="settings-card-head"><div><span class="kicker">Appearance</span><h3>Glass themes</h3><p>Change the atmosphere without losing LayerVault's translucent iOS-style surfaces. This preference stays in this browser.</p></div><span class="settings-card-symbol">◐</span></div><div class="theme-options">${THEMES.map(theme=>`<button class="theme-option ${theme.id===active?'active':''}" type="button" data-theme-choice="${theme.id}" aria-pressed="${theme.id===active}"><span class="theme-preview theme-preview-${theme.id}"><i></i><i></i><i></i></span><span><strong>${theme.name}</strong><small>${theme.note}</small></span><b aria-hidden="true">✓</b></button>`).join('')}</div></section>`;
}
function storageSettingsHtml(storage={}){
  const definitions=[
    ['workspace','LAYERVAULT_DATA_PATH','App workspace','Database-adjacent caches, imports, photos and slicer settings.','./data'],
    ['database','LAYERVAULT_DATABASE_PATH','Database','The LayerVault SQLite database.','./data'],
    ['models','LAYERVAULT_MODELS_PATH','Model files','STL, OBJ, 3MF and other library assets.','./data/files'],
    ['backups','LAYERVAULT_BACKUPS_PATH','Backup archives','Manual and scheduled recovery ZIP files.','./data/backups'],
  ];
  return `<section class="settings-card storage-card">
    <div class="settings-card-head"><div><span class="kicker">Storage locations</span><h3>Choose where LayerVault keeps its data</h3><p>Use local server folders, attached drives or mounted NAS shares. Docker only receives the folders you explicitly map.</p></div><span class="settings-card-symbol">⌁</span></div>
    <div class="storage-location-list">${definitions.map(([key,env,label,note,fallback])=>{const item=storage[key]||{};const value=item.host_path||fallback;return `<label class="storage-location-row"><span class="storage-location-icon">${key==='database'?'DB':key==='models'?'3D':key==='backups'?'ZIP':'APP'}</span><span class="grow"><strong>${label}</strong><small>${note}</small><input data-storage-env="${env}" value="${esc(value)}" spellcheck="false" aria-label="${label} host path"><em>Mounted inside LayerVault at ${esc(item.container_path||'after restart')}</em></span><span class="storage-path-state ${item.writable?'ready':'pending'}"><i></i>${item.writable?'Ready':'Apply & restart'}</span></label>`}).join('')}</div>
    <div class="storage-help"><span>NAS examples</span><code>//PRINT-NAS/3d-models</code><code>/mnt/nas/layervault</code><small>Docker Desktop may ask you to allow access to a Windows drive or network share.</small></div>
    <div class="settings-card-actions"><small>Download the configuration, place it beside <code>docker-compose.yml</code> as <code>.env</code>, then restart LayerVault.</small><button class="primary" id="downloadStorageEnv" type="button">Download storage settings</button></div>
  </section>`;
}
function downloadStorageEnvironment(){
  const values=Object.fromEntries($$('[data-storage-env]').map(input=>[input.dataset.storageEnv,input.value.trim()]));
  const encode=value=>/^[A-Za-z0-9_./:\\-]+$/.test(value)?value:`"${value.replace(/\\/g,'\\\\').replace(/"/g,'\\"')}"`;
  const lines=['# LayerVault storage locations','# Use host paths here. NAS shares must already be reachable by Docker Desktop or mounted on the server.',...Object.entries(values).map(([key,value])=>`${key}=${encode(value)}`),''];
  const blob=new Blob([lines.join('\n')],{type:'text/plain;charset=utf-8'});
  const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='layervault-storage.env';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  toast('Storage settings downloaded');
}
function scheduleFormHtml(item={}, scopes=[]) {
  const chosen=item.scopes?.length?item.scopes:scopes.map(x=>x.id);
  return `<form id="backupScheduleForm" class="backup-schedule-form">
    <div class="fields backup-schedule-fields">
      ${field('name','Schedule name',item.name||'Weekly full backup','text','wide','e.g. Sunday workshop backup')}
      ${selectField('frequency','Frequency',[{value:'daily',label:'Daily'},{value:'weekly',label:'Weekly'},{value:'monthly',label:'Monthly'}],item.frequency||'weekly')}
      <div class="field"><label>Run time</label><input name="time_local" type="time" value="${esc(item.time_local||'02:00')}"></div>
      <div class="field schedule-weekday"><label>Day of week</label><select name="weekday">${['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map((label,index)=>`<option value="${index}" ${Number(item.weekday??6)===index?'selected':''}>${label}</option>`).join('')}</select></div>
      <div class="field schedule-month-day"><label>Day of month</label><input name="month_day" type="number" min="1" max="28" value="${Number(item.month_day||1)}"></div>
      <div class="field"><label>Backups to keep</label><input name="keep_count" type="number" min="1" max="100" value="${Number(item.keep_count||10)}"></div>
    </div>
    <div class="backup-form-section"><div><strong>What should be protected?</strong><small>Each archive includes a manifest so its contents are clear.</small></div>${backupScopeChoices(scopes,chosen)}</div>
    <label class="settings-toggle"><input name="enabled" type="checkbox" ${item.enabled!==false?'checked':''}><span><b>Schedule enabled</b><small>LayerVault creates backups while the app is running.</small></span></label>
  </form>`;
}
async function backupScheduleModal(id=null) {
  const settings=await api('/api/settings/backups');
  const item=id?settings.schedules.find(x=>x.id===id):null;
  openModal(item?'Edit backup schedule':'Create backup schedule',scheduleFormHtml(item||{},settings.scopes),`${item?'<button class="danger" id="deleteBackupScheduleBtn">Delete</button>':''}<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="saveBackupScheduleBtn">${item?'Save schedule':'Create schedule'}</button>`,'Settings · automatic backups');
  const form=$('#backupScheduleForm');
  const showFrequencyFields=()=>{const f=form.frequency.value;$('.schedule-weekday',form).classList.toggle('hidden',f!=='weekly');$('.schedule-month-day',form).classList.toggle('hidden',f!=='monthly');};
  form.frequency.addEventListener('change',showFrequencyFields);showFrequencyFields();
  $('#saveBackupScheduleBtn').onclick=async()=>{const d=formDataObject(form);d.weekday=Number(d.weekday||0);d.month_day=Number(d.month_day||1);d.keep_count=Number(d.keep_count||10);d.enabled=form.enabled.checked;d.scopes=$$('[data-backup-scope]:checked',form).map(x=>x.value);try{await api(item?`/api/settings/backup-schedules/${item.id}`:'/api/settings/backup-schedules',jsonOpt(item?'PATCH':'POST',d));toast(item?'Backup schedule updated':'Backup schedule created');closeModal();renderSettings();}catch(e){toast(e.message,true);}};
  if(item)$('#deleteBackupScheduleBtn').onclick=async()=>{if(!(await confirmAction('Delete backup schedule?',`“${item.name}” will stop running. Existing backup files are kept.`)))return;await api(`/api/settings/backup-schedules/${item.id}`,{method:'DELETE'});toast('Backup schedule removed');closeModal();renderSettings();};
}
async function renderSettings() {
  const settings=await api('/api/settings/backups');
  const last=settings.backups[0];
  const enabled=settings.schedules.filter(x=>x.enabled);
  content.innerHTML=`
    <div class="settings-hero">
      <div class="settings-hero-icon" aria-hidden="true">⚙</div>
      <div><span class="kicker">Local workspace controls</span><h2>Settings</h2><p>Protect the parts of LayerVault that matter to you. Backups remain on this server and can be downloaded whenever you need an off-device copy.</p></div>
      <div class="settings-privacy"><i></i><span><strong>Private by design</strong><small>No cloud account or external backup service is required.</small></span></div>
    </div>
    ${themePickerHtml()}
    ${storageSettingsHtml(settings.storage)}
    <div class="settings-summary">
      <div><span class="settings-summary-icon">↻</span><small>Last backup</small><strong>${last?fmtDateTime(last.created_at):'Not created yet'}</strong></div>
      <div><span class="settings-summary-icon">◷</span><small>Active schedules</small><strong>${enabled.length}</strong></div>
      <div><span class="settings-summary-icon">▰</span><small>Backup storage</small><strong>${fmtBytes(settings.storage_bytes||0)}</strong></div>
    </div>
    <div class="settings-grid">
      <section class="settings-card settings-manual-card">
        <div class="settings-card-head"><div><span class="kicker">Manual backup</span><h3>Create a backup now</h3><p>Choose exactly what goes into this archive. Model files and photos are included when their category is selected.</p></div><span class="settings-card-symbol">⇩</span></div>
        <form id="manualBackupForm">${backupScopeChoices(settings.scopes,settings.scopes.map(x=>x.id))}<div class="settings-card-actions"><small>Archives are written to your configured backup location.</small><button class="primary" id="runBackupBtn" type="submit">Create backup</button></div></form>
      </section>
      <section class="settings-card settings-schedule-card">
        <div class="settings-card-head"><div><span class="kicker">Automatic protection</span><h3>Backup schedules</h3><p>Daily, weekly or monthly backups run while LayerVault is online.</p></div><button class="small-btn" id="newBackupScheduleBtn">＋ New schedule</button></div>
        <div class="backup-schedule-list">${settings.schedules.length?settings.schedules.map(s=>`<button class="backup-schedule-row" data-backup-schedule="${s.id}"><span class="schedule-state ${s.enabled?'on':'off'}"><i></i></span><span class="grow"><strong>${esc(s.name)}</strong><small>${backupFrequencyLabel(s)} · ${s.scopes.length} categor${s.scopes.length===1?'y':'ies'} · keep ${s.keep_count}</small></span><span class="schedule-next"><small>${s.enabled?'Next run':'Paused'}</small><b>${s.enabled?fmtDateTime(s.next_run_at):'—'}</b></span><span class="row-chevron">›</span></button>`).join(''):`<div class="settings-empty"><span>◷</span><strong>No automatic backups yet</strong><small>Create a schedule once and LayerVault will handle the routine copies.</small></div>`}</div>
      </section>
    </div>
    <section class="settings-card backup-history-card">
      <div class="settings-card-head"><div><span class="kicker">Recovery files</span><h3>Backup history</h3><p>Download important archives to another drive or trusted storage location.</p></div><span class="status">${settings.backups.length} saved</span></div>
      ${settings.backups.length?`<div class="backup-history-list">${settings.backups.map(b=>`<div class="backup-history-row"><span class="backup-file-icon">ZIP</span><span class="grow"><strong>${esc(b.file_name)}</strong><small>${fmtDateTime(b.created_at)} · ${fmtBytes(b.size_bytes)} · ${b.reason==='scheduled'?'Automatic':'Manual'}</small><span class="backup-scope-line">${b.scopes.map(scope=>`<i>${esc(settings.scopes.find(x=>x.id===scope)?.label||scope)}</i>`).join('')}</span></span><a class="small-btn button-link" href="${esc(b.download_url)}">Download</a><button class="icon-btn backup-delete" data-delete-backup="${b.id}" aria-label="Delete backup">×</button></div>`).join('')}</div>`:`<div class="settings-empty horizontal"><span>◇</span><div><strong>No backup files yet</strong><small>Your first manual or scheduled archive will appear here.</small></div></div>`}
    </section>`;
  $('#manualBackupForm').onsubmit=async e=>{e.preventDefault();const button=$('#runBackupBtn');const scopes=$$('[data-backup-scope]:checked',e.currentTarget).map(x=>x.value);button.disabled=true;button.textContent='Creating archive…';try{const result=await api('/api/settings/backups/run',jsonOpt('POST',{scopes}));toast(`Backup created · ${fmtBytes(result.size_bytes)}`);renderSettings();}catch(err){toast(err.message,true);button.disabled=false;button.textContent='Create backup';}};
  $$('[data-theme-choice]').forEach(button=>button.onclick=()=>applyTheme(button.dataset.themeChoice,true));
  $('#downloadStorageEnv').onclick=downloadStorageEnvironment;
  $('#newBackupScheduleBtn').onclick=()=>backupScheduleModal();
  $$('[data-backup-schedule]').forEach(button=>button.onclick=()=>backupScheduleModal(button.dataset.backupSchedule));
  $$('[data-delete-backup]').forEach(button=>button.onclick=async()=>{const item=settings.backups.find(x=>x.id===button.dataset.deleteBackup);if(!(await confirmAction('Delete backup file?',`${item?.file_name||'This archive'} will be permanently removed.`)))return;await api(`/api/settings/backups/${button.dataset.deleteBackup}`,{method:'DELETE'});toast('Backup file deleted');renderSettings();});
}

function modelCard(m) {
  const ext = m.extension.replace('.', '').toUpperCase();
  const selected = state.selectedIds.has(m.id);
  const thumb = previewable(m) ? `<img class="model-thumb" ${lazyThumbAttrs(m, `Preview of ${m.title}`)} onerror="this.closest('.model-preview').classList.add('thumb-failed');this.remove()">` : '';
  return `
    <article class="card model-card ${selected ? 'selected' : ''}" data-model-id="${m.id}" draggable="true" tabindex="0" aria-label="Open ${esc(m.title)}">
      <div class="model-preview">
        ${thumb}
        <div class="model-shape"><div class="file-orb">${esc(ext)}</div></div>
        <label class="select-model" title="Select model"><input type="checkbox" data-select-model="${m.id}" ${selected ? 'checked' : ''}><span></span></label>
        <div class="badge-row"><span class="badge accent">${esc(ext)}</span><span class="badge">${esc(m.category || 'Unsorted')}</span>${m.parent_model_id ? `<span class="badge lineage-badge">↳ ${esc(m.version_label || 'Variant')}</span>` : ''}</div>
        <button class="favorite-btn ${m.favorite ? 'on' : ''}" data-favorite="${m.id}" title="${m.favorite ? 'Remove favourite' : 'Add favourite'}" aria-label="Favourite">★</button>
        <div class="model-preview-bottom"><span>${previewable(m) ? '<span class="previewable-dot">Cached preview</span>' : 'Stored asset'}</span><span>${fmtBytes(m.size_bytes)}</span></div>
      </div>
      <div class="card-body">
        <div class="card-title-row"><h3 title="${esc(m.title)}">${esc(m.title)}</h3><span class="card-status-stack">${healthMini(m)}<span class="status ${statusClass(m.status)}">${esc(m.status)}</span></span></div>
        <div class="meta">${esc(m.creator || m.original_filename)}</div>
        <div class="dims"><span>${dims(m)}</span>${m.triangles ? `<span>${Number(m.triangles).toLocaleString()} faces</span>` : ''}</div>
        ${m.tags?.length ? `<div class="tags">${tagsHtml(m.tags, true)}</div>` : ''}
      </div>
    </article>`;
}

function collectionById(id) { return state.collections.find(c => c.id === id); }
function collectionPath(id) {
  const out=[]; let c=collectionById(id); const seen=new Set();
  while(c && !seen.has(c.id)){ out.unshift(c); seen.add(c.id); c=c.parent_id?collectionById(c.parent_id):null; }
  return out;
}
function collectionPathLabel(c) { return collectionPath(c.id).map(x=>x.name).join(' / '); }
function collectionIsDescendant(candidateId, ancestorId) {
  let c=collectionById(candidateId); const seen=new Set();
  while(c && !seen.has(c.id)){ if(c.parent_id===ancestorId)return true; seen.add(c.id); c=c.parent_id?collectionById(c.parent_id):null; }
  return false;
}
function libraryQueryString() {
  const f = state.library;
  const p = new URLSearchParams();
  if (f.q) p.set('q', f.q);
  if (f.category) p.set('category', f.category);
  if (f.extension) p.set('extension', f.extension);
  if (f.status) p.set('status', f.status);
  if (f.favorite) p.set('favorite', 'true');
  if (f.tag) p.set('tag', f.tag);
  if (f.collectionId) p.set('collection_id', f.collectionId);
  if (f.unfiled) p.set('unfiled', 'true');
  p.set('sort', f.sort || 'newest');
  return p.toString();
}
function libraryGrid(models) {
  if (!models.length) return empty('No models match this view', state.library.unfiled ? 'Everything is already filed. Nice.' : 'Clear a filter, try a broader search, or add another model.', '<button class="ghost" data-library-filter="clear">Clear filters</button>');
  const cls = state.library.view === 'list' ? 'library-list' : 'grid';
  const visible = models.slice(0, state.library.visibleCount);
  const remaining = Math.max(0, models.length - visible.length);
  return `<div class="${cls}">${visible.map(modelCard).join('')}</div>${remaining ? `<div class="library-load-more"><span>Showing ${visible.length.toLocaleString()} of ${models.length.toLocaleString()} models</span><button class="ghost" data-load-more-models>Load ${Math.min(120, remaining)} more</button></div>` : models.length > 120 ? `<div class="library-load-more complete"><span>All ${models.length.toLocaleString()} models loaded</span></div>` : ''}`;
}
function activeFilterText() {
  const f = state.library;
  const collection = collectionById(f.collectionId);
  const location = f.unfiled ? 'Unfiled' : collection?.name;
  const parts = [location, f.category, f.extension ? f.extension.slice(1).toUpperCase() : '', f.status, f.favorite ? 'Favourites' : '', f.tag ? `#${f.tag}` : ''].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'All models';
}
function hasSavableFilters() {
  const f = state.library;
  return !!(f.q || f.category || f.extension || f.status || f.favorite || f.tag);
}
function libraryFilterSnapshot() {
  const { q, category, extension, status, favorite, tag, sort, unfiled } = state.library;
  return { q, category, extension, status, favorite, tag, sort, unfiled };
}
function collectionNode(c, depth=0) {
  const children=state.collections.filter(x=>x.parent_id===c.id).sort((a,b)=>(a.kind===b.kind?a.name.localeCompare(b.name):a.kind==='manual'?-1:1));
  return `<div class="collection-tree-node" style="--folder-depth:${depth}"><button class="collection-item ${state.library.collectionId===c.id?'active':''}" data-collection-id="${c.id}" ${c.kind==='manual'?`data-drop-collection="${c.id}"`:''}><span class="collection-icon">${c.kind==='smart'?'⌁':'▱'}</span><span class="grow"><strong>${esc(c.name)}</strong><small>${c.model_count||0} model${c.model_count===1?'':'s'}${c.child_count?` · ${c.child_count} subfolder${c.child_count===1?'':'s'}`:''}</small></span>${c.kind==='smart'?'<span class="smart-dot">Smart</span>':''}</button>${children.map(x=>collectionNode(x,depth+1)).join('')}</div>`;
}
function collectionRail() {
  const roots=state.collections.filter(c=>!c.parent_id);
  const folders=roots.filter(c=>c.kind==='manual').sort((a,b)=>a.name.localeCompare(b.name));
  const smart=roots.filter(c=>c.kind==='smart').sort((a,b)=>a.name.localeCompare(b.name));
  return `<aside class="collection-rail">
    <div class="collection-title"><span>Library</span><button class="icon-mini" data-new-collection title="New folder">＋</button></div>
    <button class="collection-item ${!state.library.collectionId&&!state.library.unfiled?'active':''}" data-collection-id=""><span class="collection-icon">◇</span><span class="grow"><strong>All models</strong><small>Everything in LayerVault</small></span></button>
    <button class="collection-item ${state.library.unfiled?'active':''}" data-library-special="unfiled"><span class="collection-icon">⌁</span><span class="grow"><strong>Unfiled</strong><small>Models not in a folder</small></span></button>
    ${folders.length?`<div class="collection-label">Folders</div>${folders.map(c=>collectionNode(c,0)).join('')}`:''}
    ${smart.length?`<div class="collection-label">Smart views</div>${smart.map(c=>collectionNode(c,0)).join('')}`:''}
    <button class="collection-create" data-new-collection>＋ New folder</button>
  </aside>`;
}
function libraryBreadcrumbsHtml() {
  if(state.library.unfiled) return `<nav class="library-breadcrumbs" aria-label="Library location"><button data-collection-id="">Library</button><span>›</span><strong>Unfiled</strong></nav>`;
  const path=collectionPath(state.library.collectionId);
  if(!path.length) return `<nav class="library-breadcrumbs root" aria-label="Library location"><strong>Library</strong><span>›</span><span>All models</span></nav>`;
  return `<nav class="library-breadcrumbs" aria-label="Library location"><button data-collection-id="">Library</button>${path.map((c,i)=>`${i?'<span>›</span>':'<span>›</span>'}${i===path.length-1?`<strong>${esc(c.name)}</strong>`:`<button data-collection-id="${c.id}">${esc(c.name)}</button>`}`).join('')}</nav>`;
}
function folderTilesHtml() {
  if(state.library.unfiled) return '';
  const parent=state.library.collectionId||null;
  const children=state.collections.filter(c=>(c.parent_id||null)===parent).sort((a,b)=>(a.kind===b.kind?a.name.localeCompare(b.name):a.kind==='manual'?-1:1));
  if(!children.length) return '';
  return `<div class="folder-section"><div class="folder-section-head"><strong>${parent?'Inside this folder':'Folders & views'}</strong><span>Drag model cards onto normal folders to file them quickly.</span></div><div class="folder-grid">${children.map(c=>`<button class="folder-tile ${c.kind==='smart'?'smart-folder-tile':''}" data-collection-id="${c.id}" ${c.kind==='manual'?`data-drop-collection="${c.id}"`:''}>${c.kind==='smart'?'<span class="smart-folder-glyph">⌁</span>':'<span class="folder-glyph"><i></i></span>'}<span class="grow"><strong>${esc(c.name)}</strong><small>${c.kind==='smart'?'Smart view · ':''}${c.model_count||0} model${c.model_count===1?'':'s'}${c.child_count?` · ${c.child_count} inside`:''}</small></span><span class="folder-arrow">›</span></button>`).join('')}</div></div>`;
}

function syncLibraryChipState() {
  $$('[data-library-filter]').forEach(b => {
    const key = b.dataset.libraryFilter;
    const value = b.dataset.value || '';
    let on = false;
    if (key === 'all') on = !state.library.favorite && !state.library.status && !state.library.tag;
    if (key === 'favorite') on = state.library.favorite;
    if (key === 'status') on = state.library.status === value;
    b.classList.toggle('active', on);
  });
}
async function renderLibrary(categoryPreset = '') {
  if (categoryPreset) state.library.category = categoryPreset;
  state.library.visibleCount = 120;
  [state.taxonomy, state.collections] = await Promise.all([api('/api/taxonomy'), api('/api/collections')]);
  state.models = await api(`/api/models?${libraryQueryString()}`);
  state.selectedIds = new Set([...state.selectedIds].filter(id => state.models.some(m => m.id === id)));
  const categories = state.taxonomy.categories;
  const selectedCollection = collectionById(state.library.collectionId);
  const title=state.library.unfiled?'Unfiled models':selectedCollection?.name||'Your printable library';
  const description=state.library.unfiled?'Models that are not currently inside any normal folder. Drag them onto a folder in the sidebar to organise them.':selectedCollection?.description||'Search, folder and curate every printable asset without digging through filesystem directories.';
  content.innerHTML = `
    <div class="page-intro library-intro">
      <div><span class="kicker">Catalogue</span><h2>${esc(title)}</h2><p>${esc(description)}</p></div>
      <div class="page-intro-actions">${selectedCollection ? `<button class="ghost" data-edit-collection>${selectedCollection.kind==='smart'?'Smart view settings':'Folder settings'}</button>` : ''}<button class="ghost" data-new-collection>＋ New folder</button><button class="ghost" data-action="scan-import">↻ Import folder</button><button class="primary" data-action="pick-upload">＋ Upload models</button></div>
    </div>
    <div class="library-layout">
      ${collectionRail()}
      <div class="library-main">
        ${libraryBreadcrumbsHtml()}
        ${folderTilesHtml()}
        <button class="drop-panel" data-action="pick-upload"><span class="drop-icon">⇩</span><span><strong>Drop models anywhere to import</strong><small>STL, OBJ, 3MF, STEP, G-code and supported archive files</small></span><span class="small-btn">Choose files</span></button>
        <div class="toolbar">
          <div class="search"><span>⌕</span><input id="librarySearch" value="${esc(state.library.q)}" placeholder="Search models, creators, filenames, tags or notes…"><kbd class="search-shortcut">/</kbd></div>
          <select id="categoryFilter" class="small-btn" aria-label="Category"><option value="">All categories</option>${categories.map(c => `<option value="${esc(c)}" ${c === state.library.category ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>
          <select id="typeFilter" class="small-btn" aria-label="File type"><option value="">All file types</option>${['.stl','.3mf','.obj','.step','.stp','.gcode','.bgcode','.ctb','.goo','.lys'].map(x => `<option value="${x}" ${x === state.library.extension ? 'selected' : ''}>${x.slice(1).toUpperCase()}</option>`).join('')}</select>
          <select id="sortFilter" class="small-btn" aria-label="Sort"><option value="newest" ${state.library.sort === 'newest' ? 'selected' : ''}>Newest</option><option value="name" ${state.library.sort === 'name' ? 'selected' : ''}>Name A–Z</option><option value="prints" ${state.library.sort === 'prints' ? 'selected' : ''}>Most printed</option><option value="size" ${state.library.sort === 'size' ? 'selected' : ''}>Largest file</option><option value="oldest" ${state.library.sort === 'oldest' ? 'selected' : ''}>Oldest</option></select>
          <div class="view-toggle"><button data-library-view="grid" class="${state.library.view === 'grid' ? 'active' : ''}" title="Grid view">▦</button><button data-library-view="list" class="${state.library.view === 'list' ? 'active' : ''}" title="List view">☷</button></div>
        </div>
        <div class="filter-row">
          <button class="filter-chip" data-library-filter="all">Any status</button><button class="filter-chip" data-library-filter="favorite">★ Favourites</button><button class="filter-chip" data-library-filter="status" data-value="Ready">Ready</button><button class="filter-chip" data-library-filter="status" data-value="Needs repair">Needs repair</button><button class="filter-chip" data-library-filter="status" data-value="Needs supports">Needs supports</button>
          ${state.library.tag ? `<button class="filter-chip active" data-library-filter="tag" data-value="${esc(state.library.tag)}">#${esc(state.library.tag)} ×</button>` : ''}
          ${hasSavableFilters() ? '<button class="filter-chip smart-save" data-save-smart>＋ Save as smart view</button>' : ''}
        </div>
        <div class="library-summary"><div><strong id="libraryCount">${state.models.length} model${state.models.length === 1 ? '' : 's'}</strong><span id="libraryContext">${esc(activeFilterText())}</span></div><label class="select-all"><input type="checkbox" id="selectAllModels" ${state.models.length && state.models.every(m => state.selectedIds.has(m.id)) ? 'checked' : ''}> Select all results</label></div>
        <div id="bulkBar">${bulkBarHtml()}</div>
        <div id="libraryGrid">${libraryGrid(state.models)}</div>
      </div>
    </div>`;
  syncLibraryChipState();
  $('#librarySearch').addEventListener('input', debounce(() => { state.library.q = $('#librarySearch').value.trim(); updateLibrary(); }, 180));
  $('#categoryFilter').addEventListener('change', e => { state.library.category = e.target.value; updateLibrary(); });
  $('#typeFilter').addEventListener('change', e => { state.library.extension = e.target.value; updateLibrary(); });
  $('#sortFilter').addEventListener('change', e => { state.library.sort = e.target.value; updateLibrary(); });
  $('#selectAllModels')?.addEventListener('change', e => { state.models.forEach(m => e.target.checked ? state.selectedIds.add(m.id) : state.selectedIds.delete(m.id)); refreshSelectionUI(); });
}
function bulkBarHtml() {
  const n = state.selectedIds.size;
  if (!n) return '';
  const current = collectionById(state.library.collectionId);
  return `<div class="bulk-bar"><strong>${n} selected</strong><span class="bulk-divider"></span><button data-bulk-action="favorite">★ Favourite</button><button data-bulk-action="category">Category</button><button data-bulk-action="status">Status</button><button data-bulk-action="tags">Tags</button><button data-bulk-action="collection">Add to folder</button>${current?.kind === 'manual' ? '<button data-bulk-action="remove-collection">Remove from this folder</button>' : ''}<span class="grow"></span><button data-clear-selection>Clear</button><button class="danger-link" data-bulk-action="delete">Delete</button></div>`;
}
function refreshSelectionUI() {
  $$('.model-card').forEach(card => { const on=state.selectedIds.has(card.dataset.modelId); card.classList.toggle('selected',on); const cb=$('[data-select-model]',card); if(cb) cb.checked=on; });
  if ($('#bulkBar')) $('#bulkBar').innerHTML=bulkBarHtml();
  if ($('#selectAllModels')) $('#selectAllModels').checked=!!state.models.length && state.models.every(m => state.selectedIds.has(m.id));
}
async function updateLibrary() {
  state.library.visibleCount = 120;
  state.models = await api(`/api/models?${libraryQueryString()}`);
  state.selectedIds = new Set([...state.selectedIds].filter(id => state.models.some(m => m.id === id)));
  const grid = $('#libraryGrid'); if (grid) grid.innerHTML = libraryGrid(state.models);
  if ($('#libraryCount')) $('#libraryCount').textContent = `${state.models.length} model${state.models.length === 1 ? '' : 's'}`;
  if ($('#libraryContext')) $('#libraryContext').textContent = activeFilterText();
  if ($('#bulkBar')) $('#bulkBar').innerHTML = bulkBarHtml();
  syncLibraryChipState(); refreshSelectionUI();
}

function folderParentOptions(excludeId='') {
  return [{value:'',label:'Top level'},...state.collections.filter(c=>c.kind==='manual'&&c.id!==excludeId&&!collectionIsDescendant(c.id,excludeId)).sort((a,b)=>collectionPathLabel(a).localeCompare(collectionPathLabel(b))).map(c=>({value:c.id,label:collectionPathLabel(c)}))];
}
function newCollectionModal(kind = 'manual') {
  const smart = kind === 'smart';
  const current=collectionById(state.library.collectionId);
  const defaultParent=current?.kind==='manual'?current.id:(current?.parent_id||'');
  openModal(smart ? 'Save smart view' : 'New folder', `<form id="collectionForm" class="fields">${field('name','Name','','text','wide',smart ? 'e.g. Resin miniatures needing supports' : 'e.g. D&D / Fey')}${selectField('parent_id','Parent folder',folderParentOptions(),defaultParent,'wide')}<div class="field wide"><label>Description</label><textarea name="description" placeholder="Optional note about what belongs here"></textarea></div>${smart ? `<div class="field wide"><label>Saved rules</label><div class="smart-rule-preview">${esc(activeFilterText())}<small>LayerVault keeps this view updated automatically as models change.</small></div></div>` : '<div class="field wide"><div class="folder-help">Folders can contain models, subfolders and smart views. A model can also appear in more than one folder.</div></div>'}</form>`, `<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="saveCollectionBtn">${smart ? 'Save smart view' : 'Create folder'}</button>`, smart ? 'Smart view' : 'Library folder');
  $('#saveCollectionBtn').onclick = async e => { const btn=e.currentTarget, original=btn.textContent; btn.disabled=true; btn.classList.add('busy'); btn.textContent='Saving…'; try { const d=formDataObject($('#collectionForm')); d.kind=kind; d.parent_id=d.parent_id||null; if(smart)d.filter=libraryFilterSnapshot(); const c=await api('/api/collections',jsonOpt('POST',d)); toast(`${smart ? 'Smart view' : 'Folder'} created`); closeModal(); state.library.unfiled=false; state.library.collectionId=c.id; renderLibrary(); } catch(err) { toast(err.message||'Could not create folder',true); } finally { if(btn.isConnected){btn.disabled=false;btn.classList.remove('busy');btn.textContent=original;} } };
}
async function editCollectionModal() {
  const c=collectionById(state.library.collectionId); if(!c)return;
  const noun=c.kind==='smart'?'Smart view':'Folder';
  openModal(`${noun} settings`, `<form id="collectionEdit" class="fields">${field('name','Name',c.name,'text','wide')}${selectField('parent_id','Parent folder',folderParentOptions(c.id),c.parent_id||'','wide')}<div class="field wide"><label>Description</label><textarea name="description">${esc(c.description||'')}</textarea></div>${c.kind==='smart'?`<div class="field wide"><label>Type</label><div class="smart-rule-preview">Smart view<small>Its contents are generated from saved filters.</small></div></div>`:''}</form>`, `<button class="danger" id="deleteCollectionBtn">Delete ${c.kind==='smart'?'view':'folder'}</button><button class="primary" id="saveCollectionEditBtn">Save</button>`, noun);
  $('#saveCollectionEditBtn').onclick=async e=>{const btn=e.currentTarget,original=btn.textContent;btn.disabled=true;btn.classList.add('busy');btn.textContent='Saving…';try{const d=formDataObject($('#collectionEdit'));d.parent_id=d.parent_id||null;await api(`/api/collections/${c.id}`,jsonOpt('PATCH',d));toast(`${noun} updated`);closeModal();renderLibrary();}catch(err){toast(err.message||`Could not update ${noun.toLowerCase()}`,true);}finally{if(btn.isConnected){btn.disabled=false;btn.classList.remove('busy');btn.textContent=original;}}};
  $('#deleteCollectionBtn').onclick=async()=>{if(!(await confirmAction(`Delete ${noun.toLowerCase()}?`, `“${c.name}” will be removed. Models stay safely in your library${c.child_count?' and its subfolders move up one level':''}.`)))return;try{await api(`/api/collections/${c.id}`,{method:'DELETE'});state.library.collectionId=c.parent_id||'';closeModal();toast(`${noun} deleted`);renderLibrary();}catch(err){toast(err.message||`Could not delete ${noun.toLowerCase()}`,true);}};
}

async function bulkActionModal(action) {
  const ids=[...state.selectedIds]; if(!ids.length)return;
  if(action==='delete'){if(!(await confirmAction('Delete selected models?', `${ids.length} selected model${ids.length===1?'':'s'} and their stored files will be permanently removed.`)))return;await api('/api/models/bulk',jsonOpt('POST',{ids,action:'delete'}));state.selectedIds.clear();toast('Selected models deleted');return renderLibrary();}
  if(action==='favorite'){await api('/api/models/bulk',jsonOpt('POST',{ids,updates:{favorite:true}}));toast('Added to favourites');return updateLibrary();}
  if(action==='remove-collection'){await api(`/api/collections/${state.library.collectionId}/models`,jsonOpt('DELETE',{model_ids:ids}));state.selectedIds.clear();toast('Removed from folder');return renderLibrary();}
  if(action==='collection'){
    const choices=state.collections.filter(c=>c.kind==='manual');
    if(!choices.length)return newCollectionModal('manual');
    openModal('Add to folder',`<div class="field"><label>Folder</label><select id="bulkCollection">${choices.sort((a,b)=>collectionPathLabel(a).localeCompare(collectionPathLabel(b))).map(c=>`<option value="${c.id}">${esc(collectionPathLabel(c))}</option>`).join('')}</select></div>`,`<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="applyBulkCollection">File ${ids.length} model${ids.length===1?'':'s'}</button>`,'Bulk action');
    $('#applyBulkCollection').onclick=async()=>{await api(`/api/collections/${$('#bulkCollection').value}/models`,jsonOpt('POST',{model_ids:ids}));toast('Added to folder');closeModal();state.collections=await api('/api/collections');renderLibrary();}; return;
  }
  if(action==='category'||action==='status'){
    const values=action==='category'?[...new Set(['Unsorted','Miniatures','Terrain','Functional','Props','Parts','Tools',...state.taxonomy.categories])]:['Ready','Needs repair','Needs supports','Printed','Archived'];
    openModal(`Set ${action}`,`<div class="field"><label>${action==='category'?'Category':'Status'}</label><select id="bulkValue">${values.map(v=>`<option>${esc(v)}</option>`).join('')}</select></div>`,`<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="applyBulkValue">Apply to ${ids.length}</button>`,'Bulk action');
    $('#applyBulkValue').onclick=async()=>{await api('/api/models/bulk',jsonOpt('POST',{ids,updates:{[action]:$('#bulkValue').value}}));toast(`${action[0].toUpperCase()+action.slice(1)} updated`);closeModal();updateLibrary();}; return;
  }
  if(action==='tags'){
    openModal('Add tags',`${field('bulk_tags','Tags to add','','text','wide','miniature, campaign, painted')}`,`<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="applyBulkTags">Add tags</button>`,'Bulk action');
    $('#applyBulkTags').onclick=async()=>{await api('/api/models/bulk',jsonOpt('POST',{ids,add_tags:$('[name=bulk_tags]').value}));toast('Tags added');closeModal();updateLibrary();};
  }
}

async function renderProjects() {
  [state.projects,state.models] = await Promise.all([api('/api/projects'),api('/api/models')]);
  content.innerHTML = `
    <div class="page-intro">
      <div><span class="kicker">Build planning</span><h2>Projects</h2><p>Keep multi-part prints, variants and deadlines together as one build.</p></div>
      <div class="page-intro-actions"><button class="primary" data-action="new-project">＋ New project</button></div>
    </div>
    ${state.projects.length ? `<div class="grid three">${state.projects.map(p => `
      <article class="card project-card" data-project-id="${p.id}" tabindex="0" aria-label="Open project ${esc(p.name)}">
        ${p.model_ids?.length ? `<div class="project-thumbs">${p.model_ids.map(mid=>{const mm=state.models.find(m=>m.id===mid);return mm?`<img ${lazyThumbAttrs(mm, mm.title)} onerror="this.remove()">`:''}).join('')}<span>${p.model_count || 0} part${p.model_count===1?'':'s'}</span></div>` : ''}
        <div class="project-top">
          <div><h3>${esc(p.name)}</h3><span class="muted" style="font-size:9px">${p.model_count || 0} linked model${p.model_count === 1 ? '' : 's'}</span></div>
          <span class="status ${statusClass(p.status)}">${esc(p.status)}</span>
        </div>
        <p>${esc(p.description || 'Add a description so future-you remembers the plan for this build.')}</p>
        <div class="split" style="margin-top:12px"><span class="muted" style="font-size:9px">${p.due_date ? `Target ${fmtDate(p.due_date)}` : `Updated ${fmtDate(p.updated_at)}`}</span>${p.tags?.length ? `<div class="tags" style="margin:0">${tagsHtml(p.tags)}</div>` : ''}</div>
      </article>`).join('')}</div>` : empty('No projects yet', 'Create a project for a miniature set, terrain build, prop, cosplay part or functional print.', '<button class="primary" data-action="new-project">Create project</button>')}`;
}

async function renderMaterials() {
  state.materials=await api('/api/materials');
  const totalValue=state.materials.reduce((n,m)=>n+Number(m.remaining_value||0),0), low=state.materials.filter(m=>m.low_stock).length;
  content.innerHTML=`<div class="page-intro"><div><span class="kicker">Physical consumables</span><h2>Materials & stock</h2><p>Track each real bottle or spool, import open material data, and keep recommended starting profiles separate from settings proven by your own prints.</p></div><div class="page-intro-actions"><button class="ghost catalog-launch" data-action="material-catalog">⌕ Search material catalogue</button><a class="ghost button-link" href="/api/export/materials.csv">Export CSV</a><button class="primary" data-action="new-material">＋ Add manually</button></div></div>
    <div class="source-strip"><span>Material sources</span>${sourceBadge('manufacturer_resin')}${sourceBadge('spoolman')}${sourceBadge('openresin')}<small>Official vendor artwork and colour chips stay alongside open specifications and printer-specific resin profiles.</small></div>
    <div class="inventory-stats"><div><small>Stock items</small><strong>${state.materials.length}</strong><span>physical bottles / spools</span></div><div><small>Low stock</small><strong>${low}</strong><span>below 20%</span></div><div><small>Remaining value</small><strong>${money(totalValue)}</strong><span>based on purchase cost</span></div></div>
    ${state.materials.length?`<div class="grid three material-inventory-grid">${state.materials.map(m=>{const pct=m.remaining_percent??0, hasPhoto=m.has_custom_image||m.has_source_image||m.source_image_url;return `<article class="card material-card ${m.low_stock?'low-stock-card':''} ${hasPhoto?'has-photo':''}" data-material-open="${m.id}" tabindex="0">${hasPhoto?`<div class="material-media has-image">${materialImageTag(m)}<div class="material-media-fallback" style="--material-color:${esc(m.color_hex||'#808080')}"></div>${m.has_custom_image?'<span class="custom-photo-pill">Your photo</span>':'<span class="source-photo-pill">Official product</span>'}</div>`:''}<div class="material-top"><div><div class="material-source-row"><span class="inventory-code">${esc(m.inventory_code)}</span>${sourceBadge(m.source_provider)}</div><h3>${esc(m.name)}</h3><span class="muted">${esc([m.brand,m.material,m.color].filter(Boolean).join(' · ')||m.kind)}</span></div><div class="swatch" title="${esc(m.color||'Recorded colour')}" style="background:${esc(m.color_hex||'#808080')}"></div></div><div class="material-status-row"><span class="status ${statusClass(m.stock_status)}">${esc(m.stock_status)}</span>${m.low_stock?'<span class="low-stock-pill">Low stock</span>':''}<span>${pct.toFixed(0)}%</span></div><div class="progress"><span style="width:${Math.max(0,Math.min(100,pct))}%"></span></div><div class="material-details"><span><b>${Number(m.remaining_amount).toFixed(1)}</b> ${esc(m.unit)} remaining</span><span>${m.remaining_value!=null?money(m.remaining_value):'Cost not set'}</span></div>${materialSpecsHtml(m.specs,3)}<div class="material-kpis"><span><b>${m.print_attempts||0}</b> print attempts</span><span><b>${m.avg_rating?Number(m.avg_rating).toFixed(1):'—'}</b> avg rating</span></div><div class="split"><span class="muted">${esc(m.location||m.batch_lot||'No location')}</span><div class="mini-actions"><button class="small-btn" data-use-material="${m.id}">Adjust</button><button class="small-btn" data-material-qr="${m.id}">QR</button></div></div></article>`}).join('')}</div>`:empty('No physical stock tracked','Search an open catalogue or add each resin bottle / filament spool manually.','<button class="primary" data-action="material-catalog">Search material catalogue</button>')}`;
}

async function renderPrinters() {
  [state.printers,state.profiles]=await Promise.all([api('/api/printers'),api('/api/profiles')]); const active=state.printers.filter(p=>p.printer_status==='Active'); const totalHours=state.printers.reduce((a,p)=>a+Number(p.print_hours||0),0); const best=[...state.profiles].filter(p=>p.avg_rating).sort((a,b)=>(b.avg_rating||0)-(a.avg_rating||0)||(b.success_rate||0)-(a.success_rate||0))[0];
  content.innerHTML=`<div class="page-intro"><div><span class="kicker">Hardware inventory</span><h2>Your printers</h2><p>Keep every owned machine, exact build volume, resin display resolution, service state and proven recipe together.</p></div><div class="page-intro-actions"><button class="ghost catalog-launch" data-action="printer-catalog">⌕ Search printer catalogue</button><button class="primary" data-action="new-printer">＋ Add manually</button></div></div>
    <div class="source-strip"><span>Open printer artwork & data</span>${sourceBadge('orca')}${sourceBadge('dragonfruit')}${sourceBadge('uvtools')}<small>Bundled Orca and DragonFruit printer images populate matching machines automatically. Open FDM and resin profile data remains searchable and editable.</small></div>
    <div class="inventory-stats"><div><small>Owned printers</small><strong>${state.printers.length}</strong><span>${active.length} active</span></div><div><small>FDM</small><strong>${state.printers.filter(p=>techFamily(p.technology)==='FDM').length}</strong><span>filament machines</span></div><div><small>Resin</small><strong>${state.printers.filter(p=>techFamily(p.technology)==='Resin').length}</strong><span>MSLA / SLA / DLP</span></div><div><small>Logged runtime</small><strong>${totalHours.toFixed(1)}h</strong><span>finished attempts</span></div></div>
    ${state.printers.length?`<div class="grid three printer-inventory-grid">${state.printers.map(p=>{const specs=printerSpecs(p);return `<article class="card printer-card printer-card-rich" data-printer-open="${p.id}" tabindex="0"><div class="printer-media ${(p.has_custom_image||p.source_image_url)?'has-image':''}">${printerImageTag(p)}<div class="printer-media-fallback"><span>${techFamily(p.technology)==='Resin'?'◫':'⌂'}</span><small>${esc(p.manufacturer||techFamily(p.technology))}</small></div>${p.has_custom_image?'<span class="custom-photo-pill">Your photo</span>':''}<div class="printer-media-badges">${sourceBadge(p.source_provider)}<span class="tech-badge">${esc(techFamily(p.technology))}</span></div></div><div class="printer-card-body"><div class="printer-top"><div><span class="inventory-code">${esc(p.inventory_code)}</span><h3>${esc(p.name)}</h3><span class="muted">${esc([p.manufacturer,p.model].filter(Boolean).join(' · ')||'Generic printer')}</span></div><span class="status ${statusClass(p.printer_status)}">${esc(p.printer_status)}</span></div>${specs.length?`<div class="printer-spec-chips">${specs.map(x=>`<span>${esc(x)}</span>`).join('')}</div>`:''}<div class="printer-kpis"><span><b>${p.print_attempts||0}</b>logged prints</span><span><b>${p.success_rate!=null?`${p.success_rate}%`:'—'}</b>success</span><span><b>${p.avg_rating?Number(p.avg_rating).toFixed(1):'—'}</b>avg rating</span></div><div class="split"><span class="muted">${esc(p.location||'Location not set')}</span><button class="small-btn" data-printer-open="${p.id}">Manage</button></div></div></article>`}).join('')}</div>`:empty('No printers in inventory','Search the open printer catalogue to pull in machine dimensions/resolution, or add a printer manually.','<button class="primary" data-action="printer-catalog">Search printer catalogue</button>')}
    <div class="section-head"><div><h2>Print profiles</h2><p>Reusable starting recipes. Every print job keeps its own permanent settings snapshot.</p></div><button class="small-btn" data-action="new-profile">＋ New profile</button></div>${state.profiles.length?`<div class="profile-grid">${state.profiles.map(p=>{const pr=state.printers.find(x=>x.id===p.printer_id);return `<article class="profile-card ${best?.id===p.id?'best-profile':''}" data-profile-open="${p.id}" tabindex="0"><div class="profile-card-head"><div><div class="profile-label-row"><span class="tech-badge">${esc(techFamily(p.technology))}</span>${p.profile_origin==='Recommended'?'<span class="recommended-pill">Recommended</span>':''}${sourceBadge(p.source_provider)}${best?.id===p.id?'<span class="best-profile-pill">Best performer</span>':''}</div><h3>${esc(p.name)}</h3><small>${esc(pr?.name||'Any printer')} · ${esc(p.material||'Any material')}</small></div><button class="icon-btn" data-delete-profile="${p.id}" title="Delete profile">×</button></div>${settingsSummary(p.settings,p.technology,4)?`<div class="recipe-mini">${settingsSummary(p.settings,p.technology,4)}</div>`:'<p class="muted">No structured recipe values yet.</p>'}<div class="profile-performance"><span>${p.job_count||0} jobs</span><span>${p.avg_rating?`${Number(p.avg_rating).toFixed(1)} ★ avg`:'Not rated yet'}</span><span>${p.success_rate!=null?`${p.success_rate}% success`:''}</span></div><button class="small-btn full" data-profile-open="${p.id}">Edit recipe</button></article>`}).join('')}</div>`:empty('No saved profiles','Save a structured resin or FDM recipe when you find settings worth repeating.')}`;
}

async function renderJobs() {
  await refreshCore(); const all=state.jobs; const q=state.jobQuery.trim().toLowerCase(); const shown=all.filter(j=>(!state.jobStatus||j.status===state.jobStatus)&&(!state.jobPrinter||j.printer_id===state.jobPrinter)&&(!state.jobMaterial||j.material_id===state.jobMaterial)&&(!q||[j.name,j.model_title,j.printer_name,j.material_name,j.notes].some(v=>String(v||'').toLowerCase().includes(q)))); const complete=all.filter(j=>j.status==='Complete'),failed=all.filter(j=>j.status==='Failed'),active=all.filter(j=>['Queued','Printing'].includes(j.status));const rated=all.filter(j=>j.result_rating);const avg=rated.length?rated.reduce((a,j)=>a+Number(j.result_rating),0)/rated.length:0;const cost=all.filter(j=>['Complete','Failed'].includes(j.status)).reduce((a,j)=>a+Number(j.material_cost||0),0);
  content.innerHTML=`<div class="page-intro"><div><span class="kicker">Print Lab</span><h2>Queue, recipes & results</h2><p>Keep the exact settings, physical material, printer, outcome and cost behind every attempt.</p></div><div class="page-intro-actions"><a class="ghost button-link" href="/api/export/print-history.csv">Export CSV</a><button class="primary" data-action="new-job">＋ Log print job</button></div></div><div class="result-stats"><div><small>Active queue</small><strong>${active.length}</strong><span>${all.filter(j=>j.status==='Printing').length} printing now</span></div><div><small>Completed</small><strong>${complete.length}</strong><span>successful prints</span></div><div><small>Success rate</small><strong>${complete.length+failed.length?Math.round(complete.length/(complete.length+failed.length)*100):0}%</strong><span>${failed.length} failed attempt${failed.length===1?'':'s'}</span></div><div><small>Average rating</small><strong>${avg?avg.toFixed(1):'—'}</strong><span>${rated.length} rated attempts</span></div><div><small>Material cost</small><strong>${money(cost)}</strong><span>logged finished attempts</span></div></div>
    <div class="lab-filterbar"><input id="jobSearch" value="${esc(state.jobQuery)}" placeholder="Search jobs, models, printers…"><select id="jobPrinterFilter"><option value="">All printers</option>${state.printers.map(p=>`<option value="${p.id}" ${state.jobPrinter===p.id?'selected':''}>${esc(p.name)}</option>`).join('')}</select><select id="jobMaterialFilter"><option value="">All materials</option>${state.materials.map(m=>`<option value="${m.id}" ${state.jobMaterial===m.id?'selected':''}>${esc(m.inventory_code)} · ${esc(m.name)}</option>`).join('')}</select></div><div class="history-tabs">${['','Queued','Printing','Complete','Failed'].map(v=>`<button class="${state.jobStatus===v?'active':''}" data-job-filter="${v}">${v||'All'} <span>${v?all.filter(j=>j.status===v).length:all.length}</span></button>`).join('')}</div>${shown.length?`<div class="print-history-grid">${shown.map(jobResultCard).join('')}</div>`:empty('Nothing in this view','Change the filters or log a new print job.','<button class="primary" data-action="new-job">Log print job</button>')}`;
  $('#jobSearch')?.addEventListener('input',debounce(e=>{state.jobQuery=e.target.value;renderJobs()},250)); $('#jobPrinterFilter')?.addEventListener('change',e=>{state.jobPrinter=e.target.value;renderJobs()}); $('#jobMaterialFilter')?.addEventListener('change',e=>{state.jobMaterial=e.target.value;renderJobs()});
}
function ratingStars(n=0){return `<span class="rating-stars" aria-label="${n||0} out of 5">${[1,2,3,4,5].map(x=>`<i class="${x<=Number(n||0)?'on':''}">★</i>`).join('')}</span>`;}
function jobResultCard(j){const done=['Complete','Failed'].includes(j.status),date=j.completed_at||j.started_at||j.created_at,recipe=settingsSummary(j.settings_snapshot,j.technology||j.printer_technology,3);return `<article class="print-result-card" data-job-id="${j.id}" tabindex="0"><div class="result-media ${j.result_photo?'has-photo':''}">${j.result_photo?`<img loading="lazy" src="/api/jobs/${j.id}/photo" alt="Print result for ${esc(j.name)}">`:`<div class="result-placeholder"><span>${j.status==='Complete'?'✓':j.status==='Failed'?'!':'▷'}</span><small>${done?'Add a result photo':'Print queued'}</small></div>`}<span class="status ${statusClass(j.status)}">${esc(j.status)}</span><span class="tech-float">${esc(techFamily(j.technology||j.printer_technology))}</span></div><div class="result-body"><div class="result-title"><div><h3>${esc(j.name)}</h3><small>${fmtDate(date)}</small></div>${done?ratingStars(j.result_rating):''}</div><div class="result-model"><strong>${esc(j.model_title||'No model linked')}</strong><span>${esc([j.printer_name,j.material_inventory_code,j.material_name].filter(Boolean).join(' · ')||'Print setup not fully recorded')}</span></div>${recipe?`<div class="recipe-mini">${recipe}</div>`:''}<div class="result-metrics">${j.duration_minutes?`<span><b>${Math.floor(j.duration_minutes/60)}h ${j.duration_minutes%60}m</b>duration</span>`:''}${j.material_used!=null?`<span><b>${Number(j.material_used).toFixed(1)}${esc(j.material_unit||'')}</b>material used</span>`:''}${j.material_cost!=null?`<span><b>${money(j.material_cost)}</b>material cost</span>`:''}</div>${j.failure_tags?.length?`<div class="failure-tags">${j.failure_tags.slice(0,3).map(x=>`<span>${esc(x)}</span>`).join('')}</div>`:''}${(j.failure_reason||j.notes)?`<p>${esc(j.failure_reason||j.notes)}</p>`:''}<div class="result-actions"><button class="small-btn" data-job-open="${j.id}">${done?'View result':'Edit job'}</button><button class="small-btn" data-job-repeat="${j.id}" title="Create a new queued job with this same setup and recipe">Repeat</button>${!done?`<button class="small-btn" data-job-status="${j.id}">Advance</button>`:''}</div></div></article>`;}

let viewer = {
  renderer:null, scene:null, camera:null, controls:null, transform:null, root:null,
  selection:new Set(), objects:new Map(), helpers:null, animation:null, observer:null,
  design:null, history:[], historyIndex:-1, dirty:false, saveTimer:null, generation:0,
  raycaster:null, pointer:null, mode:'translate', dragging:false, dragDepth:0,
  groupPreviews:new Map(), selectionPivot:null, selectionTransform:null,
  resizeAnchor:null, resizeDrag:null, handleResize:null, surfaceMove:null, marquee:null,
  alignmentMode:false, alignmentTarget:null, cameraModifier:false, clipboard:null
};

const cadClone = value => JSON.parse(JSON.stringify(value));
const cadId = prefix => `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
const cadPrimitiveMeta = {
  box:['Box','▣',[20,20,20]], cylinder:['Cylinder','●',[20,20,20]], sphere:['Sphere','◉',[20,20,20]],
  cone:['Cone','▲',[20,20,20]], wedge:['Wedge','◩',[24,16,20]], pyramid:['Pyramid','△',[20,20,20]],
  hex:['Hex prism','⬡',[20,20,20]], star:['Star','★',[24,5,24]], torus:['Torus','◎',[24,7,24]], ring:['Tube','◌',[20,14,20]],
  d4:['D4','4',[20,20,20]], d8:['D8','8',[20,20,20]],
  d10:['D10','10',[20,26,20]], d12:['D12','12',[20,20,20]], d20:['D20','20',[20,20,20]],
  text:['Text','T',[36,3,12]]
};
const cadTextFonts={classic:'Classic block',bold:'Heavy block',condensed:'Condensed'};

function cadPrintableText(value){const cleaned=String(value??'TEXT').toUpperCase().replace(/[^A-Z0-9 .,!?:+\-_\/]/g,'').replace(/\s+/g,' ').trim().slice(0,18).trim();return cleaned||'TEXT';}

function defaultWorkshopDocument() {
  return {schema:1,units:'mm',objects:[],grid:{size_mm:1,snap:true,visible:true},camera:{}};
}

function newWorkshopObject(kind, model=null) {
  const meta=cadPrimitiveMeta[kind]||['Library part','◆',[20,20,20]];
  const size=kind==='model'
    ? [Number(model?.width_mm)||20,Number(model?.depth_mm)||20,Number(model?.height_mm)||20]
    : [...meta[2]];
  return {
    id:cadId('part'),kind,name:kind==='model'?(model?.title||'Library part'):meta[0],model_id:model?.id||null,
    operation:'solid',color:'#67bea9',visible:true,locked:false,group_id:null,
    position:[0,size[1]/2,0],rotation:[0,0,0],scale:[1,1,1],size,
    params:{segments:32,top_radius_ratio:kind==='cone'?0:1,...(kind==='text'?{text:'TEXT',font:'classic'}:{})}
  };
}

async function renderWorkshop() {
  disposeViewer();
  [state.models,state.workshopDesigns]=await Promise.all([api('/api/models'),api('/api/workshop/designs')]);
  if (state.workshopModelId) {
    const base=state.models.find(m=>m.id===state.workshopModelId);
    if (base) {
      const created=await api('/api/workshop/designs',jsonOpt('POST',{name:`${base.title} — Workshop`,base_model_id:base.id}));
      state.workshopDesignId=created.id;
    }
    state.workshopModelId=null;
  }
  if (!state.workshopDesignId || !state.workshopDesigns.some(d=>d.id===state.workshopDesignId)) {
    state.workshopDesignId=state.workshopDesigns[0]?.id||null;
  }
  if (!state.workshopDesignId) {
    const created=await api('/api/workshop/designs',jsonOpt('POST',{name:'Untitled design',document:defaultWorkshopDocument()}));
    state.workshopDesignId=created.id;
  }
  const design=await api(`/api/workshop/designs/${state.workshopDesignId}`);
  state.workshopDesigns=await api('/api/workshop/designs');
  viewer.design=design;
  viewer.history=[cadClone(design.document)]; viewer.historyIndex=0;
  content.innerHTML=workshopShellHtml(design);
  bindWorkshopUI();
  requestAnimationFrame(initWorkshopViewer);
}

function workshopShellHtml(design) {
  const objects=design.document.objects||[];
  return `<div class="workshop-cad" data-workshop-design="${esc(design.id)}">
    <header class="cad-header">
      <div class="cad-design-switcher"><label><span>My designs</span><select id="cadDesignSelect">${state.workshopDesigns.map(d=>`<option value="${d.id}" ${d.id===design.id?'selected':''}>${esc(d.name)} · ${d.object_count} parts</option>`).join('')}</select></label><button class="cad-icon-action" data-cad-action="new-design" title="Create a new editable design">＋</button></div>
      <div class="cad-title-block"><span class="kicker">Workshop CAD · editable design</span><input id="cadDesignName" value="${esc(design.name)}" maxlength="120" aria-label="Design name"><span id="cadSaveState" class="cad-save-state">Saved · revision ${design.revision}</span></div>
      <div class="cad-header-actions"><button class="ghost" data-cad-action="save">Save</button><button class="primary" data-cad-action="export">Export & check printability</button></div>
    </header>
    <div class="cad-app">
      <main class="cad-stage-wrap">
        <div class="cad-toolbar" role="toolbar" aria-label="Workshop tools">
          <div class="cad-toolset cad-history-tools"><button data-cad-action="undo" title="Undo (Ctrl+Z)">↶ <span>Undo</span></button><button data-cad-action="redo" title="Redo (Ctrl+Y)">↷ <span>Redo</span></button></div>
          <i></i><div class="cad-toolset cad-mode-tools"><button class="active" data-cad-mode="translate" title="Move (M)">↔ <span>Move</span></button><button data-cad-mode="rotate" title="Rotate (R)">⟳ <span>Rotate</span></button><button data-cad-mode="scale" title="Resize (S)">⤢ <span>Resize</span></button></div>
          <i></i><div class="cad-toolset"><button data-cad-action="duplicate" title="Duplicate (Ctrl+D)">⧉ <span>Duplicate</span></button><button data-cad-action="delete" title="Delete selected">⌫ <span>Delete</span></button><button data-cad-action="align" title="Align selected objects (L)">⫶ <span>Align</span></button><button data-cad-action="group" title="Group selected objects">▦ <span>Group</span></button><button data-cad-action="ungroup" title="Ungroup selected objects">▤ <span>Ungroup</span></button></div>
          <span class="cad-toolbar-spacer"></span><div class="cad-toolset"><button data-cad-action="drop" title="Drop selection to workplane">⇩ <span>Drop</span></button><button data-cad-action="fit" title="Fit everything in view">⌗ <span>Fit all</span></button></div>
        </div>
        <div class="cad-stage" id="cadStage">
          <div class="viewer-empty" id="viewerEmpty"><div><strong>Preparing Workshop…</strong><span>Loading the local 3D design engine.</span></div></div>
          <div class="cad-start-hint ${objects.length?'hidden':''}" id="cadEmptyHint"><span class="cad-start-shape">▣</span><strong>Start with a shape</strong><small>Drag a shape here from the right, or click one to place it in the centre.</small></div>
          <div class="cad-drop-hint" id="cadDropHint"><strong>Place shape on the workplane</strong><small>Release to add it at this position</small></div>
          <div class="cad-view-tools" aria-label="Camera controls"><button data-cad-view="home" title="Home view">⌂</button><button data-cad-view="top">Top</button><button data-cad-view="front">Front</button><button data-cad-view="right">Right</button><i></i><button data-cad-zoom="in" title="Zoom in">＋</button><button data-cad-zoom="out" title="Zoom out">−</button></div>
          <div class="cad-dimension-overlay hidden" id="cadDimensionOverlay" aria-label="Selected object dimensions"></div>
          <div class="cad-selection-marquee hidden" id="cadSelectionMarquee" aria-hidden="true"></div>
          <div class="cad-selection-hud hidden" id="cadSelectionHud"></div>
        </div>
        <div class="cad-statusbar"><span id="cadSelectionStatus">${objects.length?`${objects.length} part${objects.length===1?'':'s'} · click or drag-box to select`:'Add a shape to begin'}</span><span class="cad-shortcuts">Drag-box selects · Ctrl + drag orbits · Ctrl+C / V copies · Ctrl+Z undoes</span><label><input id="cadSnap" type="checkbox" ${design.document.grid?.snap!==false?'checked':''}> Snap grid</label><select id="cadGridSize" aria-label="Grid size"><option value="0.5">0.5 mm</option><option value="1" ${Number(design.document.grid?.size_mm||1)===1?'selected':''}>1 mm</option><option value="2">2 mm</option><option value="5">5 mm</option><option value="10">10 mm</option></select><span>mm</span></div>
      </main>
      <aside class="cad-inspector cad-right-dock">
        <section class="cad-palette">
          <div class="cad-panel-head"><strong>Basic shapes</strong><small>Drag or click to add</small></div>
          <div class="cad-shape-grid">${Object.entries(cadPrimitiveMeta).map(([kind,[label]])=>`<button draggable="true" data-cad-add="${kind}" title="Drag ${label} onto the workplane or click to add"><span class="cad-shape-preview shape-${kind}" aria-hidden="true"><i>${kind.startsWith('d')?label:kind==='text'?'T':''}</i></span><b>${label}</b><small>${kind==='text'?'Type to edit':kind.startsWith('d')?'Dice blank':'Solid'}</small></button>`).join('')}</div>
          <div class="cad-library-add"><div class="cad-panel-head"><strong>Your models</strong><small>From the library</small></div>${modelSearchPickerHtml('cadLibrary',state.models.filter(previewable),'Search stored models…')}<button class="ghost full" id="cadLibraryAddBtn" data-cad-action="add-library" disabled>＋ Add selected model</button></div>
        </section>
        <details class="cad-object-drawer" open><summary><span>Objects</span><small id="cadObjectCount">${objects.length}</small></summary><div id="cadObjectList" class="cad-object-list"></div></details>
        <section id="cadInspectorPanel"><div class="cad-panel-head"><strong>Shape</strong><small>Exact size & position</small></div><div id="cadInspectorBody"></div></section>
        <section class="cad-readiness" id="cadReadiness"></section>
        <section class="cad-design-danger"><button class="subtle-danger full" data-cad-action="delete-design">Delete this design</button></section>
      </aside>
    </div>
  </div>`;
}

function bindWorkshopUI() {
  $('#cadDesignSelect').onchange=e=>{state.workshopDesignId=e.target.value;renderWorkshop();};
  $('#cadDesignName').addEventListener('input',e=>{viewer.design.name=e.target.value.trim()||'Untitled design';markWorkshopDirty();});
  $$('[data-cad-add]').forEach(b=>{b.onclick=()=>addWorkshopPart(b.dataset.cadAdd);b.ondragstart=e=>{e.dataTransfer.effectAllowed='copy';e.dataTransfer.setData('application/x-layervault-shape',b.dataset.cadAdd);b.classList.add('dragging');};b.ondragend=()=>{b.classList.remove('dragging');$('#cadStage')?.classList.remove('shape-drag-over');};});
  $$('[data-cad-mode]').forEach(b=>b.onclick=()=>setWorkshopMode(b.dataset.cadMode));
  $$('[data-cad-action]').forEach(b=>b.onclick=()=>runWorkshopAction(b.dataset.cadAction));
  bindModelSearchPicker('cadLibrary',state.models.filter(previewable),{onSelect:model=>{const button=$('#cadLibraryAddBtn');if(button)button.disabled=!model;}});
  $('#cadSnap').onchange=e=>{viewer.design.document.grid.snap=e.target.checked;applyWorkshopSnaps();commitWorkshopChange();};
  $('#cadGridSize').value=String(viewer.design.document.grid?.size_mm||1);
  $('#cadGridSize').onchange=e=>{viewer.design.document.grid.size_mm=Number(e.target.value);applyWorkshopSnaps();replaceWorkshopGrid();commitWorkshopChange();};
  $$('[data-cad-view]').forEach(b=>b.onclick=()=>setWorkshopView(b.dataset.cadView));
  $$('[data-cad-zoom]').forEach(b=>b.onclick=()=>zoomWorkshop(b.dataset.cadZoom==='in' ? .8 : 1.25));
  const stage=$('#cadStage'),hasShapeDrag=e=>Array.from(e.dataTransfer?.types||[]).includes('application/x-layervault-shape');stage.ondragover=e=>{if(!hasShapeDrag(e))return;e.preventDefault();e.dataTransfer.dropEffect='copy';stage.classList.add('shape-drag-over');};stage.ondragleave=e=>{if(!stage.contains(e.relatedTarget))stage.classList.remove('shape-drag-over');};stage.ondrop=e=>{const kind=e.dataTransfer?.getData('application/x-layervault-shape');if(!kind)return;e.preventDefault();e.stopPropagation();stage.classList.remove('shape-drag-over');addWorkshopPart(kind,workshopDropPosition(e,kind));};
  $('#cadObjectList').addEventListener('click',e=>{const row=e.target.closest('[data-cad-object]');if(!row)return;const id=row.dataset.cadObject,item=viewer.design.document.objects.find(object=>object.id===id),related=item?.group_id?viewer.design.document.objects.filter(object=>object.group_id===item.group_id).map(object=>object.id):[id];if(e.shiftKey){related.forEach(partId=>viewer.selection.has(partId)?viewer.selection.delete(partId):viewer.selection.add(partId));}else viewer.selection=new Set(related);refreshWorkshopSelection();});
  $('#cadInspectorBody').onclick=e=>{const align=e.target.closest('[data-cad-align]');if(align)return alignWorkshopSelection(align.dataset.cadAlign);const operation=e.target.closest('[data-cad-operation]');if(operation)return setWorkshopOperation(operation.dataset.cadOperation);const preset=e.target.closest('[data-cad-color-preset]');if(preset)return setWorkshopColor(preset.dataset.cadColorPreset);const local=e.target.closest('[data-cad-local]');if(local)return runWorkshopAction(local.dataset.cadLocal);};
  $('#cadInspectorBody').onchange=e=>{if(e.target.matches('[data-cad-text]'))updateWorkshopText(e.target);else if(e.target.matches('[data-cad-font]'))updateWorkshopTextFont(e.target);else if(e.target.matches('[data-cad-name]')){const o=selectedWorkshopItems()[0];if(o){o.name=e.target.value.trim()||o.name;commitWorkshopChange();}}else if(e.target.matches('[data-cad-color]'))setWorkshopColor(e.target.value);else if(e.target.matches('[data-cad-value]'))applyWorkshopInspectorValue(e.target);else if(e.target.matches('[data-cad-toggle]')){const o=selectedWorkshopItems()[0];if(o){o[e.target.dataset.cadToggle]=e.target.checked;commitWorkshopChange();rebuildWorkshopObjects();}}};
  $('#cadInspectorBody').onfocusout=e=>{if(e.target.matches('[data-cad-value]'))applyWorkshopInspectorValue(e.target);};
  $('#cadInspectorBody').onkeydown=e=>{if(e.target.matches('[data-cad-text]')&&e.key==='Enter'){e.preventDefault();updateWorkshopText(e.target);e.target.blur();}};
  $('#cadInspectorBody').oninput=debounce(e=>{if(e.target.matches('[data-cad-value]'))applyWorkshopInspectorValue(e.target);},320);
  refreshWorkshopPanels();
}

function disposeObject(obj) {
  obj?.traverse?.(c=>{if(c.geometry?.dispose)c.geometry.dispose();if(Array.isArray(c.material))c.material.forEach(m=>m?.dispose?.());else c.material?.dispose?.();});
}

function disposeViewer() {
  if(viewer.animation)cancelAnimationFrame(viewer.animation);
  if(viewer.saveTimer)clearTimeout(viewer.saveTimer);
  viewer.observer?.disconnect?.();
  viewer.transform?.dispose?.(); viewer.controls?.dispose?.();
  if(viewer.root)disposeObject(viewer.root);
  if(viewer.renderer){viewer.renderer.dispose();viewer.renderer.domElement.remove();}
  viewer={renderer:null,scene:null,camera:null,controls:null,transform:null,root:null,selection:new Set(),objects:new Map(),helpers:null,animation:null,observer:null,design:null,history:[],historyIndex:-1,dirty:false,saveTimer:null,generation:(viewer.generation||0)+1,raycaster:null,pointer:null,mode:'translate',dragging:false,dragDepth:0,groupPreviews:new Map(),selectionPivot:null,selectionTransform:null,resizeAnchor:null,resizeDrag:null,surfaceMove:null,alignmentMode:false,alignmentTarget:null};
}

function loadModelObject(model, done, fail) {
  const url=`/api/models/${model.id}/file?v=${encodeURIComponent(String(model.sha256||'').slice(0,16))}`;
  const loaded=value=>{try{done(value);}catch(error){fail?.(error);}};
  ensureThreeEngine().then(()=>{if(model.extension==='.stl')return new STLLoader().load(url,loaded,undefined,fail);if(model.extension==='.obj')return new OBJLoader().load(url,loaded,undefined,fail);if(model.extension==='.3mf')return new ThreeMFLoader().load(url,loaded,undefined,fail);fail?.(new Error('This file type does not have a browser preview.'));}).catch(fail);
}

function styleLoadedObject(raw,color=0x70bfae){
  const material=()=>new THREE.MeshStandardMaterial({color,roughness:.88,metalness:0,side:THREE.DoubleSide});
  const root=raw?.isBufferGeometry?new THREE.Mesh(raw,material()):raw;
  if(!root?.traverse)throw new Error('The stored model did not contain renderable geometry.');
  let meshCount=0;
  root.traverse(child=>{if(!child.isMesh)return;meshCount++;if(!child.geometry?.attributes?.normal)child.geometry?.computeVertexNormals?.();if(Array.isArray(child.material))child.material.forEach(value=>value?.dispose?.());else child.material?.dispose?.();child.material=material();child.castShadow=false;child.receiveShadow=false;});
  if(!meshCount)throw new Error('The stored model did not contain a renderable mesh.');
  return root;
}

let cadHolePattern=null;
function cadHolePatternTexture(){if(cadHolePattern)return cadHolePattern;const canvas=document.createElement('canvas');canvas.width=canvas.height=64;const context=canvas.getContext('2d');context.fillStyle='#d5dadd';context.fillRect(0,0,64,64);context.strokeStyle='#69747c';context.lineWidth=7;for(let x=-64;x<128;x+=22){context.beginPath();context.moveTo(x,64);context.lineTo(x+64,0);context.stroke();}cadHolePattern=new THREE.CanvasTexture(canvas);cadHolePattern.wrapS=cadHolePattern.wrapT=THREE.RepeatWrapping;cadHolePattern.repeat.set(3,3);cadHolePattern.colorSpace=THREE.SRGBColorSpace;return cadHolePattern;}
function cadMaterial(item) {
  const hole=item.operation==='hole';
  return new THREE.MeshStandardMaterial({color:new THREE.Color(hole?'#a6afb5':item.color||'#67bea9'),map:hole?cadHolePatternTexture():null,roughness:.92,metalness:0,transparent:hole,opacity:hole?.58:1,depthWrite:!hole,side:THREE.DoubleSide,polygonOffset:hole,polygonOffsetFactor:hole?-1:0,polygonOffsetUnits:hole?-1:0});
}
function addCadEdgeOutline(mesh,item){if(!mesh?.isMesh||!mesh.geometry)return;const triangles=(mesh.geometry.index?.count||mesh.geometry.attributes?.position?.count||0)/3;if(triangles>80000)return;const hole=item.operation==='hole',edges=new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry,28),new THREE.LineBasicMaterial({color:hole?0x56636c:0x174a55,transparent:true,opacity:hole?.82:.72,depthTest:true}));edges.name='CAD feature edges';edges.renderOrder=4;mesh.add(edges);}
function styleCadObject(object,item){const meshes=[];object.traverse?.(child=>{if(child.isMesh)meshes.push(child);});for(const mesh of meshes){mesh.material=cadMaterial(item);mesh.castShadow=false;mesh.receiveShadow=false;addCadEdgeOutline(mesh,item);}return object;}

const cadBlockGlyphs={
  A:['01110','10001','10001','11111','10001','10001','10001'],B:['11110','10001','10001','11110','10001','10001','11110'],C:['01111','10000','10000','10000','10000','10000','01111'],D:['11110','10001','10001','10001','10001','10001','11110'],E:['11111','10000','10000','11110','10000','10000','11111'],F:['11111','10000','10000','11110','10000','10000','10000'],G:['01111','10000','10000','10111','10001','10001','01111'],H:['10001','10001','10001','11111','10001','10001','10001'],I:['11111','00100','00100','00100','00100','00100','11111'],J:['00111','00010','00010','00010','10010','10010','01100'],K:['10001','10010','10100','11000','10100','10010','10001'],L:['10000','10000','10000','10000','10000','10000','11111'],M:['10001','11011','10101','10101','10001','10001','10001'],N:['10001','11001','10101','10011','10001','10001','10001'],O:['01110','10001','10001','10001','10001','10001','01110'],P:['11110','10001','10001','11110','10000','10000','10000'],Q:['01110','10001','10001','10001','10101','10010','01101'],R:['11110','10001','10001','11110','10100','10010','10001'],S:['01111','10000','10000','01110','00001','00001','11110'],T:['11111','00100','00100','00100','00100','00100','00100'],U:['10001','10001','10001','10001','10001','10001','01110'],V:['10001','10001','10001','10001','10001','01010','00100'],W:['10001','10001','10001','10101','10101','11011','10001'],X:['10001','10001','01010','00100','01010','10001','10001'],Y:['10001','10001','01010','00100','00100','00100','00100'],Z:['11111','00001','00010','00100','01000','10000','11111'],
  0:['01110','10001','10011','10101','11001','10001','01110'],1:['00100','01100','00100','00100','00100','00100','01110'],2:['01110','10001','00001','00010','00100','01000','11111'],3:['11110','00001','00001','01110','00001','00001','11110'],4:['00010','00110','01010','10010','11111','00010','00010'],5:['11111','10000','10000','11110','00001','00001','11110'],6:['01110','10000','10000','11110','10001','10001','01110'],7:['11111','00001','00010','00100','01000','01000','01000'],8:['01110','10001','10001','01110','10001','10001','01110'],9:['01110','10001','10001','01111','00001','00001','01110'],
  '?':['01110','10001','00001','00010','00100','00000','00100'],'!':['00100','00100','00100','00100','00100','00000','00100'],'.':['00000','00000','00000','00000','00000','00110','00110'],',':['00000','00000','00000','00000','00110','00110','00100'],':':['00000','00110','00110','00000','00110','00110','00000'],'-':['00000','00000','00000','11111','00000','00000','00000'],'_':['00000','00000','00000','00000','00000','00000','11111'],'+':['00000','00100','00100','11111','00100','00100','00000'],'/':['00001','00010','00010','00100','01000','01000','10000']
};

function cadUnitGeometry(geometry){geometry.computeBoundingBox();const box=geometry.boundingBox,size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3());geometry.translate(-center.x,-center.y,-center.z);geometry.scale(1/Math.max(size.x,.001),1/Math.max(size.y,.001),1/Math.max(size.z,.001));geometry.computeVertexNormals();return geometry;}
function cadD10Geometry(){const positions=[0,.5,0,0,-.5,0],indices=[];for(let i=0;i<10;i++){const angle=Math.PI*2*i/10;positions.push(Math.cos(angle)*.5,0,Math.sin(angle)*.5);}for(let i=0;i<10;i++){const a=2+i,b=2+(i+1)%10;indices.push(0,b,a,1,a,b);}const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setIndex(indices);return cadUnitGeometry(geometry);}
function cadPolygonPrismGeometry(points){const positions=[0,.5,0,0,-.5,0],indices=[],count=points.length;for(const [x,z] of points)positions.push(x,.5,z);for(const [x,z] of points)positions.push(x,-.5,z);for(let i=0;i<count;i++){const next=(i+1)%count,top=2+i,topNext=2+next,bottom=2+count+i,bottomNext=2+count+next;indices.push(0,topNext,top,1,bottom,bottomNext,bottom,top,topNext,bottom,topNext,bottomNext);}const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setIndex(indices);return cadUnitGeometry(geometry);}
function cadStarGeometry(){const points=[];for(let i=0;i<10;i++){const angle=-Math.PI/2+i*Math.PI/5,radius=i%2===0?.5:.225;points.push([Math.cos(angle)*radius,Math.sin(angle)*radius]);}return cadPolygonPrismGeometry(points);}
function cadRingGeometry(segments=40){const positions=[],indices=[],outer=.5,inner=.29;for(let i=0;i<segments;i++){const a=Math.PI*2*i/segments,b=Math.PI*2*(i+1)/segments,oa=[Math.cos(a)*outer,Math.sin(a)*outer],ob=[Math.cos(b)*outer,Math.sin(b)*outer],ia=[Math.cos(a)*inner,Math.sin(a)*inner],ib=[Math.cos(b)*inner,Math.sin(b)*inner],start=positions.length/3,vertices=[[oa[0],.5,oa[1]],[ia[0],.5,ia[1]],[ib[0],.5,ib[1]],[ob[0],.5,ob[1]],[oa[0],-.5,oa[1]],[ob[0],-.5,ob[1]],[ib[0],-.5,ib[1]],[ia[0],-.5,ia[1]]];vertices.forEach(vertex=>positions.push(...vertex));indices.push(start,start+1,start+2,start,start+2,start+3,start+4,start+5,start+6,start+4,start+6,start+7,start+4,start,start+3,start+4,start+3,start+5,start+7,start+6,start+2,start+7,start+2,start+1);}const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setIndex(indices);return cadUnitGeometry(geometry);}
function cadTextGeometry(value,font='classic'){
  const text=cadPrintableText(value),style=cadTextFonts[font]?font:'classic',filled=new Set();let cursor=0;
  for(const character of text){if(character===' '){cursor+=style==='condensed'?3:4;continue;}const rows=cadBlockGlyphs[character]||cadBlockGlyphs['?'];rows.forEach((row,z)=>{if(style==='condensed'){[[0,1],[2],[3,4]].forEach((columns,x)=>{if(columns.some(column=>row[column]==='1'))filled.add(`${cursor+x},${6-z}`);});}else{[...row].forEach((on,x)=>{if(on!=='1')return;filled.add(`${cursor+x},${6-z}`);if(style==='bold'){if(x>0)filled.add(`${cursor+x-1},${6-z}`);if(x<4)filled.add(`${cursor+x+1},${6-z}`);}});}});cursor+=style==='condensed'?4:6;}
  for(let pass=0;pass<4;pass++){const additions=[];for(const key of filled){const [x,z]=key.split(',').map(Number);for(const [dx,dz] of [[-1,-1],[-1,1],[1,-1],[1,1]])if(filled.has(`${x+dx},${z+dz}`)&&!filled.has(`${x+dx},${z}`)&&!filled.has(`${x},${z+dz}`))additions.push(`${x+dx},${z}`);}if(!additions.length)break;additions.forEach(key=>filled.add(key));}
  const positions=[],indices=[],quad=(a,b,c,d)=>{const start=positions.length/3;[a,b,c,d].forEach(point=>positions.push(...point));indices.push(start,start+1,start+2,start,start+2,start+3);};
  for(const key of filled){const [x,z]=key.split(',').map(Number),x0=x,x1=x+1,z0=z,z1=z+1,y0=-.5,y1=.5;quad([x0,y1,z0],[x0,y1,z1],[x1,y1,z1],[x1,y1,z0]);quad([x0,y0,z0],[x1,y0,z0],[x1,y0,z1],[x0,y0,z1]);if(!filled.has(`${x-1},${z}`))quad([x0,y0,z0],[x0,y0,z1],[x0,y1,z1],[x0,y1,z0]);if(!filled.has(`${x+1},${z}`))quad([x1,y0,z0],[x1,y1,z0],[x1,y1,z1],[x1,y0,z1]);if(!filled.has(`${x},${z-1}`))quad([x0,y0,z0],[x0,y1,z0],[x1,y1,z0],[x1,y0,z0]);if(!filled.has(`${x},${z+1}`))quad([x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]);}
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setIndex(indices);return cadUnitGeometry(geometry);
}

function primitiveGeometry(kind,item=null) {
  if(kind==='box')return new THREE.BoxGeometry(1,1,1);
  if(kind==='cylinder')return new THREE.CylinderGeometry(.5,.5,1,32);
  if(kind==='sphere')return new THREE.SphereGeometry(.5,32,20);
  if(kind==='cone')return new THREE.CylinderGeometry(0,.5,1,32);
  if(kind==='wedge'){
    const g=new THREE.BufferGeometry();
    g.setAttribute('position',new THREE.Float32BufferAttribute([
      -.5,-.5,-.5,.5,-.5,-.5,.5,-.5,.5,-.5,-.5,.5,
      -.5,.5,-.5,.5,.5,-.5
    ],3));
    g.setIndex([0,2,1,0,3,2,0,1,5,0,5,4,1,2,5,2,3,5,3,0,4,3,4,5]);g.computeVertexNormals();return g;
  }
  if(kind==='pyramid')return cadUnitGeometry(new THREE.CylinderGeometry(0,.5,1,4,1,false));
  if(kind==='hex')return cadUnitGeometry(new THREE.CylinderGeometry(.5,.5,1,6,1,false));
  if(kind==='star')return cadStarGeometry();
  if(kind==='torus')return cadUnitGeometry(new THREE.TorusGeometry(.34,.16,14,40));
  if(kind==='ring')return cadRingGeometry();
  if(kind==='d4')return cadUnitGeometry(new THREE.TetrahedronGeometry(.5,0));
  if(kind==='d6')return new THREE.BoxGeometry(1,1,1);
  if(kind==='d8')return cadUnitGeometry(new THREE.OctahedronGeometry(.5,0));
  if(kind==='d10')return cadD10Geometry();
  if(kind==='d12')return cadUnitGeometry(new THREE.DodecahedronGeometry(.5,0));
  if(kind==='d20')return cadUnitGeometry(new THREE.IcosahedronGeometry(.5,0));
  if(kind==='text')return cadTextGeometry(item?.params?.text,item?.params?.font);
  return new THREE.BoxGeometry(1,1,1);
}

const cadPrimitiveGeometryCache=new Map();
function cachedPrimitiveGeometry(item){const key=item.kind==='text'?`text:${cadPrintableText(item.params?.text)}:${cadTextFonts[item.params?.font]?item.params.font:'classic'}`:item.kind;if(!cadPrimitiveGeometryCache.has(key)){cadPrimitiveGeometryCache.set(key,primitiveGeometry(item.kind,item));if(cadPrimitiveGeometryCache.size>48){const oldest=cadPrimitiveGeometryCache.keys().next().value;cadPrimitiveGeometryCache.get(oldest)?.dispose?.();cadPrimitiveGeometryCache.delete(oldest);}}return cadPrimitiveGeometryCache.get(key).clone();}
function makePrimitiveObject(item) {
  const wrap=new THREE.Group(),mesh=new THREE.Mesh(cachedPrimitiveGeometry(item),cadMaterial(item));
  mesh.scale.set(...item.size);mesh.castShadow=false;mesh.receiveShadow=false;addCadEdgeOutline(mesh,item);wrap.add(mesh);return wrap;
}

function prepareLibraryObject(raw,item) {
  const styled=raw.isBufferGeometry?new THREE.Mesh(raw,cadMaterial(item)):raw;
  styleCadObject(styled,item);
  const box=new THREE.Box3().setFromObject(styled),center=box.getCenter(new THREE.Vector3());
  styled.position.sub(center);
  const wrap=new THREE.Group();wrap.add(styled);return wrap;
}

function applyWorkshopTransform(obj,item) {
  obj.userData.workshopId=item.id;
  obj.position.set(...item.position);obj.rotation.set(...item.rotation.map(THREE.MathUtils.degToRad));obj.scale.set(...item.scale);
  obj.visible=item.visible!==false;obj.traverse(c=>{c.userData.workshopId=item.id;});obj.updateMatrixWorld(true);
}

async function initWorkshopViewer() {
  const stage=$('#cadStage');if(!stage||!viewer.design)return;
  try{await ensureWorkshopEngine();}catch(e){$('#viewerEmpty').innerHTML=`<div><strong>Workshop unavailable</strong><span>${esc(e.message)}</span></div>`;toast(e.message,true);return;}
  if(!$('#cadStage')||!viewer.design)return;
  const scene=new THREE.Scene();scene.background=new THREE.Color(0xf4f8f8);
  const camera=new THREE.PerspectiveCamera(42,stage.clientWidth/stage.clientHeight,.1,20000);camera.position.set(120,90,120);
  const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setSize(stage.clientWidth,stage.clientHeight);renderer.shadowMap.enabled=false;renderer.outputColorSpace=THREE.SRGBColorSpace;stage.prepend(renderer.domElement);
  const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.enabled=false;controls.target.set(0,12,0);
  scene.add(new THREE.HemisphereLight(0xffffff,0xd9e4e3,1.65));scene.add(new THREE.AmbientLight(0xffffff,.7));const light=new THREE.DirectionalLight(0xffffff,1.25);light.position.set(80,140,70);light.castShadow=false;scene.add(light);
  const root=new THREE.Group();root.name='Workshop objects';scene.add(root);const helpers=new THREE.Group();scene.add(helpers);
  const transform=new TransformControls(camera,renderer.domElement);scene.add(transform.getHelper());
  viewer=Object.assign(viewer,{renderer,scene,camera,controls,transform,root,helpers,objects:new Map(),selection:new Set(),raycaster:new THREE.Raycaster(),pointer:new THREE.Vector2(),mode:'translate',groupPreviews:new Map(),selectionPivot:null,selectionTransform:null,resizeAnchor:null,resizeDrag:null,handleResize:null,surfaceMove:null,marquee:null,alignmentMode:false,alignmentTarget:null,cameraModifier:false});transform.setSize(.68);
  transform.addEventListener('mouseDown',()=>{if(viewer.mode==='scale')beginDirectionalResize();});
  transform.addEventListener('dragging-changed',e=>{viewer.dragging=e.value;controls.enabled=!e.value&&viewer.cameraModifier;if(!e.value){syncSelectedTransformToDocument();commitWorkshopChange();viewer.resizeDrag=null;refreshWorkshopSelection();}});
  transform.addEventListener('objectChange',syncSelectedTransformToDocument);
  applyWorkshopSnaps();
  renderer.domElement.tabIndex=0;renderer.domElement.setAttribute('aria-label','Workshop design canvas');
  let down=null;renderer.domElement.addEventListener('pointerdown',e=>{renderer.domElement.focus({preventScroll:true});down=[e.clientX,e.clientY];if(e.button!==0||e.ctrlKey||viewer.cameraModifier)return;const handle=workshopPointerHelperHit(e,'cadResizeHandle');if(handle&&beginWorkshopHandleResize(e,handle))return;if(!e.shiftKey&&beginWorkshopSurfaceMove(e))return;beginWorkshopMarquee(e);});
  renderer.domElement.addEventListener('pointermove',e=>{if(updateWorkshopHandleResize(e))return;updateWorkshopSurfaceMove(e);updateWorkshopMarquee(e);});
  renderer.domElement.addEventListener('pointerup',e=>{if(finishWorkshopHandleResize(e))return;const moved=finishWorkshopSurfaceMove(e),boxed=finishWorkshopMarquee(e);if(moved||boxed||viewer.dragging||e.ctrlKey||viewer.cameraModifier||!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;pickWorkshopObject(e);});
  renderer.domElement.addEventListener('pointercancel',()=>{cancelWorkshopHandleResize();cancelWorkshopSurfaceMove();cancelWorkshopMarquee();});
  viewer.observer=new ResizeObserver(()=>{if(!stage.clientWidth||!viewer.renderer)return;camera.aspect=stage.clientWidth/stage.clientHeight;camera.updateProjectionMatrix();renderer.setSize(stage.clientWidth,stage.clientHeight);});viewer.observer.observe(stage);
  let lastOverlayFrame=0;const animate=time=>{viewer.animation=requestAnimationFrame(animate);controls.update();renderer.render(scene,camera);if(time-lastOverlayFrame>32){positionWorkshopDimensionOverlay();lastOverlayFrame=time;}};animate(0);
  await rebuildWorkshopObjects();fitWorkshopView();$('#viewerEmpty')?.classList.add('hidden');
}

function replaceWorkshopGrid(){const old=viewer.scene?.getObjectByName('workshop-grid');if(old){viewer.scene.remove(old);old.geometry.dispose();old.material.dispose();}if(!viewer.scene||viewer.design.document.grid.visible===false)return;const step=Number(viewer.design.document.grid.size_mm||1),size=400,div=Math.max(2,Math.min(400,Math.round(size/step)));const grid=new THREE.GridHelper(size,div,0x83a7a2,0xcfdcda);grid.name='workshop-grid';viewer.scene.add(grid);}

async function rebuildWorkshopObjects() {
  if(!viewer.root)return;const generation=++viewer.generation;
  viewer.transform.detach();disposeWorkshopSelectionPivot();for(const child of [...viewer.root.children]){viewer.root.remove(child);disposeObject(child);}viewer.objects.clear();viewer.groupPreviews.clear();replaceWorkshopGrid();
  const tasks=(viewer.design.document.objects||[]).map(item=>new Promise(resolve=>{
    const finish=obj=>{if(generation!==viewer.generation){disposeObject(obj);return resolve();}applyWorkshopTransform(obj,item);viewer.root.add(obj);viewer.objects.set(item.id,obj);resolve();};
    if(item.kind!=='model')return finish(makePrimitiveObject(item));
    const model=state.models.find(m=>m.id===item.model_id);if(!model)return resolve();
    loadModelObject(model,raw=>finish(prepareLibraryObject(raw,item)),()=>{toast(`${item.name} could not be loaded`,true);resolve();});
  }));
  await Promise.all(tasks);viewer.root.updateMatrixWorld(true);
  const groups=new Map();for(const item of viewer.design.document.objects||[]){if(item.group_id)(groups.get(item.group_id)||groups.set(item.group_id,[]).get(item.group_id)).push(item);}for(const [groupId,items] of groups){if(items.length<2||!items.some(x=>x.operation==='solid'))continue;try{const geometry=composeWorkshopItemsGeometry(items),solid=items.find(x=>x.operation==='solid'),preview=new THREE.Mesh(geometry,cadMaterial({...solid,operation:'solid'}));preview.castShadow=false;preview.receiveShadow=false;addCadEdgeOutline(preview,{...solid,operation:'solid'});preview.traverse(child=>{child.userData.workshopGroupId=groupId;child.userData.workshopId=items[0].id;});items.forEach(x=>{const original=viewer.objects.get(x.id);if(original)original.visible=false;});viewer.root.add(preview);viewer.groupPreviews.set(groupId,preview);}catch(e){/* Keep editable source shapes visible when a source cannot produce a safe group preview. */}}
  viewer.selection=new Set([...viewer.selection].filter(id=>viewer.objects.has(id)));refreshWorkshopSelection();
}

function setWorkshopPointerRay(event){const rect=viewer.renderer.domElement.getBoundingClientRect();viewer.pointer.set(((event.clientX-rect.left)/rect.width)*2-1,-((event.clientY-rect.top)/rect.height)*2+1);viewer.raycaster.setFromCamera(viewer.pointer,viewer.camera);return viewer.raycaster;}
function workshopPointerObjectHit(event){const ray=setWorkshopPointerRay(event),hit=ray.intersectObjects(viewer.root.children,true).find(value=>value.object.visible);let target=hit?.object;while(target&&!target.userData?.workshopId&&!target.userData?.workshopGroupId)target=target.parent;const groupId=target?.userData?.workshopGroupId,id=target?.userData?.workshopId,ids=groupId?(viewer.design.document.objects||[]).filter(item=>item.group_id===groupId).map(item=>item.id):(id?[id]:[]);return{hit,target,ids};}
function workshopPointerPlanePoint(event,plane){const point=new THREE.Vector3();return setWorkshopPointerRay(event).ray.intersectPlane(plane,point)?point:null;}
function workshopPointerHelperHit(event,key){if(key==='cadResizeHandle'&&viewer.camera&&viewer.renderer){const rect=viewer.renderer.domElement.getBoundingClientRect(),candidates=(viewer.helpers?.children||[]).filter(object=>object.userData?.[key]).map(object=>{const point=object.getWorldPosition(new THREE.Vector3()).project(viewer.camera),x=rect.left+(point.x+1)*rect.width/2,y=rect.top+(1-point.y)*rect.height/2;return{object,distance:Math.hypot(event.clientX-x,event.clientY-y)};}).sort((a,b)=>a.distance-b.distance);if(candidates[0]?.distance<=22)return candidates[0].object;}const hit=setWorkshopPointerRay(event).intersectObjects(viewer.helpers?.children||[],true).find(value=>{let object=value.object;while(object&&object!==viewer.helpers){if(object.userData?.[key])return true;object=object.parent;}return false;});if(!hit)return null;let object=hit.object;while(object&&object!==viewer.helpers&&!object.userData?.[key])object=object.parent;return object?.userData?.[key]?object:null;}
function setWorkshopCameraModifier(active){if(!viewer.controls||!viewer.renderer)return;viewer.cameraModifier=!!active;viewer.controls.enabled=!!active&&!viewer.dragging&&!viewer.surfaceMove&&!viewer.handleResize;viewer.renderer.domElement.classList.toggle('cad-camera-mode',!!active);}
function beginWorkshopSurfaceMove(event){if(viewer.alignmentMode||viewer.transform?.axis)return false;const picked=workshopPointerObjectHit(event);if(!picked.ids.length)return false;const alreadySelected=picked.ids.every(id=>viewer.selection.has(id));if(viewer.mode!=='translate'&&!alreadySelected)return false;if(!alreadySelected){viewer.selection=new Set(picked.ids);refreshWorkshopSelection();}const items=selectedWorkshopItems();if(!items.length||items.every(item=>item.locked))return false;const visuals=workshopSelectionVisuals(),box=workshopVisualBounds(visuals),center=box.getCenter(new THREE.Vector3()),plane=new THREE.Plane(new THREE.Vector3(0,1,0),-center.y),startPoint=workshopPointerPlanePoint(event,plane);if(!startPoint)return false;viewer.surfaceMove={startClient:new THREE.Vector2(event.clientX,event.clientY),startPoint,plane,center,items:items.map(item=>({item,startMatrix:workshopMatrixFromItem(item),object:viewer.objects.get(item.id)})),visuals:visuals.map(object=>({object,startMatrix:object.matrix.clone()})),moved:false,pointerId:event.pointerId};viewer.renderer.domElement.setPointerCapture?.(event.pointerId);return true;}
function updateWorkshopSurfaceMove(event){const state=viewer.surfaceMove;if(!state||event.pointerId!==state.pointerId||viewer.transform?.dragging)return;if(!state.moved&&state.startClient.distanceTo(new THREE.Vector2(event.clientX,event.clientY))<3)return;const point=workshopPointerPlanePoint(event,state.plane);if(!point)return;state.moved=true;viewer.controls.enabled=false;viewer.transform.detach();viewer.renderer.domElement.classList.add('cad-direct-moving');event.preventDefault();const step=viewer.design.document.grid.snap===false?0:Number(viewer.design.document.grid.size_mm||1),snap=value=>step?Math.round(value/step)*step:value,delta=new THREE.Vector3(snap(state.center.x+point.x-state.startPoint.x)-state.center.x,0,snap(state.center.z+point.z-state.startPoint.z)-state.center.z),translation=new THREE.Matrix4().makeTranslation(delta.x,0,delta.z);for(const entry of state.items)applyMatrixToWorkshopItem(translation.clone().multiply(entry.startMatrix),entry.item,entry.object);for(const entry of state.visuals){const matrix=translation.clone().multiply(entry.startMatrix),position=new THREE.Vector3(),quaternion=new THREE.Quaternion(),scale=new THREE.Vector3();matrix.decompose(position,quaternion,scale);entry.object.position.copy(position);entry.object.quaternion.copy(quaternion);entry.object.scale.copy(scale);entry.object.updateMatrixWorld(true);}positionWorkshopDimensionOverlay();}
function finishWorkshopSurfaceMove(event){const state=viewer.surfaceMove;if(!state||event?.pointerId!==state.pointerId)return false;viewer.surfaceMove=null;releaseWorkshopPointer(state.pointerId);viewer.controls.enabled=viewer.cameraModifier;viewer.renderer?.domElement?.classList.remove('cad-direct-moving');if(!state.moved)return false;commitWorkshopChange();refreshWorkshopSelection();toast('Selection moved · left-drag stays ready');return true;}
function cancelWorkshopSurfaceMove(){const state=viewer.surfaceMove;if(!state)return;viewer.surfaceMove=null;releaseWorkshopPointer(state.pointerId);viewer.controls.enabled=viewer.cameraModifier;viewer.renderer?.domElement?.classList.remove('cad-direct-moving');if(state.moved)refreshWorkshopSelection();}

function beginWorkshopMarquee(event){if(viewer.alignmentMode||viewer.transform?.axis||workshopPointerObjectHit(event).ids.length)return false;const canvas=viewer.renderer.domElement,rect=canvas.getBoundingClientRect();viewer.marquee={pointerId:event.pointerId,startClient:new THREE.Vector2(event.clientX,event.clientY),start:{x:event.clientX-rect.left,y:event.clientY-rect.top},current:{x:event.clientX-rect.left,y:event.clientY-rect.top},additive:event.shiftKey,moved:false};canvas.setPointerCapture?.(event.pointerId);updateWorkshopMarqueeElement();return true;}
function updateWorkshopMarquee(event){const state=viewer.marquee;if(!state||event.pointerId!==state.pointerId)return false;state.current={x:event.clientX-viewer.renderer.domElement.getBoundingClientRect().left,y:event.clientY-viewer.renderer.domElement.getBoundingClientRect().top};if(!state.moved&&state.startClient.distanceTo(new THREE.Vector2(event.clientX,event.clientY))>=5)state.moved=true;updateWorkshopMarqueeElement();if(state.moved)event.preventDefault();return state.moved;}
function updateWorkshopMarqueeElement(){const box=$('#cadSelectionMarquee'),state=viewer.marquee;if(!box)return;if(!state||!state.moved){box.classList.add('hidden');return;}const left=Math.min(state.start.x,state.current.x),top=Math.min(state.start.y,state.current.y),width=Math.abs(state.current.x-state.start.x),height=Math.abs(state.current.y-state.start.y);box.classList.remove('hidden');Object.assign(box.style,{left:`${left}px`,top:`${top}px`,width:`${width}px`,height:`${height}px`});}
function selectWorkshopMarquee(state){const left=Math.min(state.start.x,state.current.x),right=Math.max(state.start.x,state.current.x),top=Math.min(state.start.y,state.current.y),bottom=Math.max(state.start.y,state.current.y),canvas=viewer.renderer.domElement,rect=canvas.getBoundingClientRect(),project=point=>{const p=point.clone().project(viewer.camera);return{x:(p.x+1)*rect.width/2,y:(1-p.y)*rect.height/2};},all=(viewer.design.document.objects||[]).filter(item=>item.visible!==false),matched=new Set();for(const unit of workshopSelectionUnits(all)){const box=workshopVisualBounds(unit.visuals);if(box.isEmpty())continue;const corners=[];for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z])corners.push(project(new THREE.Vector3(x,y,z)));const xs=corners.map(point=>point.x),ys=corners.map(point=>point.y),screen={left:Math.min(...xs),right:Math.max(...xs),top:Math.min(...ys),bottom:Math.max(...ys)},overlaps=screen.right>=left&&screen.left<=right&&screen.bottom>=top&&screen.top<=bottom;if(overlaps)unit.items.forEach(item=>matched.add(item.id));}if(state.additive)matched.forEach(id=>viewer.selection.add(id));else viewer.selection=matched;refreshWorkshopSelection();}
function releaseWorkshopPointer(pointerId){const canvas=viewer.renderer?.domElement;if(canvas?.hasPointerCapture?.(pointerId))canvas.releasePointerCapture(pointerId);}
function finishWorkshopMarquee(event){const state=viewer.marquee;if(!state||event?.pointerId!==state.pointerId)return false;viewer.marquee=null;releaseWorkshopPointer(state.pointerId);updateWorkshopMarqueeElement();if(!state.moved)return false;selectWorkshopMarquee(state);return true;}
function cancelWorkshopMarquee(){const state=viewer.marquee;viewer.marquee=null;updateWorkshopMarqueeElement();if(state)releaseWorkshopPointer(state.pointerId);}
function pickWorkshopObject(e){const ray=setWorkshopPointerRay(e),alignment=viewer.alignmentMode?ray.intersectObjects(viewer.helpers.children,true).find(hit=>hit.object.userData.cadAlign):null;if(alignment){const [axis,mode]=alignment.object.userData.cadAlign.split(':');alignWorkshopSelection(axis,mode);return;}const {ids}=workshopPointerObjectHit(e);if(e.shiftKey&&ids.length){ids.forEach(partId=>viewer.selection.has(partId)?viewer.selection.delete(partId):viewer.selection.add(partId));}else viewer.selection=new Set(ids);refreshWorkshopSelection();}

function normaliseWorkshopSelection(){const objects=viewer.design?.document?.objects||[],valid=new Set(objects.map(item=>item.id)),next=new Set([...viewer.selection].filter(id=>valid.has(id)));for(const item of objects)if(next.has(item.id)&&item.group_id)objects.filter(member=>member.group_id===item.group_id).forEach(member=>next.add(member.id));viewer.selection=next;return next;}
function selectedWorkshopItems(){const selection=normaliseWorkshopSelection();return (viewer.design?.document?.objects||[]).filter(o=>selection.has(o.id));}
function selectedWorkshopObjects(){return [...viewer.selection].map(id=>viewer.objects.get(id)).filter(Boolean);}
function workshopSelectionUnits(items=selectedWorkshopItems()){const units=[],seenGroups=new Set();for(const item of items){if(item.group_id){if(seenGroups.has(item.group_id))continue;seenGroups.add(item.group_id);const members=(viewer.design?.document?.objects||[]).filter(member=>member.group_id===item.group_id),preview=viewer.groupPreviews.get(item.group_id),visuals=preview?[preview]:members.map(member=>viewer.objects.get(member.id)).filter(object=>object?.visible);units.push({id:item.group_id,grouped:true,items:members,visuals});}else{const visual=viewer.objects.get(item.id);units.push({id:item.id,grouped:false,items:[item],visuals:visual?[visual]:[]});}}return units;}
function workshopSelectionVisuals(){const visuals=[],seen=new Set();for(const unit of workshopSelectionUnits())for(const visual of unit.visuals)if(!seen.has(visual)){seen.add(visual);visuals.push(visual);}return visuals;}
function workshopVisualBounds(visuals=workshopSelectionVisuals()){const box=new THREE.Box3();visuals.forEach(object=>box.expandByObject(object));return box;}
function disposeWorkshopSelectionPivot(){if(viewer.selectionPivot){viewer.transform?.detach?.();viewer.scene?.remove?.(viewer.selectionPivot);viewer.selectionPivot=null;}viewer.selectionTransform=null;}
function createWorkshopSelectionPivot(visuals,items){disposeWorkshopSelectionPivot();const box=new THREE.Box3();visuals.forEach(o=>box.expandByObject(o));const center=box.isEmpty()?new THREE.Vector3():box.getCenter(new THREE.Vector3()),pivot=new THREE.Object3D();pivot.name='Workshop selection pivot';pivot.position.copy(center);pivot.updateMatrix();viewer.scene.add(pivot);const startPivotInverse=pivot.matrix.clone().invert(),visualStates=visuals.map(object=>({object,startMatrix:object.matrix.clone()})),itemStates=items.map(item=>({item,object:viewer.objects.get(item.id),startMatrix:workshopMatrixFromItem(item)}));viewer.selectionPivot=pivot;viewer.selectionTransform={pivot,startPivotInverse,items:itemStates,visuals:visualStates};return pivot;}

function workshopGuideLine(from,to,color=0x344550){const geometry=new THREE.BufferGeometry().setFromPoints([from,to]),material=new THREE.LineDashedMaterial({color,transparent:true,opacity:.62,dashSize:.7,gapSize:.55,depthTest:false}),line=new THREE.Line(geometry,material);line.computeLineDistances();line.renderOrder=8;return line;}
function addWorkshopAlignmentHandles(visuals){const box=workshopVisualBounds(visuals);if(box.isEmpty())return;const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()),span=Math.max(size.x,size.y,size.z,10),offset=Math.max(2,span*.09),radius=Math.max(.7,Math.min(1.35,span*.032)),geometry=new THREE.SphereGeometry(radius,16,10),definitions=[
  ['x','min',new THREE.Vector3(box.min.x,box.min.y-offset,box.max.z+offset)],['x','center',new THREE.Vector3(center.x,box.min.y-offset,box.max.z+offset)],['x','max',new THREE.Vector3(box.max.x,box.min.y-offset,box.max.z+offset)],
  ['z','min',new THREE.Vector3(box.max.x+offset,box.min.y-offset,box.min.z)],['z','center',new THREE.Vector3(box.max.x+offset,box.min.y-offset,center.z)],['z','max',new THREE.Vector3(box.max.x+offset,box.min.y-offset,box.max.z)],
  ['y','min',new THREE.Vector3(box.min.x-offset,box.min.y,box.max.z+offset)],['y','center',new THREE.Vector3(box.min.x-offset,center.y,box.max.z+offset)],['y','max',new THREE.Vector3(box.min.x-offset,box.max.y,box.max.z+offset)]
];
  viewer.helpers.add(workshopGuideLine(definitions[0][2],definitions[2][2]));viewer.helpers.add(workshopGuideLine(definitions[3][2],definitions[5][2],0x77838a));viewer.helpers.add(workshopGuideLine(definitions[6][2],definitions[8][2]));
  for(const [axis,mode,position] of definitions){const active=viewer.alignmentTarget?.axis===axis&&viewer.alignmentTarget?.mode===mode,handle=new THREE.Mesh(geometry.clone(),new THREE.MeshBasicMaterial({color:active?0x2e79e7:(axis==='z'?0x808a91:0x293740),depthTest:false}));handle.position.copy(position);handle.renderOrder=9;handle.userData.cadAlign=`${axis}:${mode}`;handle.name=`Align ${axis} ${mode}`;viewer.helpers.add(handle);}geometry.dispose();
}

function addWorkshopResizeHandles(visuals){const box=workshopVisualBounds(visuals);if(box.isEmpty())return;const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()),span=Math.max(size.x,size.y,size.z,10),handleSize=Math.max(1.45,Math.min(2.8,span*.065)),baseY=box.min.y+handleSize*.18,definitions=[];for(const sx of [-1,1])for(const sz of [-1,1])definitions.push({axis:'XZ',signs:{x:sx,y:1,z:sz},position:new THREE.Vector3(sx<0?box.min.x:box.max.x,baseY,sz<0?box.min.z:box.max.z),kind:'corner'});definitions.push(
  {axis:'X',signs:{x:-1,y:1,z:1},position:new THREE.Vector3(box.min.x,baseY,center.z),kind:'edge'},
  {axis:'X',signs:{x:1,y:1,z:1},position:new THREE.Vector3(box.max.x,baseY,center.z),kind:'edge'},
  {axis:'Z',signs:{x:1,y:1,z:-1},position:new THREE.Vector3(center.x,baseY,box.min.z),kind:'edge'},
  {axis:'Z',signs:{x:1,y:1,z:1},position:new THREE.Vector3(center.x,baseY,box.max.z),kind:'edge'},
  {axis:'Y',signs:{x:1,y:1,z:1},position:new THREE.Vector3(center.x,box.max.y,center.z),kind:'height'}
);for(const definition of definitions){const sizeFactor=definition.kind==='edge'?0.82:1,geometry=new THREE.BoxGeometry(handleSize*sizeFactor,handleSize*sizeFactor,handleSize*sizeFactor),material=new THREE.MeshBasicMaterial({color:definition.kind==='height'?0xf7fbff:0xffffff,depthTest:false,transparent:true,opacity:.98}),handle=new THREE.Mesh(geometry,material);handle.position.copy(definition.position);handle.renderOrder=12;handle.userData.cadResizeHandle={axis:definition.axis,signs:definition.signs,kind:definition.kind};handle.name=`Resize ${definition.axis}`;const edges=new THREE.LineSegments(new THREE.EdgesGeometry(geometry),new THREE.LineBasicMaterial({color:0x253945,depthTest:false}));edges.renderOrder=13;handle.add(edges);viewer.helpers.add(handle);}}

function workshopResizeSnap(value){const step=viewer.design.document.grid.snap===false?0:Number(viewer.design.document.grid.size_mm||1);return Math.max(.1,step?Math.round(value/step)*step:value);}
function beginWorkshopHandleResize(event,handle){const data=handle.userData.cadResizeHandle,items=selectedWorkshopItems();if(!data||!items.length||items.every(item=>item.locked))return false;const visuals=workshopSelectionVisuals(),box=workshopVisualBounds(visuals);if(box.isEmpty())return false;const size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3()),anchor=center.clone(),signs=data.signs;for(const [letter,index] of [['X',0],['Y',1],['Z',2]])if(data.axis.includes(letter))anchor.setComponent(index,signs[letter.toLowerCase()]>0?box.min.getComponent(index):box.max.getComponent(index));const plane=data.axis.includes('X')||data.axis.includes('Z')?new THREE.Plane(new THREE.Vector3(0,1,0),-box.min.y):null,startPoint=plane?workshopPointerPlanePoint(event,plane):null,distance=viewer.camera.position.distanceTo(center),worldPerPixel=2*distance*Math.tan(THREE.MathUtils.degToRad(viewer.camera.fov/2))/Math.max(1,viewer.renderer.domElement.clientHeight);viewer.handleResize={pointerId:event.pointerId,handle,axis:data.axis,signs,startClient:new THREE.Vector2(event.clientX,event.clientY),startPoint,plane,box,size,anchor,worldPerPixel,items:items.map(item=>({item,object:viewer.objects.get(item.id),startMatrix:workshopMatrixFromItem(item)})),visuals:visuals.map(object=>({object,startMatrix:object.matrix.clone()})),handles:viewer.helpers.children.filter(child=>child.userData.cadResizeHandle).map(object=>({object,startMatrix:object.matrix.clone()})),moved:false};viewer.resizeAnchor={axis:data.axis,signs};viewer.mode='scale';viewer.transform.detach();viewer.controls.enabled=false;viewer.renderer.domElement.classList.add('cad-handle-resizing');viewer.renderer.domElement.setPointerCapture?.(event.pointerId);$$('[data-cad-mode]').forEach(button=>button.classList.toggle('active',button.dataset.cadMode==='scale'));refreshWorkshopPanels();event.preventDefault();event.stopPropagation();return true;}
function updateWorkshopHandleResize(event){const state=viewer.handleResize;if(!state||event.pointerId!==state.pointerId)return false;const movement=state.startClient.distanceTo(new THREE.Vector2(event.clientX,event.clientY));if(!state.moved&&movement<3)return true;state.moved=true;const desired=state.size.clone();if(state.plane){const point=workshopPointerPlanePoint(event,state.plane);if(point){if(state.axis.includes('X'))desired.x=workshopResizeSnap(Math.abs(point.x-state.anchor.x));if(state.axis.includes('Z'))desired.z=workshopResizeSnap(Math.abs(point.z-state.anchor.z));}}if(state.axis.includes('Y'))desired.y=workshopResizeSnap(state.size.y-(event.clientY-state.startClient.y)*state.worldPerPixel*state.signs.y);const scale=new THREE.Vector3(state.axis.includes('X')?desired.x/Math.max(.001,state.size.x):1,state.axis.includes('Y')?desired.y/Math.max(.001,state.size.y):1,state.axis.includes('Z')?desired.z/Math.max(.001,state.size.z):1),delta=new THREE.Matrix4().makeTranslation(state.anchor.x,state.anchor.y,state.anchor.z).multiply(new THREE.Matrix4().makeScale(scale.x,scale.y,scale.z)).multiply(new THREE.Matrix4().makeTranslation(-state.anchor.x,-state.anchor.y,-state.anchor.z));for(const entry of state.items)applyMatrixToWorkshopItem(delta.clone().multiply(entry.startMatrix),entry.item,entry.object);for(const entry of state.visuals){const matrix=delta.clone().multiply(entry.startMatrix),position=new THREE.Vector3(),quaternion=new THREE.Quaternion(),objectScale=new THREE.Vector3();matrix.decompose(position,quaternion,objectScale);entry.object.position.copy(position);entry.object.quaternion.copy(quaternion);entry.object.scale.copy(objectScale);entry.object.updateMatrixWorld(true);}for(const entry of state.handles){const position=new THREE.Vector3().setFromMatrixPosition(delta.clone().multiply(entry.startMatrix));entry.object.position.copy(position);entry.object.updateMatrixWorld(true);}viewer.helpers.children.forEach(child=>child.isBoxHelper&&child.update?.());positionWorkshopDimensionOverlay();event.preventDefault();return true;}
function finishWorkshopHandleResize(event){const state=viewer.handleResize;if(!state||event?.pointerId!==state.pointerId)return false;viewer.handleResize=null;releaseWorkshopPointer(state.pointerId);viewer.renderer.domElement.classList.remove('cad-handle-resizing');viewer.controls.enabled=viewer.cameraModifier;if(state.moved){commitWorkshopChange();refreshWorkshopSelection();toast('Selection resized · the opposite edge stayed fixed');}else refreshWorkshopSelection();return true;}
function cancelWorkshopHandleResize(){const state=viewer.handleResize;if(!state)return;viewer.handleResize=null;releaseWorkshopPointer(state.pointerId);viewer.renderer?.domElement?.classList.remove('cad-handle-resizing');viewer.controls.enabled=viewer.cameraModifier;refreshWorkshopSelection();}

function renderWorkshopDimensionOverlay(){const overlay=$('#cadDimensionOverlay'),items=selectedWorkshopItems();if(!overlay)return;if(!items.length||!THREE){overlay.classList.add('hidden');overlay.innerHTML='';return;}const size=workshopSelectionSize(),labels=['Width','Height','Depth'],letters=['X','Y','Z'];overlay.classList.remove('hidden');overlay.innerHTML=[0,2,1].map(axis=>`<i class="cad-dimension-line" data-cad-dimension-line="${axis}"></i><label class="cad-dimension-value axis-${letters[axis].toLowerCase()}" data-cad-dimension-value="${axis}"><b>${letters[axis]}</b><input type="number" min="0.001" step="0.5" data-cad-measure-size="${axis}" value="${Number(size[axis]||0).toFixed(2)}" aria-label="${labels[axis]} in millimetres"><em>mm</em></label>`).join('');overlay.querySelectorAll('[data-cad-measure-size]').forEach(input=>{const apply=()=>{if(input.dataset.cadCommitted===input.value)return;input.dataset.cadCommitted=input.value;const axis=Number(input.dataset.cadMeasureSize),letter=letters[axis];if(!viewer.resizeAnchor?.axis?.includes(letter))viewer.resizeAnchor={axis:letter,signs:{x:1,y:1,z:1}};input.dataset.cadHudSize=String(axis);applyWorkshopHudSize(input);};input.onfocus=()=>{const axis=Number(input.dataset.cadMeasureSize),letter=letters[axis];if(!viewer.resizeAnchor?.axis?.includes(letter))viewer.resizeAnchor={axis:letter,signs:{x:1,y:1,z:1}};};input.onchange=apply;input.onblur=apply;input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();apply();input.blur();}};});positionWorkshopDimensionOverlay();}
function positionWorkshopDimensionOverlay(){const overlay=$('#cadDimensionOverlay');if(!overlay||overlay.classList.contains('hidden')||!viewer.camera||!viewer.renderer)return;const visuals=workshopSelectionVisuals(),box=workshopVisualBounds(visuals);if(box.isEmpty())return;const size=box.getSize(new THREE.Vector3()),pad=Math.max(1.7,Math.max(size.x,size.y,size.z)*.08),points={0:[new THREE.Vector3(box.min.x,box.min.y,box.max.z+pad),new THREE.Vector3(box.max.x,box.min.y,box.max.z+pad)],1:[new THREE.Vector3(box.max.x+pad,box.min.y,box.max.z+pad),new THREE.Vector3(box.max.x+pad,box.max.y,box.max.z+pad)],2:[new THREE.Vector3(box.max.x+pad,box.min.y,box.min.z),new THREE.Vector3(box.max.x+pad,box.min.y,box.max.z)]},rect=viewer.renderer.domElement.getBoundingClientRect(),project=point=>{const p=point.clone().project(viewer.camera);return{x:(p.x+1)*rect.width/2,y:(1-p.y)*rect.height/2};},centre=project(box.getCenter(new THREE.Vector3())),selectionSize=workshopSelectionSize(),placements=[];overlay.querySelectorAll('[data-cad-dimension-line]').forEach(line=>{const axis=Number(line.dataset.cadDimensionLine),[a,b]=points[axis].map(project),dx=b.x-a.x,dy=b.y-a.y,length=Math.max(1,Math.hypot(dx,dy)),angle=Math.atan2(dy,dx),mid={x:(a.x+b.x)/2,y:(a.y+b.y)/2},normal={x:-dy/length,y:dx/length},outward=(mid.x-centre.x)*normal.x+(mid.y-centre.y)*normal.y<0?-1:1,offset=axis===1?25:20;line.style.left=`${a.x}px`;line.style.top=`${a.y}px`;line.style.width=`${length}px`;line.style.transform=`rotate(${angle}rad)`;placements.push({axis,x:mid.x+normal.x*offset*outward,y:mid.y+normal.y*offset*outward});});for(let index=0;index<placements.length;index++){const placement=placements[index];for(let previous=0;previous<index;previous++){const other=placements[previous];if(Math.abs(placement.x-other.x)<76&&Math.abs(placement.y-other.y)<34)placement.y=other.y+38;}placement.x=Math.max(45,Math.min(rect.width-45,placement.x));placement.y=Math.max(20,Math.min(rect.height-20,placement.y));const label=overlay.querySelector(`[data-cad-dimension-value="${placement.axis}"]`),input=label?.querySelector('input');if(label){label.style.left=`${placement.x}px`;label.style.top=`${placement.y}px`;}if(input&&document.activeElement!==input)input.value=Number(selectionSize[placement.axis]||0).toFixed(2);}}

function refreshWorkshopSelection(){
  disposeWorkshopSelectionPivot();viewer.resizeDrag=null;
  if(!viewer.helpers)return;for(const h of [...viewer.helpers.children]){viewer.helpers.remove(h);h.traverse?.(child=>{child.geometry?.dispose?.();if(Array.isArray(child.material))child.material.forEach(material=>material.dispose?.());else child.material?.dispose?.();});}
  const items=selectedWorkshopItems(),units=workshopSelectionUnits(items),visuals=workshopSelectionVisuals(),grouped=units.length===1&&units[0].grouped,aligning=viewer.alignmentMode&&units.length>1;visuals.forEach(obj=>{const outline=new THREE.BoxHelper(obj,0x167ba0);outline.material.depthTest=false;outline.material.transparent=true;outline.material.opacity=.9;outline.renderOrder=7;viewer.helpers.add(outline);});
  const canTransform=items.length&&visuals.length&&!items.every(item=>item.locked);viewer.transform.showX=viewer.mode!=='translate';viewer.transform.showY=true;viewer.transform.showZ=viewer.mode!=='translate';
  if(aligning||viewer.mode==='scale'||!canTransform)viewer.transform.detach();else if(items.length===1&&visuals.length===1){viewer.transform.attach(visuals[0]);viewer.transform.setMode(viewer.mode);viewer.transform.setSpace(viewer.mode==='translate'?'world':'local');}else{viewer.transform.attach(createWorkshopSelectionPivot(visuals,items));viewer.transform.setMode(viewer.mode);viewer.transform.setSpace(viewer.mode==='translate'?'world':'local');}
  if(aligning)addWorkshopAlignmentHandles(visuals);else if(items.length&&!items.every(item=>item.locked))addWorkshopResizeHandles(visuals);else if(units.length<2)viewer.alignmentMode=false;
  renderWorkshopDimensionOverlay();
  refreshWorkshopPanels();
}

function workshopObjectRowsHtml(objects){const rows=[],seen=new Set();for(const o of objects){if(o.group_id){if(seen.has(o.group_id))continue;seen.add(o.group_id);const members=objects.filter(x=>x.group_id===o.group_id),selected=members.every(x=>viewer.selection.has(x.id));rows.push(`<button class="cad-object-row cad-group-row ${selected?'selected':''}" data-cad-object="${o.id}"><span>▦</span><span class="grow"><b>Group</b><small>${members.length} shapes · combined</small></span><i title="Grouped printable body">●</i></button>`);continue;}rows.push(`<button class="cad-object-row ${viewer.selection.has(o.id)?'selected':''} ${o.operation==='hole'?'hole':''}" data-cad-object="${o.id}"><span>${o.kind==='model'?'◆':cadPrimitiveMeta[o.kind]?.[1]||'◇'}</span><span class="grow"><b>${esc(o.name)}</b><small>${o.operation==='hole'?'Hole':o.kind==='model'?'Library model':o.kind}</small></span><i title="${o.visible?'Visible':'Hidden'}">${o.visible?'◉':'○'}</i><i title="${o.locked?'Locked':'Unlocked'}">${o.locked?'▣':''}</i></button>`);}return rows.join('');}
function workshopSelectionSize(){const items=selectedWorkshopItems();if(!items.length||!THREE)return [0,0,0];if(items.length===1)return items[0].size.map((v,i)=>Math.abs(v*items[0].scale[i]));const box=new THREE.Box3();workshopSelectionVisuals().forEach(o=>box.expandByObject(o));const size=box.isEmpty()?new THREE.Vector3():box.getSize(new THREE.Vector3());return [size.x,size.y,size.z];}
function applyWorkshopHudSize(input){const axis=Number(input.dataset.cadHudSize),value=Math.max(.001,Math.abs(Number(input.value)));if(!Number.isFinite(value))return;const items=selectedWorkshopItems(),letter=['X','Y','Z'][axis],key=letter.toLowerCase(),sign=viewer.resizeAnchor?.axis?.includes(letter)?viewer.resizeAnchor.signs[key]:1;if(items.length===1){const item=items[0],old=Math.abs(item.size[axis]*item.scale[axis]);if(Math.abs(old-value)<1e-6)return;const shift=new THREE.Vector3().setComponent(axis,sign*(value-old)/2).applyQuaternion(new THREE.Quaternion().setFromEuler(new THREE.Euler(...item.rotation.map(THREE.MathUtils.degToRad))));item.position=item.position.map((n,i)=>Number((n+shift.getComponent(i)).toFixed(6)));item.scale[axis]=(Math.sign(item.scale[axis])||1)*value/Math.max(.001,item.size[axis]);const object=viewer.objects.get(item.id);if(object)applyWorkshopTransform(object,item);}else if(items.length>1){const size=workshopSelectionSize(),old=size[axis];if(old<1e-6||Math.abs(old-value)<1e-6)return;const box=new THREE.Box3();workshopSelectionVisuals().forEach(o=>box.expandByObject(o));const center=box.getCenter(new THREE.Vector3()),anchor=center.clone().setComponent(axis,center.getComponent(axis)-sign*old/2),scale=new THREE.Vector3(1,1,1).setComponent(axis,value/old),delta=new THREE.Matrix4().makeTranslation(anchor.x,anchor.y,anchor.z).multiply(new THREE.Matrix4().makeScale(scale.x,scale.y,scale.z)).multiply(new THREE.Matrix4().makeTranslation(-anchor.x,-anchor.y,-anchor.z));items.forEach(item=>applyMatrixToWorkshopItem(delta.clone().multiply(workshopMatrixFromItem(item)),item,viewer.objects.get(item.id)));}commitWorkshopChange();if(items.some(item=>item.group_id))rebuildWorkshopObjects();else refreshWorkshopSelection();}
function workshopModeControls(){return `<div class="cad-mode-tabs" aria-label="Selection tool"><button data-cad-quick-mode="translate" class="${viewer.mode==='translate'?'active':''}" title="Drag the model across the workplane">Move</button><button data-cad-quick-mode="scale" class="${viewer.mode==='scale'?'active':''}" title="Resize one side or type a measurement">Resize</button><button data-cad-quick-mode="rotate" class="${viewer.mode==='rotate'?'active':''}" title="Rotate around the selected centre">Rotate</button></div>`;}

function refreshWorkshopPanels(){
  if(!viewer.design)return;const objects=viewer.design.document.objects||[],selected=selectedWorkshopItems(),units=workshopSelectionUnits(selected),groupedSelection=units.length===1&&units[0].grouped,selectedCount=units.length;
  const shell=$('.workshop-cad');if(shell)shell.dataset.selectedObjects=[...viewer.selection].join(',');
  const list=$('#cadObjectList');if(list)list.innerHTML=objects.length?workshopObjectRowsHtml(objects):'<div class="cad-empty-small">No objects yet.<br>Add a shape or library model.</div>';
  const groups=new Set(objects.map(x=>x.group_id).filter(Boolean)),visibleRows=objects.filter(x=>!x.group_id).length+groups.size,count=$('#cadObjectCount');if(count)count.textContent=groups.size?`${visibleRows} item${visibleRows===1?'':'s'} · ${objects.length} shapes`:`${objects.length} object${objects.length===1?'':'s'}`;
  const designOption=$(`#cadDesignSelect option[value="${viewer.design.id}"]`);if(designOption)designOption.textContent=`${viewer.design.name} · ${objects.length} parts`;
  const status=$('#cadSelectionStatus');if(status)status.textContent=selected.length?`${selectedCount} selected · ${units.map(unit=>unit.grouped?'Group':unit.items[0].name).join(', ')}`:`${objects.length} part${objects.length===1?'':'s'} · click or drag-box to select`;
  const emptyHint=$('#cadEmptyHint');if(emptyHint)emptyHint.classList.toggle('hidden',objects.length>0);
  const hud=$('#cadSelectionHud');if(hud){const label=groupedSelection?'Group':selectedCount===1?units[0].items[0].name:`${selectedCount} items selected`,size=workshopSelectionSize(),modeHelp=viewer.mode==='translate'?'Hold left-click on the model and drag to move':viewer.mode==='rotate'?'Left-drag the model to move · use a ring to rotate':'Left-drag the model to move · use a square to resize';hud.classList.toggle('hidden',!selected.length);hud.classList.toggle('resize-values',viewer.mode==='scale'&&!!selected.length);hud.classList.toggle('aligning',viewer.alignmentMode&&selectedCount>1);hud.innerHTML=!selected.length?'':`<div><strong>${viewer.mode==='scale'?'Resize ':''}${esc(label)}</strong><small>${viewer.alignmentMode&&selectedCount>1?'Choose a black alignment dot or a labelled edge':modeHelp}</small></div>${workshopModeControls()}${viewer.mode==='scale'?`<div class="cad-inline-dimensions">${['X','Y','Z'].map((axis,i)=>`<label class="${viewer.resizeAnchor?.axis?.includes(axis)?'active':''}"><span>${axis}</span><input type="number" min="0.001" step="0.5" data-cad-hud-size="${i}" value="${Number(size[i]||0).toFixed(3)}"><em>mm</em></label>`).join('')}</div>`:''}${selectedCount>1?`<button data-cad-action="align" class="${viewer.alignmentMode?'active':''}">${viewer.alignmentMode?'Done':'Align'}</button>`:groupedSelection?'<span class="cad-hud-badge">Combined</span>':''}<button data-cad-action="focus">Focus</button>`;hud.querySelectorAll('[data-cad-action]').forEach(b=>b.onclick=()=>runWorkshopAction(b.dataset.cadAction));hud.querySelectorAll('[data-cad-quick-mode]').forEach(button=>button.onclick=()=>setWorkshopMode(button.dataset.cadQuickMode));hud.querySelectorAll('[data-cad-hud-size]').forEach(input=>{const apply=()=>{if(input.dataset.cadCommitted===input.value)return;input.dataset.cadCommitted=input.value;applyWorkshopHudSize(input);};input.onchange=apply;input.onblur=apply;input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();apply();input.blur();}};});}
  renderWorkshopInspector(selected);renderWorkshopReadiness();
  $$('[data-cad-action="undo"]').forEach(b=>b.disabled=viewer.historyIndex<=0);$$('[data-cad-action="redo"]').forEach(b=>b.disabled=viewer.historyIndex>=viewer.history.length-1);
  $$('[data-cad-action="align"]').forEach(button=>{button.disabled=selectedCount<2;button.classList.toggle('active',viewer.alignmentMode&&selectedCount>1);});
}

globalThis.LayerVaultCadSelect=(id,shift,event)=>{event?.stopPropagation?.();if(!viewer.design)return false;const item=viewer.design.document.objects.find(o=>o.id===id),related=item?.group_id?viewer.design.document.objects.filter(o=>o.group_id===item.group_id).map(o=>o.id):[id];if(shift){related.forEach(partId=>viewer.selection.has(partId)?viewer.selection.delete(partId):viewer.selection.add(partId));}else viewer.selection=new Set(related);refreshWorkshopSelection();return false;};

function workshopAlignmentControls(){const definitions={x:['Left','Centre','Right'],y:['Bottom','Middle','Top'],z:['Front','Centre','Back']};return `<div class="cad-align-panel"><div><b>Alignment</b><small>Choose an edge or centre on each axis</small></div>${Object.entries(definitions).map(([axis,labels])=>`<div class="cad-align-row"><span>${axis.toUpperCase()}</span>${['min','center','max'].map((mode,index)=>`<button data-cad-align="${axis}:${mode}" class="${viewer.alignmentTarget?.axis===axis&&viewer.alignmentTarget?.mode===mode?'active':''}" title="Align ${labels[index].toLowerCase()} on ${axis.toUpperCase()}"><i></i><em>${labels[index]}</em></button>`).join('')}</div>`).join('')}</div>`;}
function renderWorkshopInspector(selected){const body=$('#cadInspectorBody');if(!body)return;if(!selected.length){body.innerHTML='<div class="cad-inspector-empty"><span>◇</span><b>Select a shape</b><small>Click any object on the workplane or in the Objects list to edit it precisely.</small></div>';return;}const units=workshopSelectionUnits(selected),grouped=units.length===1&&units[0].grouped;if(grouped){body.innerHTML=`<div class="cad-multi cad-group-inspector"><span class="cad-group-symbol">▦</span><b>Grouped printable part</b><small>${selected.length} editable shapes are locked together. Move, rotate and resize affect the complete combined part.</small>${workshopModeControls()}<button class="ghost full" data-cad-local="ungroup">Ungroup to edit shapes</button></div>`;body.querySelectorAll('[data-cad-quick-mode]').forEach(button=>button.onclick=()=>setWorkshopMode(button.dataset.cadQuickMode));return;}if(units.length>1){body.innerHTML=`<div class="cad-multi"><b>${units.length} items selected</b><small>Groups stay locked together while you move or align them with other shapes.</small><button class="ghost full ${viewer.alignmentMode?'active':''}" data-cad-local="align">${viewer.alignmentMode?'Done aligning':'Align selected items'}</button>${viewer.alignmentMode?workshopAlignmentControls():''}<button class="primary full" data-cad-local="group">Group as printable part</button></div>`;return;}const o=units[0].items[0],size=o.size.map((v,i)=>Math.abs(v*o.scale[i]));body.innerHTML=`
  <label class="cad-name-field"><span>Name</span><input data-cad-name value="${esc(o.name)}"></label>
  ${o.kind==='text'?`<div class="cad-text-settings"><label><span>Printable text</span><input data-cad-text maxlength="18" value="${esc(cadPrintableText(o.params?.text))}" spellcheck="false"></label><label><span>Font</span><select data-cad-font>${Object.entries(cadTextFonts).map(([value,label])=>`<option value="${value}" ${(o.params?.font||'classic')===value?'selected':''}>${label}</option>`).join('')}</select></label><small>Resize X/Z for the lettering face and Y for extrusion thickness.</small></div>`:''}
  <div class="cad-operation"><button data-cad-operation="solid" class="${o.operation==='solid'?'active':''}"><span>●</span> Solid</button><button data-cad-operation="hole" class="${o.operation==='hole'?'active':''}"><span>◌</span> Hole</button></div>
  <div class="cad-color-row"><span>Colour</span><input type="color" data-cad-color value="${esc(o.color||'#67bea9')}" aria-label="Shape colour"><div>${['#67bea9','#5b8def','#8b6fe8','#f0a35e','#ef6f7d','#f2cc5c'].map(c=>`<button style="--swatch:${c}" data-cad-color-preset="${c}" title="Use ${c}"></button>`).join('')}</div></div>
  ${cadVectorEditor('Position',o.position,'position','mm',.5)}${cadVectorEditor('Rotation',o.rotation,'rotation','°',5)}${cadVectorEditor('Size',size,'size','mm',.5)}
  <div class="cad-inspector-toggles"><label><input type="checkbox" data-cad-toggle="visible" ${o.visible!==false?'checked':''}> Visible</label><label><input type="checkbox" data-cad-toggle="locked" ${o.locked?'checked':''}> Locked</label></div>
  <div class="cad-mini-actions"><button data-cad-local="duplicate">Duplicate</button><button data-cad-local="drop">Drop to bed</button><button class="subtle-danger" data-cad-local="delete">Delete</button></div><div class="cad-mirror-actions"><span>Mirror</span><button data-cad-local="mirror-x">X</button><button data-cad-local="mirror-y">Y</button><button data-cad-local="mirror-z">Z</button></div>`;
}

function replaceWorkshopPrimitive(item){if(!item||item.kind==='model'||item.group_id)return rebuildWorkshopObjects();const old=viewer.objects.get(item.id);if(old){viewer.root.remove(old);disposeObject(old);}const object=makePrimitiveObject(item);applyWorkshopTransform(object,item);viewer.root.add(object);viewer.objects.set(item.id,object);viewer.root.updateMatrixWorld(true);refreshWorkshopSelection();return Promise.resolve();}
function updateWorkshopText(input){const o=selectedWorkshopItems()[0];if(!o||o.kind!=='text')return;const value=cadPrintableText(input.value),previous=cadPrintableText(o.params?.text);input.value=value;if(value===previous)return;o.params={...(o.params||{}),text:value,font:cadTextFonts[o.params?.font]?o.params.font:'classic'};if(!o.name||o.name==='Text'||o.name===`Text · ${previous}`)o.name=`Text · ${value}`;commitWorkshopChange();replaceWorkshopPrimitive(o);toast(`Printable text changed to “${value}”`);}
function updateWorkshopTextFont(select){const o=selectedWorkshopItems()[0];if(!o||o.kind!=='text')return;const font=cadTextFonts[select.value]?select.value:'classic';if((o.params?.font||'classic')===font)return;o.params={...(o.params||{}),text:cadPrintableText(o.params?.text),font};commitWorkshopChange();replaceWorkshopPrimitive(o);toast(`${cadTextFonts[font]} lettering applied`);}

function cadVectorEditor(label,values,prop,suffix,step){return `<div class="cad-vector"><div><b>${label}</b><small>${suffix}</small></div><div>${['X','Y','Z'].map((a,i)=>`<label><span>${a}</span><input type="number" step="${step}" data-cad-value="${prop}" data-cad-axis="${i}" value="${Number(values[i]).toFixed(3)}"></label>`).join('')}</div></div>`;}

function applyWorkshopInspectorValue(input){const o=selectedWorkshopItems()[0];if(!o)return;const prop=input.dataset.cadValue,i=Number(input.dataset.cadAxis),value=Number(input.value);if(!Number.isFinite(value))return;const next=prop==='size'?(Math.sign(o.scale[i])||1)*Math.max(.001,Math.abs(value))/Math.max(.001,o.size[i]):value;const current=prop==='size'?o.scale[i]:o[prop][i];if(Math.abs(current-next)<1e-7)return;if(prop==='size')o.scale[i]=next;else o[prop][i]=next;const object=viewer.objects.get(o.id);if(object)applyWorkshopTransform(object,o);commitWorkshopChange();refreshWorkshopSelection();}

function renderWorkshopReadiness(){const box=$('#cadReadiness');if(!box||!viewer.design)return;const objects=viewer.design.document.objects||[],solids=objects.filter(o=>o.visible!==false&&o.operation==='solid').length,holes=objects.filter(o=>o.visible!==false&&o.operation==='hole').length,last=state.models.find(m=>m.id===viewer.design.last_export_model_id);box.innerHTML=`<div class="cad-panel-head"><strong>Print readiness</strong><small>Exported geometry</small></div><div class="cad-ready-summary"><span class="${last?.health?healthClass(last.health.grade):'unknown'}">${last?.health?last.health.score:'—'}</span><div><b>${last?.health?`${esc(last.health.grade)} · ${last.health.score}/100`:'Ready for first export'}</b><small>${last?.health?'Latest exported STL analysed by Model Health.':'The editable design is checked after solid/hole composition.'}</small></div></div><div class="cad-ready-facts"><span><b>${solids}</b> solids</span><span><b>${holes}</b> holes</span><span><b>${objects.length}</b> parts</span></div>${last?`<button class="ghost full" id="cadViewLastExport">View latest health report</button>`:''}`;if($('#cadViewLastExport'))$('#cadViewLastExport').onclick=()=>modelModal(last.id);}

function markWorkshopDirty(){viewer.dirty=true;const stateEl=$('#cadSaveState');if(stateEl){stateEl.textContent='Unsaved changes';stateEl.classList.add('dirty');}clearTimeout(viewer.saveTimer);viewer.saveTimer=setTimeout(()=>saveWorkshopDesign(true),900);}
function commitWorkshopChange(){viewer.history=viewer.history.slice(0,viewer.historyIndex+1);const next=cadClone(viewer.design.document);if(JSON.stringify(viewer.history.at(-1))!==JSON.stringify(next)){viewer.history.push(next);viewer.historyIndex=viewer.history.length-1;if(viewer.history.length>60){viewer.history.shift();viewer.historyIndex--;}}markWorkshopDirty();refreshWorkshopPanels();}

async function saveWorkshopDesign(silent=false){if(!viewer.design)return null;if(!viewer.dirty){if(!silent)toast('Workshop design is already saved');return viewer.design;}clearTimeout(viewer.saveTimer);try{const saved=await api(`/api/workshop/designs/${viewer.design.id}`,jsonOpt('PUT',{name:viewer.design.name,revision:viewer.design.revision,document:viewer.design.document}));viewer.design=Object.assign(viewer.design,saved);viewer.dirty=false;const el=$('#cadSaveState');if(el){el.textContent=`Saved · revision ${saved.revision}`;el.classList.remove('dirty');}if(!silent)toast('Editable Workshop design saved');return saved;}catch(e){toast(e.message,true);throw e;}}

function applyWorkshopSnaps(){if(!viewer.transform||!viewer.design)return;const enabled=viewer.design.document.grid.snap!==false,step=Number(viewer.design.document.grid.size_mm||1);viewer.transform.translationSnap=enabled ? step : null;viewer.transform.rotationSnap=enabled ? THREE.MathUtils.degToRad(5) : null;viewer.transform.scaleSnap=enabled ? .05 : null;}
function setWorkshopMode(mode){viewer.mode=mode;viewer.resizeDrag=null;viewer.alignmentMode=false;viewer.alignmentTarget=null;viewer.transform?.setMode(mode);viewer.transform?.setSpace(mode==='translate'?'world':'local');if(viewer.renderer?.domElement)viewer.renderer.domElement.style.cursor='';$$('[data-cad-mode]').forEach(b=>b.classList.toggle('active',b.dataset.cadMode===mode));refreshWorkshopSelection();}
function workshopMatrixFromItem(item){return new THREE.Matrix4().compose(new THREE.Vector3(...item.position),new THREE.Quaternion().setFromEuler(new THREE.Euler(...item.rotation.map(THREE.MathUtils.degToRad))),new THREE.Vector3(...item.scale));}
function applyMatrixToWorkshopItem(matrix,item,obj=null){const position=new THREE.Vector3(),quaternion=new THREE.Quaternion(),scale=new THREE.Vector3();matrix.decompose(position,quaternion,scale);const rotation=new THREE.Euler().setFromQuaternion(quaternion,'XYZ');item.position=[position.x,position.y,position.z].map(n=>Number(n.toFixed(6)));item.rotation=[rotation.x,rotation.y,rotation.z].map(n=>Number(THREE.MathUtils.radToDeg(n).toFixed(6)));item.scale=[scale.x,scale.y,scale.z].map(n=>Number(n.toFixed(6)));if(obj){obj.position.copy(position);obj.quaternion.copy(quaternion);obj.scale.copy(scale);obj.updateMatrixWorld(true);}}
function beginDirectionalResize(){const target=viewer.transform?.object;if(!target)return;const axis=viewer.transform.axis||'XYZ',localPoint=viewer.transform.pointStart?.clone?.().applyQuaternion(viewer.transform.worldQuaternionStart.clone().invert())||new THREE.Vector3(1,1,1),signs={x:Math.sign(localPoint.x)||1,y:Math.sign(localPoint.y)||1,z:Math.sign(localPoint.z)||1},box=new THREE.Box3();workshopSelectionVisuals().forEach(o=>box.expandByObject(o));const size=box.isEmpty()?new THREE.Vector3(20,20,20):box.getSize(new THREE.Vector3());viewer.resizeAnchor={axis,signs};viewer.resizeDrag={axis,signs,size,startPosition:target.position.clone(),startScale:target.scale.clone(),startQuaternion:target.quaternion.clone()};refreshWorkshopPanels();}
function anchorDirectionalScale(target){const drag=viewer.resizeDrag;if(!drag||viewer.mode!=='scale')return;const shift=new THREE.Vector3();for(const [letter,i] of [['X',0],['Y',1],['Z',2]])if(drag.axis.includes(letter)){const key=letter.toLowerCase(),delta=drag.size.getComponent(i)*(Math.abs(target.scale.getComponent(i)/drag.startScale.getComponent(i))-1);shift.setComponent(i,drag.signs[key]*delta/2);}shift.applyQuaternion(drag.startQuaternion);target.position.copy(drag.startPosition).add(shift);target.updateMatrixWorld(true);}
function syncWorkshopSelectionTransform(){const state=viewer.selectionTransform;if(!state)return;anchorDirectionalScale(state.pivot);state.pivot.updateMatrix();const delta=state.pivot.matrix.clone().multiply(state.startPivotInverse);for(const entry of state.items){const matrix=delta.clone().multiply(entry.startMatrix);applyMatrixToWorkshopItem(matrix,entry.item,entry.object);}for(const entry of state.visuals){const matrix=delta.clone().multiply(entry.startMatrix),p=new THREE.Vector3(),q=new THREE.Quaternion(),s=new THREE.Vector3();matrix.decompose(p,q,s);entry.object.position.copy(p);entry.object.quaternion.copy(q);entry.object.scale.copy(s);entry.object.updateMatrixWorld(true);}}
function syncSelectedTransformToDocument(){if(viewer.selectionTransform){syncWorkshopSelectionTransform();refreshWorkshopPanels();return;}const item=selectedWorkshopItems()[0],obj=selectedWorkshopObjects()[0];if(!item||!obj)return;anchorDirectionalScale(obj);item.position=[obj.position.x,obj.position.y,obj.position.z].map(n=>Number(n.toFixed(6)));item.rotation=[obj.rotation.x,obj.rotation.y,obj.rotation.z].map(n=>Number(THREE.MathUtils.radToDeg(n).toFixed(6)));item.scale=[obj.scale.x,obj.scale.y,obj.scale.z].map(n=>Number(n.toFixed(6)));refreshWorkshopPanels();}

function workshopDropPosition(event,kind){if(!viewer.renderer||!viewer.camera)return null;const rect=viewer.renderer.domElement.getBoundingClientRect(),pointer=new THREE.Vector2(((event.clientX-rect.left)/rect.width)*2-1,-((event.clientY-rect.top)/rect.height)*2+1),ray=new THREE.Raycaster(),hit=new THREE.Vector3();ray.setFromCamera(pointer,viewer.camera);if(!ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0,1,0),0),hit))return null;const step=viewer.design.document.grid.snap===false?0:Number(viewer.design.document.grid.size_mm||1),size=cadPrimitiveMeta[kind]?.[2]||[20,20,20],snap=n=>step?Math.round(n/step)*step:n;return [snap(hit.x),size[1]/2,snap(hit.z)];}
async function addWorkshopPart(kind,position=null){const o=newWorkshopObject(kind);if(position)o.position=position;viewer.design.document.objects.push(o);viewer.selection=new Set([o.id]);commitWorkshopChange();await rebuildWorkshopObjects();if(kind==='text')requestAnimationFrame(()=>{const input=$('[data-cad-text]');input?.focus();input?.select();});toast(kind==='text'?'Text added · type your wording in the Shape panel':`${o.name} added · drag the arrows to move it`);}
async function addWorkshopLibraryPart(){const id=$('#cadLibraryValue')?.value,model=state.models.find(m=>m.id===id);if(!model)return toast('Choose a library model first',true);const o=newWorkshopObject('model',model);viewer.design.document.objects.push(o);viewer.selection=new Set([o.id]);commitWorkshopChange();await rebuildWorkshopObjects();fitWorkshopView();const input=$('#cadLibrarySearch'),value=$('#cadLibraryValue'),button=$('#cadLibraryAddBtn'),clear=$('#cadLibraryClear');if(input)input.value='';if(value)value.value='';if(button)button.disabled=true;clear?.classList.add('hidden');}
function setWorkshopOperation(operation){selectedWorkshopItems().forEach(o=>{o.operation=operation;if(operation==='hole'&&o.color==='#67bea9')o.color='#ee7f63';});commitWorkshopChange();rebuildWorkshopObjects();}
function setWorkshopColor(color){if(!/^#[0-9a-f]{6}$/i.test(String(color||'')))return;selectedWorkshopItems().forEach(o=>o.color=color);commitWorkshopChange();rebuildWorkshopObjects();}
function duplicateWorkshopSelection(){const items=selectedWorkshopItems();if(!items.length)return;const ids=[],groupCopies=new Map();for(const source of items){const copy=cadClone(source);copy.id=cadId('part');copy.name=`${source.name} copy`;if(source.group_id){if(!groupCopies.has(source.group_id))groupCopies.set(source.group_id,cadId('group'));copy.group_id=groupCopies.get(source.group_id);}copy.position[0]+=Number(viewer.design.document.grid.size_mm||1)*5;copy.position[2]+=Number(viewer.design.document.grid.size_mm||1)*5;viewer.design.document.objects.push(copy);ids.push(copy.id);}viewer.selection=new Set(ids);commitWorkshopChange();rebuildWorkshopObjects();}
function copyWorkshopSelection(){const items=selectedWorkshopItems();if(!items.length)return toast('Select an object or group to copy',true);viewer.clipboard={items:cadClone(items),pasteCount:0};toast(`${workshopSelectionUnits(items).length} object${workshopSelectionUnits(items).length===1?'':'s'} copied`);}
function pasteWorkshopClipboard(){const stored=viewer.clipboard?.items;if(!stored?.length)return toast('Copy an object first',true);const pasteCount=++viewer.clipboard.pasteCount,offset=Number(viewer.design.document.grid.size_mm||1)*5*pasteCount,ids=[],groupCopies=new Map();for(const source of stored){const copy=cadClone(source);copy.id=cadId('part');copy.name=`${String(source.name||'Part').replace(/ copy(?: \d+)?$/,'')} copy`;if(source.group_id){if(!groupCopies.has(source.group_id))groupCopies.set(source.group_id,cadId('group'));copy.group_id=groupCopies.get(source.group_id);}copy.position[0]+=offset;copy.position[2]+=offset;viewer.design.document.objects.push(copy);ids.push(copy.id);}viewer.selection=new Set(ids);commitWorkshopChange();rebuildWorkshopObjects();toast(`Pasted ${workshopSelectionUnits(stored).length} object${workshopSelectionUnits(stored).length===1?'':'s'}`);}
function deleteWorkshopSelection(){if(!viewer.selection.size)return;viewer.design.document.objects=viewer.design.document.objects.filter(o=>!viewer.selection.has(o.id));viewer.selection.clear();commitWorkshopChange();rebuildWorkshopObjects();}
function mirrorWorkshopSelection(axis){const i={x:0,y:1,z:2}[axis];if(i==null)return;for(const unit of workshopSelectionUnits()){const box=workshopVisualBounds(unit.visuals);if(box.isEmpty())continue;const center=box.getCenter(new THREE.Vector3()),scale=new THREE.Vector3(1,1,1).setComponent(i,-1),delta=new THREE.Matrix4().makeTranslation(center.x,center.y,center.z).multiply(new THREE.Matrix4().makeScale(scale.x,scale.y,scale.z)).multiply(new THREE.Matrix4().makeTranslation(-center.x,-center.y,-center.z));unit.items.forEach(item=>applyMatrixToWorkshopItem(delta.clone().multiply(workshopMatrixFromItem(item)),item));}commitWorkshopChange();rebuildWorkshopObjects();}
function dropWorkshopSelection(){for(const unit of workshopSelectionUnits()){const box=workshopVisualBounds(unit.visuals);if(box.isEmpty())continue;const shift=-box.min.y;unit.items.forEach(item=>{item.position[1]=Number((item.position[1]+shift).toFixed(6));});}commitWorkshopChange();rebuildWorkshopObjects();}
function toggleWorkshopAlignment(){const units=workshopSelectionUnits();if(units.length<2)return toast('Select two or more objects or groups to align',true);viewer.alignmentMode=!viewer.alignmentMode;viewer.alignmentTarget=null;refreshWorkshopSelection();}
function alignWorkshopSelection(axis,mode='center'){if(String(axis).includes(':'))[axis,mode]=String(axis).split(':');const i={x:0,y:1,z:2}[axis],units=workshopSelectionUnits().filter(unit=>unit.visuals.length);if(i==null||units.length<2)return;const bounds=units.map(unit=>workshopVisualBounds(unit.visuals)),overall=new THREE.Box3();bounds.forEach(box=>overall.union(box));const target=mode==='min'?overall.min.getComponent(i):mode==='max'?overall.max.getComponent(i):overall.getCenter(new THREE.Vector3()).getComponent(i);units.forEach((unit,index)=>{const box=bounds[index],current=mode==='min'?box.min.getComponent(i):mode==='max'?box.max.getComponent(i):box.getCenter(new THREE.Vector3()).getComponent(i),shift=target-current;unit.items.forEach(item=>{item.position[i]=Number((item.position[i]+shift).toFixed(6));});});viewer.alignmentMode=true;viewer.alignmentTarget={axis,mode};commitWorkshopChange();rebuildWorkshopObjects();toast(`Aligned ${axis.toUpperCase()} · ${mode==='min'?'start':mode==='max'?'end':'centre'}`);}
function groupWorkshopSelection(){const items=selectedWorkshopItems();if(items.length<2)return toast('Select at least two objects to group',true);const id=cadId('group');items.forEach(o=>o.group_id=id);commitWorkshopChange();rebuildWorkshopObjects();toast('Grouped into one printable part · holes are now cut in the preview');}
function ungroupWorkshopSelection(){const items=selectedWorkshopItems();if(!items.some(o=>o.group_id))return toast('The selection is not grouped',true);items.forEach(o=>o.group_id=null);commitWorkshopChange();rebuildWorkshopObjects();toast('Group opened back into editable shapes');}

function undoWorkshop(){if(viewer.historyIndex<=0)return;viewer.historyIndex--;viewer.design.document=cadClone(viewer.history[viewer.historyIndex]);viewer.selection.clear();markWorkshopDirty();rebuildWorkshopObjects();}
function redoWorkshop(){if(viewer.historyIndex>=viewer.history.length-1)return;viewer.historyIndex++;viewer.design.document=cadClone(viewer.history[viewer.historyIndex]);viewer.selection.clear();markWorkshopDirty();rebuildWorkshopObjects();}
function fitWorkshopView(){if(!viewer.camera||!viewer.root)return;const box=new THREE.Box3().setFromObject(viewer.root);if(box.isEmpty()){viewer.camera.position.set(120,90,120);viewer.controls.target.set(0,10,0);return;}const size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3()),max=Math.max(size.x,size.y,size.z)||50;viewer.camera.position.copy(center).add(new THREE.Vector3(max*1.5,max*1.1,max*1.5));viewer.camera.near=Math.max(.01,max/1000);viewer.camera.far=max*100;viewer.camera.updateProjectionMatrix();viewer.controls.target.copy(center);viewer.controls.update();}
function focusWorkshopSelection(){const objects=workshopSelectionVisuals();if(!objects.length)return fitWorkshopView();const box=new THREE.Box3();objects.forEach(o=>box.expandByObject(o));const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()),max=Math.max(size.x,size.y,size.z)||20,direction=viewer.camera.position.clone().sub(viewer.controls.target).normalize();viewer.controls.target.copy(center);viewer.camera.position.copy(center).add(direction.multiplyScalar(max*2.4));viewer.controls.update();}
function setWorkshopView(view){if(!viewer.camera||!viewer.controls)return;const box=viewer.root?new THREE.Box3().setFromObject(viewer.root):null,center=box&&!box.isEmpty()?box.getCenter(new THREE.Vector3()):new THREE.Vector3(0,10,0),size=box&&!box.isEmpty()?box.getSize(new THREE.Vector3()):new THREE.Vector3(60,60,60),distance=Math.max(size.x,size.y,size.z,40)*2.2,dirs={home:new THREE.Vector3(1.25,.9,1.25),top:new THREE.Vector3(0,1,.001),front:new THREE.Vector3(0,.08,1),right:new THREE.Vector3(1,.08,0)},direction=(dirs[view]||dirs.home).normalize();viewer.controls.target.copy(center);viewer.camera.position.copy(center).add(direction.multiplyScalar(distance));viewer.camera.up.set(0,1,0);if(view==='top')viewer.camera.up.set(0,0,-1);viewer.camera.lookAt(center);viewer.controls.update();}
function zoomWorkshop(factor){if(!viewer.camera||!viewer.controls)return;const offset=viewer.camera.position.clone().sub(viewer.controls.target).multiplyScalar(factor);if(offset.length()<5||offset.length()>10000)return;viewer.camera.position.copy(viewer.controls.target).add(offset);viewer.controls.update();}

async function runWorkshopAction(action){
  if(action==='add-library')return addWorkshopLibraryPart();if(action==='save')return saveWorkshopDesign(false);if(action==='export')return exportWorkshopDesign();
  if(action==='duplicate')return duplicateWorkshopSelection();if(action==='delete')return deleteWorkshopSelection();if(action==='drop')return dropWorkshopSelection();if(action==='undo')return undoWorkshop();if(action==='redo')return redoWorkshop();if(action==='fit')return fitWorkshopView();if(action==='focus')return focusWorkshopSelection();
  if(action==='solid'||action==='hole')return setWorkshopOperation(action);if(action==='align')return toggleWorkshopAlignment();if(action==='group')return groupWorkshopSelection();if(action==='ungroup')return ungroupWorkshopSelection();
  if(action.startsWith('mirror-'))return mirrorWorkshopSelection(action.slice(-1));
  if(action==='new-design'){const created=await api('/api/workshop/designs',jsonOpt('POST',{name:'Untitled design',document:defaultWorkshopDocument()}));state.workshopDesignId=created.id;return renderWorkshop();}
  if(action==='delete-design'){if(!(await confirmAction('Delete this Workshop design?','The editable design will be removed. Models already exported to the library remain safe.')))return;await api(`/api/workshop/designs/${viewer.design.id}`,{method:'DELETE'});state.workshopDesignId=null;toast('Workshop design deleted');return renderWorkshop();}
}

function geometryForWorkshopObject(obj){obj.updateMatrixWorld(true);const geometries=[];obj.traverse(mesh=>{if(!mesh.isMesh||!mesh.geometry)return;const g=mesh.geometry.clone();g.applyMatrix4(mesh.matrixWorld);for(const name of Object.keys(g.attributes))if(name!=='position')g.deleteAttribute(name);geometries.push(g);});if(!geometries.length)return null;const merged=geometries.length===1?geometries[0]:BufferGeometryUtils.mergeGeometries(geometries,false);const welded=BufferGeometryUtils.mergeVertices(merged,1e-5);if(welded!==merged)merged.dispose();return welded;}

function manifoldFromWorkshopObject(obj,item){const geometry=geometryForWorkshopObject(obj);if(!geometry)throw new Error(`${item.name} has no triangle geometry`);const position=geometry.getAttribute('position'),vertices=new Float32Array(position.array),sourceIndex=geometry.index?.array||Uint32Array.from({length:position.count},(_,i)=>i),indices=new Uint32Array(sourceIndex);let signed=0;for(let i=0;i<indices.length;i+=3){const ia=indices[i]*3,ib=indices[i+1]*3,ic=indices[i+2]*3,ax=vertices[ia],ay=vertices[ia+1],az=vertices[ia+2],bx=vertices[ib],by=vertices[ib+1],bz=vertices[ib+2],cx=vertices[ic],cy=vertices[ic+1],cz=vertices[ic+2];signed+=ax*(by*cz-bz*cy)+ay*(bz*cx-bx*cz)+az*(bx*cy-by*cx);}if(signed<0)for(let i=0;i<indices.length;i+=3){const swap=indices[i+1];indices[i+1]=indices[i+2];indices[i+2]=swap;}geometry.dispose();let mesh=null;try{mesh=new ManifoldEngine.Mesh({numProp:3,vertProperties:vertices,triVerts:indices,tolerance:1e-5});return new ManifoldEngine.Manifold(mesh);}catch(e){throw new Error(`${item.name} is not a closed printable solid. Run Safe Repair on the source model before using it in a Boolean design.`);}finally{mesh?.delete?.();}}

function geometryFromManifold(manifold){const mesh=manifold.getMesh(),geometry=new THREE.BufferGeometry(),positions=new Float32Array(mesh.numVert*3);for(let i=0;i<mesh.numVert;i++){positions[i*3]=mesh.vertProperties[i*mesh.numProp];positions[i*3+1]=mesh.vertProperties[i*mesh.numProp+1];positions[i*3+2]=mesh.vertProperties[i*mesh.numProp+2];}geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(mesh.triVerts),1));mesh.delete?.();if(BufferGeometryUtils?.toCreasedNormals){const creased=BufferGeometryUtils.toCreasedNormals(geometry,Math.PI/4);geometry.dispose();return creased;}geometry.computeVertexNormals();return geometry;}

function composeWorkshopItemsGeometry(items){const solids=items.filter(o=>o.visible!==false&&o.operation==='solid'),holes=items.filter(o=>o.visible!==false&&o.operation==='hole');if(!solids.length)throw new Error('A group needs at least one visible solid');const inputs=[];let result=null,holeUnion=null;try{const solidValues=solids.map(item=>{const value=manifoldFromWorkshopObject(viewer.objects.get(item.id),item);inputs.push(value);return value;});result=ManifoldEngine.Manifold.union(solidValues);if(holes.length){const holeValues=holes.map(item=>{const value=manifoldFromWorkshopObject(viewer.objects.get(item.id),item);inputs.push(value);return value;});holeUnion=ManifoldEngine.Manifold.union(holeValues);const cut=result.subtract(holeUnion);result.delete?.();result=cut;}if(result.isEmpty())throw new Error('The selected holes remove the complete group');return geometryFromManifold(result);}finally{result?.delete?.();holeUnion?.delete?.();inputs.forEach(value=>value.delete?.());}}

async function workshopExportBlob(){
  const items=(viewer.design.document.objects||[]).filter(o=>o.visible!==false),solids=items.filter(o=>o.operation==='solid'),holes=items.filter(o=>o.operation==='hole');if(!solids.length)throw new Error('Add at least one visible solid before exporting');
  const inputs=[];let result=null,holeUnion=null;
  try{const solidManifolds=solids.map(item=>{const value=manifoldFromWorkshopObject(viewer.objects.get(item.id),item);inputs.push(value);return value;});result=ManifoldEngine.Manifold.union(solidManifolds);if(holes.length){const holeManifolds=holes.map(item=>{const value=manifoldFromWorkshopObject(viewer.objects.get(item.id),item);inputs.push(value);return value;});holeUnion=ManifoldEngine.Manifold.union(holeManifolds);const cut=result.subtract(holeUnion);result.delete?.();result=cut;}if(result.isEmpty())throw new Error('The holes remove the entire solid. Resize or reposition the hole objects.');const geometry=geometryFromManifold(result),mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial());mesh.updateMatrixWorld(true);const blob=new Blob([new STLExporter().parse(mesh,{binary:true})],{type:'model/stl'});geometry.dispose();mesh.material.dispose();return blob;}finally{result?.delete?.();holeUnion?.delete?.();inputs.forEach(value=>value.delete?.());}
}

async function exportWorkshopDesign(){const button=$('[data-cad-action="export"]');button.disabled=true;button.textContent='Composing geometry…';try{await saveWorkshopDesign(true);const blob=await workshopExportBlob();const fd=new FormData(),name=viewer.design.name||'Workshop design';fd.append('file',blob,`${name.replace(/[^a-z0-9._-]+/gi,'_')}.stl`);fd.append('title',name);fd.append('version_label','Workshop export');fd.append('notes',`Exported from editable Workshop design ${viewer.design.id}`);button.textContent='Checking model health…';const result=await api(`/api/workshop/designs/${viewer.design.id}/export`,{method:'POST',body:fd});viewer.design.last_export_model_id=result.model.id;const modelWithHealth={...result.model,health:{score:result.health?.score,grade:result.health?.grade}};const existing=state.models.findIndex(m=>m.id===result.model.id);if(existing>=0)state.models[existing]=modelWithHealth;else state.models.unshift(modelWithHealth);renderWorkshopReadiness();openModal('Print-ready export created',`<div class="cad-export-result"><span class="health-score-orb ${healthClass(result.health?.grade)}">${esc(result.health?.score??'—')}</span><div><span class="kicker">Model Health</span><h3>${esc(result.health?.grade||'Analysis complete')}</h3><p>${esc(result.health?.summary||'The STL was composed and stored in your model lineage.')}</p></div></div><div class="notice"><b>Your editable design remains intact.</b><span>The composed STL is now a library model, with solids and holes resolved for slicing.</span></div>`,`<button class="ghost" data-close-modal>Keep editing</button><button class="primary" id="cadOpenExport">View health report</button>`,'Workshop export');$('#cadOpenExport').onclick=()=>{closeModal();modelModal(result.model.id);};}catch(e){toast(e.message,true);}finally{button.disabled=false;button.textContent='Export & check printability';}}

function resetTransforms() { const item=selectedWorkshopItems()[0];if(!item)return;item.rotation=[0,0,0];item.scale=[1,1,1];commitWorkshopChange();rebuildWorkshopObjects(); }
function syncTransforms() {}
function syncDimensionInputs() {}
function applyScaleEdit() {}
function applyDimensionEdit() {}
function exportSTL(){return exportWorkshopDesign();}
function saveWorkshopVersion(){return exportWorkshopDesign();}

function lineageTreeHtml(lineage, currentId) {
  const family = lineage.family || [];
  if (!family.length) return '';
  const byParent = {};
  family.forEach(m => { const key=m.parent_model_id || '__root__'; (byParent[key] ||= []).push(m); });
  const root = family.find(m=>m.id===lineage.root_id) || family.find(m=>!m.parent_model_id) || family[0];
  const branch = (m, depth=0) => `<div class="lineage-node-wrap" style="--depth:${depth}"><button type="button" class="lineage-node ${m.id===currentId?'current':''}" data-lineage-open="${m.id}">
      <span class="lineage-node-thumb">${previewable(m)?`<img ${lazyThumbAttrs(m, m.title)}>`:`<b>${esc(m.extension.slice(1).toUpperCase())}</b>`}</span>
      <span class="grow"><strong>${esc(m.version_label || (m.parent_model_id?'Variant':'Original'))}</strong><small>${esc(m.title)}</small></span>
      <span class="lineage-kind">${esc(m.derivation_type||'Original')}</span>
    </button>${(byParent[m.id]||[]).map(c=>branch(c,depth+1)).join('')}</div>`;
  return `<div class="lineage-map">${branch(root)}</div>`;
}

function downloadBlob(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

let detailPreview = { renderer: null, scene: null, camera: null, controls: null, object: null, markerGroup: null, center: null, animation: null, observer: null, baseDistance: 0, viewInfo: null };
function disposeDetailPreview() {
  if (detailPreview.animation) cancelAnimationFrame(detailPreview.animation);
  detailPreview.observer?.disconnect?.();
  if (detailPreview.object) disposeObject(detailPreview.object);
  if (detailPreview.renderer) detailPreview.renderer.dispose();
  detailPreview = { renderer: null, scene: null, camera: null, controls: null, object: null, markerGroup: null, center: null, animation: null, observer: null, baseDistance: 0, viewInfo: null };
}
function thumbnailCameraVector(view=DEFAULT_THUMB_VIEW, distance=1) {
  const yaw=THREE.MathUtils.degToRad(Number(view?.yaw_deg ?? DEFAULT_THUMB_VIEW.yaw_deg));
  const pitch=THREE.MathUtils.degToRad(Number(view?.pitch_deg ?? DEFAULT_THUMB_VIEW.pitch_deg));
  return new THREE.Vector3(Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch),Math.cos(yaw)*Math.cos(pitch)).multiplyScalar(distance);
}
function applyDetailThumbnailView(view=DEFAULT_THUMB_VIEW) {
  if(!detailPreview.camera||!detailPreview.controls||!detailPreview.baseDistance)return;
  const zoom=Math.max(.72,Math.min(1.30,Number(view?.zoom||1)));
  detailPreview.camera.position.copy(thumbnailCameraVector(view,detailPreview.baseDistance/zoom));
  detailPreview.controls.target.set(0,0,0); detailPreview.controls.update();
}
function captureDetailThumbnailView() {
  if(!detailPreview.camera||!detailPreview.controls||!detailPreview.baseDistance)return null;
  const v=detailPreview.camera.position.clone().sub(detailPreview.controls.target); const distance=v.length(); if(!distance)return null;
  const yaw=THREE.MathUtils.radToDeg(Math.atan2(v.x,v.z));
  const pitch=THREE.MathUtils.radToDeg(Math.asin(THREE.MathUtils.clamp(v.y/distance,-1,1)));
  const zoom=THREE.MathUtils.clamp(detailPreview.baseDistance/distance,.72,1.30);
  return {yaw_deg:Number(yaw.toFixed(2)),pitch_deg:Number(pitch.toFixed(2)),zoom:Number(zoom.toFixed(3))};
}
async function initDetailPreview(model, viewInfo={effective:DEFAULT_THUMB_VIEW}) {
  disposeDetailPreview();
  if (!previewable(model)) return;
  try { await ensureThreeEngine(); }
  catch (e) {
    const panel = $('#detailPreview');
    const fallback = panel ? $('.detail-preview-fallback', panel) : null;
    if (fallback) fallback.innerHTML = `<div><strong>3D preview unavailable</strong><span style="font-size:9px">${esc(e.message)}</span></div>`;
    return;
  }
  const panel = $('#detailPreview');
  if (!panel) return;
  const fallback = $('.detail-preview-fallback', panel);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf7fafb);
  const camera = new THREE.PerspectiveCamera(38, panel.clientWidth / 280, .1, 10000);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(panel.clientWidth, 280);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = false;
  panel.prepend(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.autoRotate = false;
  controls.enablePan = false;
  scene.add(new THREE.HemisphereLight(0xffffff, 0xe0e8e8, 2.5));
  const dir = new THREE.DirectionalLight(0xffffff, 2.6);
  dir.position.set(80, 130, 90);
  scene.add(dir);
  detailPreview = { renderer, scene, camera, controls, object: null, markerGroup: null, center: null, animation: null, observer: null, baseDistance: 0, viewInfo };
  loadModelObject(model, obj => {
    const root = styleLoadedObject(obj, 0x70bfae);
    const box = new THREE.Box3().setFromObject(root);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    root.position.sub(center);
    const max = Math.max(size.x, size.y, size.z) || 100;
    detailPreview.baseDistance=max*2.35;
    camera.near = Math.max(.01, max / 1000);
    camera.far = max * 100;
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    scene.add(root);
    detailPreview.object = root;
    detailPreview.center = center.clone();
    applyDetailThumbnailView(viewInfo?.effective||DEFAULT_THUMB_VIEW);
    fallback?.classList.add('hidden');
  }, () => {
    if (fallback) fallback.innerHTML = '<div><strong>Preview unavailable</strong><span style="font-size:9px">The model is still safely stored.</span></div>';
  });
  detailPreview.observer = new ResizeObserver(() => {
    if (!panel.clientWidth || !detailPreview.renderer) return;
    camera.aspect = panel.clientWidth / 280;
    camera.updateProjectionMatrix();
    renderer.setSize(panel.clientWidth, 280);
  });
  detailPreview.observer.observe(panel);
  const animate = () => { detailPreview.animation = requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); };
  animate();
}

function clearHealthMarkers() {
  if (!detailPreview.markerGroup || !detailPreview.scene) return;
  detailPreview.scene.remove(detailPreview.markerGroup);
  detailPreview.markerGroup.traverse?.(o => { o.geometry?.dispose?.(); o.material?.dispose?.(); });
  detailPreview.markerGroup = null;
}
function showHealthMarkers(markers=[], tone='warning') {
  if (!detailPreview.scene || !detailPreview.object || !detailPreview.center || !THREE) return toast('3D preview is still loading', true);
  clearHealthMarkers();
  const usable=(markers||[]).filter(x=>Array.isArray(x?.position_mm)&&x.position_mm.length===3).slice(0,24);
  if(!usable.length)return toast('This warning has no representative 3D marker points',true);
  const group=new THREE.Group();
  const radius=Math.max(.08,(detailPreview.baseDistance/2.35)*.012);
  const color=tone==='error'?0xff5268:tone==='info'?0x4b88ff:0xffa92f;
  usable.forEach(m=>{
    const area=Number(m.projected_area_proxy_mm2||m.estimated_sheet_area_mm2||0);const scale=area>0?Math.min(2.4,Math.max(1,Math.sqrt(area)/2.6)):1;
    const g=new THREE.SphereGeometry(radius*scale,16,10); const mat=new THREE.MeshStandardMaterial({color,emissive:color,emissiveIntensity:.32,roughness:.35});
    const sphere=new THREE.Mesh(g,mat); sphere.position.set(Number(m.position_mm[0])-detailPreview.center.x,Number(m.position_mm[1])-detailPreview.center.y,Number(m.position_mm[2])-detailPreview.center.z);group.add(sphere);
    if(m.projected_area_proxy_mm2){const rg=new THREE.TorusGeometry(radius*scale*1.75,radius*.18,8,28);const ring=new THREE.Mesh(rg,mat.clone());ring.rotation.x=Math.PI/2;ring.position.copy(sphere.position);group.add(ring);}
  });
  detailPreview.scene.add(group);detailPreview.markerGroup=group;
  const pocket=usable.some(x=>x.projected_area_proxy_mm2);toast(`${usable.length} representative ${pocket?'suction region':'risk point'}${usable.length===1?'':'s'} highlighted in the model preview`);
}

function openModal(title, body, footer = '', eyebrow = 'LayerVault') {
  disposeDetailPreview();
  if ($('#modal').classList.contains('hidden')) modalReturnFocus = document.activeElement;
  $('#modalTitle').textContent = title;
  $('#modalEyebrow').textContent = eyebrow;
  $('#modalBody').innerHTML = body;
  $('#modalFooter').innerHTML = footer;
  $('#modal').classList.remove('hidden');
  document.body.classList.add('modal-open');
  requestAnimationFrame(() => (focusables($('#modalBody'))[0] || $('[data-close-modal]', $('#modal')))?.focus());
}
function closeModal() {
  disposeDetailPreview();
  $('#modal').classList.add('hidden');
  document.body.classList.remove('modal-open');
  if (modalReturnFocus?.isConnected) modalReturnFocus.focus({preventScroll:true});
  modalReturnFocus = null;
}
function field(name, label, value = '', type = 'text', extra = '', placeholder = '') {
  return `<div class="field ${extra}"><label>${esc(label)}</label><input name="${name}" type="${type}" value="${esc(value)}" ${placeholder ? `placeholder="${esc(placeholder)}"` : ''}></div>`;
}
function selectField(name, label, values, current = '', extra = '') {
  return `<div class="field ${extra}"><label>${esc(label)}</label><select name="${name}">${values.map(v => {
    const val = typeof v === 'string' ? v : v.value;
    const lab = typeof v === 'string' ? v : v.label;
    return `<option value="${esc(val)}" ${String(val) === String(current) ? 'selected' : ''}>${esc(lab)}</option>`;
  }).join('')}</select></div>`;
}
function formDataObject(form) { const data=Object.fromEntries(new FormData(form).entries());if(form?._jobModelPicker){data.models=form._jobModelPicker.value;data.model_id=data.models[0]?.model_id||null;}return data; }

function healthMetric(label, value, tone='') {
  return `<div class="health-metric ${tone}"><span>${esc(label)}</span><strong>${value}</strong></div>`;
}
function healthIssueHtml(issue, markerIndex=null, manufacturing=false) {
  const markerCount=Number(issue?.markers?.length||0);const markerBtn=manufacturing && markerCount ? `<button type="button" class="marker-btn" data-health-marker="${markerIndex}">Show ${markerCount} location${markerCount===1?'':'s'} on model</button>` : '';
  return `<div class="health-issue ${esc(issue.severity||'info')}"><span class="health-issue-icon">${issue.severity==='error'?'×':issue.severity==='warning'?'!':'i'}</span><div class="grow"><strong>${esc(issue.title)}</strong><small>${esc(issue.detail)}</small>${markerBtn}</div>${issue.repairable?'<span class="repairable-tag">Safe repair</span>':''}</div>`;
}
function printabilityMetric(label,value,tone=''){return `<div class="printability-metric ${tone}"><span>${esc(label)}</span><strong>${value}</strong></div>`;}
function manufacturingReportHtml(m, printer) {
  if(!m)return `<div class="printability-select"><span>◇</span><div><strong>Select a printer for manufacturing checks</strong><small>LayerVault will add technology-aware thickness, support and resin/FDM risk screening without changing the cached mesh-integrity score.</small></div></div>`;
  if(!m.available)return `<div class="printability-select"><span>×</span><div><strong>Printability screening unavailable</strong><small>${esc(m.summary||'The selected model could not be screened.')}</small></div></div>`;
  const t=m.thickness||{}; const resin=m.resin||null; const fdm=m.fdm||null;
  let metrics='';
  if(t.available){const substantial=(t.broad_thin_regions||[]).filter(x=>Number(x.estimated_p25_mm||99)<Number(t.caution_threshold_mm||0));const featureEstimate=substantial.length?Math.min(...substantial.map(x=>Number(x.estimated_p10_mm||x.estimated_p25_mm||99))):null;metrics+=printabilityMetric('Exposed thin feature',featureEstimate!=null?`${featureEstimate.toFixed(2)} mm`:'None',featureEstimate==null?'good':featureEstimate<Number(t.critical_threshold_mm||0)?'bad':'warn');metrics+=printabilityMetric('Caution below',`${Number(t.caution_threshold_mm||0).toFixed(2)} mm`);}
  if(resin){const c=resin.enclosed_cavities||{},p=resin.suction_pockets||{},i=resin.unsupported_minima||{},peel=resin.peel_proxy||{};metrics+=printabilityMetric('Cavity candidates',String(c.candidate_count||0),c.candidate_count?'bad':'good');metrics+=printabilityMetric('Suction candidates',String(p.candidate_count||0),p.candidate_count?'warn':'good');metrics+=printabilityMetric('Island-risk points',String(i.candidate_count||0),i.candidate_count?'warn':'good');metrics+=printabilityMetric('Peak peel proxy',peel.available?`${Number(peel.peak_projected_area_mm2||0).toFixed(0)} mm²`:'—');}
  if(fdm){const o=fdm.overhangs||{};metrics+=printabilityMetric('Severe overhang',o.available?`${Number(o.severe_overhang_percent||0).toFixed(1)}%`:'—',Number(o.severe_overhang_percent||0)>5?'warn':'good');metrics+=printabilityMetric('Bridge candidates',String(o.bridge_candidate_faces||0),o.bridge_candidate_faces?'warn':'good');metrics+=printabilityMetric('Bed contact',o.available?`${Number(o.bed_contact_vs_footprint_percent||0).toFixed(1)}%`:'—',Number(o.bed_contact_vs_footprint_percent||100)<1.5?'warn':'good');}
  const prep=resin?.preparation;const prepHtml=resin?`<div class="resin-preparation"><div class="resin-preparation-copy"><span>Resin Preparation</span><strong>${prep?.available?'Create a strengthened child version':'No conservative automatic change needed'}</strong><small>${prep?.available?`Targets ${Number(prep.thin_region_count||0)} substantial thin feature group${Number(prep.thin_region_count||0)===1?'':'s'} and ${Number(prep.suction_candidate_count||0)} suction candidate${Number(prep.suction_candidate_count||0)===1?'':'s'}. It expands the selected surfaces along their local outward directions and can test safer orthogonal orientations.`:'The current screen did not find a substantial exposed thin feature or suction candidate suitable for this conservative preparation pass.'} The original is preserved; drain holes are never guessed automatically.</small></div><div class="resin-preparation-action"><label>Thickness target<input id="resinTargetThickness" type="number" min="0.30" max="2.00" step="0.05" value="${Number(prep?.target_thickness_mm||.5).toFixed(2)}"><em>mm</em></label><button type="button" class="small-btn health-repair-button" data-resin-prepare ${prep?.available?'':'disabled'}>Create Resin Preparation</button></div></div>`:'';
  return `<div class="printability-wrap"><div class="printability-head"><div class="printability-score ${healthClass(m.grade==='Ready'?'Healthy':m.grade)}"><strong>${esc(m.score)}</strong><span>/ 100</span></div><div class="grow"><div class="printability-kicker"><span>${esc(m.technology)} printability</span><b>${esc(m.confidence||'Heuristic screening')}</b></div><h4>${esc(m.summary)}</h4><small>${esc(printer?.name||'Selected printer')} · build direction ${esc(m.build_direction||'+Z')}</small></div></div><div class="printability-note"><strong>What this score means</strong><span>This is separate from Mesh Health. A topologically valid model can still be fragile or difficult to manufacture. These checks are conservative heuristics; confirm final orientation, islands and cups in your slicer's layer preview.</span></div><div class="printability-metrics">${metrics}</div><div class="health-issues manufacturing-issues">${m.issues?.length?m.issues.map((x,i)=>healthIssueHtml(x,i,true)).join(''):'<div class="health-clear"><span>✓</span><div><strong>No strong printer-specific warning detected</strong><small>LayerVault did not find a major risk with its current screening methods.</small></div></div>'}</div>${prepHtml}${m.recommendations?.length?`<div class="health-recommendations"><strong>Printability next steps</strong>${m.recommendations.map(x=>`<p>• ${esc(x)}</p>`).join('')}</div>`:''}</div>`;
}
function healthReportHtml(report) {
  if(!report?.analyzable) return `<div class="health-empty"><span class="health-orb unknown">◇</span><div><strong>${esc(report?.grade||'Unavailable')}</strong><p>${esc(report?.summary||'This file cannot be analysed yet.')}</p></div></div>`;
  const m=report.metrics||{};
  const volume=m.volume_mm3==null?'Open mesh':`${Number(m.volume_mm3).toLocaleString(undefined,{maximumFractionDigits:1})} mm³`;
  const fit=report.printer_fit;
  const fitHtml=fit ? (fit.available ? `<div class="printer-fit ${fit.fits_current_orientation?'good':fit.fits_with_axis_rotation?'review':'bad'}"><div><span>Selected printer fit</span><strong>${fit.fits_current_orientation?'Fits current axes':fit.fits_with_axis_rotation?'Fits after 90° axis rotation':'Does not fit build volume'}</strong></div><small>${fit.model_dimensions_mm.join(' × ')} mm model · ${fit.build_volume_mm.join(' × ')} mm build${fit.margins_mm?` · minimum margin ${Math.min(...fit.margins_mm).toFixed(1)} mm`:''}</small></div>` : `<div class="printer-fit review"><strong>Printer dimensions incomplete</strong><small>${esc(fit.reason||'Build volume is not fully recorded.')}</small></div>`) : '';
  return `<div class="health-summary-row"><div class="health-score ${healthClass(report.grade)}"><strong>${esc(report.score)}</strong><span>/ 100</span></div><div class="grow"><span class="health-grade ${healthClass(report.grade)}">${esc(report.grade)}</span><h4>${esc(report.summary)}</h4><small>Analysed ${report.analyzed_at?fmtDate(report.analyzed_at):'now'} · ${esc(report.engine||'LayerVault Mesh Health')}</small></div></div>
    <div class="health-metrics">${healthMetric('Watertight',m.watertight?'Yes':'No',m.watertight?'good':'warn')}${healthMetric('Open edges',Number(m.boundary_edges||0).toLocaleString(),m.boundary_edges?'warn':'good')}${healthMetric('Non-manifold',Number(m.nonmanifold_edges||0).toLocaleString(),m.nonmanifold_edges?'bad':'good')}${healthMetric('Shells',Number(m.components||0).toLocaleString())}${healthMetric('Degenerate',Number(m.degenerate_faces||0).toLocaleString(),m.degenerate_faces?'warn':'good')}${healthMetric('Duplicates',Number(m.duplicate_faces||0).toLocaleString(),m.duplicate_faces?'warn':'good')}${healthMetric('Surface area',`${Number(m.surface_area_mm2||0).toLocaleString(undefined,{maximumFractionDigits:1})} mm²`)}${healthMetric('Volume',volume)}</div>
    ${fitHtml}
    ${report.notes?.length?`<div class="health-note">${report.notes.map(n=>`<span>${esc(n)}</span>`).join('')}</div>`:''}
    <div class="health-issues">${report.issues?.length?report.issues.map(healthIssueHtml).join(''):'<div class="health-clear"><span>✓</span><div><strong>No topology warnings detected</strong><small>LayerVault found no issue that currently calls for repair.</small></div></div>'}</div>
    ${report.recommendations?.length?`<div class="health-recommendations"><strong>Mesh-health next steps</strong>${report.recommendations.map(x=>`<p>• ${esc(x)}</p>`).join('')}</div>`:''}
    <div class="printability-divider"><span>Manufacturing health</span><small>${report.printer?`Printer-aware screening for ${esc(report.printer.name)}`:'Choose a printer above to evaluate thin geometry and resin/FDM-specific risks.'}</small></div>
    ${manufacturingReportHtml(report.manufacturing,report.printer)}`;
}
async function loadModelHealth(modelId, refresh=false) {
  const body=$('#healthReportBody'); if(!body)return;
  const printer=$('#healthPrinterSelect')?.value||'';
  body.innerHTML='<div class="health-loading"><span></span><strong>Analysing triangle topology…</strong><small>Large high-detail models can take a few seconds the first time; the report is cached afterwards.</small></div>';
  try {
    const qs=new URLSearchParams(); if(printer)qs.set('printer_id',printer); if(refresh)qs.set('refresh','true');
    const report=await api(`/api/models/${modelId}/health?${qs}`); body.innerHTML=healthReportHtml(report);
    $$('[data-health-marker]',body).forEach(btn=>btn.onclick=()=>{const issue=report.manufacturing?.issues?.[Number(btn.dataset.healthMarker)];if(issue)showHealthMarkers(issue.markers,issue.severity);});
    const resinRepair=$('[data-resin-prepare]',body);if(resinRepair)resinRepair.onclick=()=>resinPrepareModel(modelId,printer);
    const repair=$('#healthRepairBtn'); if(repair)repair.hidden=!(report.analyzable&&report.issues?.some(x=>x.repairable));
    const badge=$('#healthHeaderBadge'); if(badge){badge.textContent=`${report.grade} · ${report.score}/100`;badge.className=`health-header-badge ${healthClass(report.grade)}`;}
    const analyse=$('#healthAnalyseBtn'); if(analyse)analyse.textContent='Re-analyse';
    const stateModel=state.models.find(x=>x.id===modelId); if(stateModel)stateModel.health={model_id:modelId,score:report.score,grade:report.grade,analyzed_at:report.analyzed_at};
    const card=document.querySelector(`.model-card[data-model-id="${CSS.escape(modelId)}"] .card-status-stack`); if(card){const old=card.querySelector('.health-mini');if(old)old.remove();card.insertAdjacentHTML('afterbegin',healthMini(stateModel||{health:{score:report.score,grade:report.grade}}));}
    return report;
  } catch(e) { body.innerHTML=`<div class="health-empty"><span class="health-orb issues">×</span><div><strong>Analysis failed</strong><p>${esc(e.message)}</p></div></div>`; toast(e.message,true); }
}
async function safeRepairModel(modelId) {
  if(!(await confirmAction('Create Safe Repair version?','LayerVault will keep the original untouched and create a new STL lineage version using only conservative cleanup operations.','Create repair')))return;
  const btn=$('#healthRepairBtn'); if(btn){btn.disabled=true;btn.textContent='Repairing…';}
  try{
    const result=await api(`/api/models/${modelId}/health/repair`,{method:'POST'});
    if(!result.model){toast(result.message||'No safe repair changes were needed'); if(btn){btn.disabled=false;btn.textContent='Create Safe Repair version';} return;}
    const duplicates=Number(result.after?.metrics?.duplicate_faces||0);
    toast(`${result.reused?'Verified Safe Repair opened':'Safe Repair created'} · ${duplicates} duplicate face${duplicates===1?'':'s'} remaining`);
    await refreshCore(); closeModal(); modelModal(result.model.id, true);
  }catch(e){toast(e.message,true);if(btn){btn.disabled=false;btn.textContent='Create Safe Repair version';}}
}

async function resinPrepareModel(modelId,printerId) {
  if(!printerId)return toast('Select a resin printer first',true);
  const target=Number($('#resinTargetThickness')?.value||.5);
  if(!Number.isFinite(target)||target<.3||target>2)return toast('Choose a thickness target from 0.30 to 2.00 mm',true);
  if(!(await confirmAction('Create Resin Preparation version?',`LayerVault will preserve the original, strengthen broad sheet-like regions toward ${target.toFixed(2)} mm and try a safer orthogonal orientation only when suction risk genuinely improves. It will not add drain holes automatically.`,'Create preparation')))return;
  const btn=$('[data-resin-prepare]');if(btn){btn.disabled=true;btn.textContent='Preparing…';}
  try{
    const result=await api(`/api/models/${modelId}/manufacturing/repair`,jsonOpt('POST',{printer_id:printerId,target_thickness_mm:target}));
    if(!result.model){toast(result.message||'No safe resin-preparation change was accepted',true);if(btn){btn.disabled=false;btn.textContent='Create Resin Preparation';}return;}
    const thin=result.improvements?.broad_thin_regions||[];const cups=result.improvements?.suction_candidates||[];
    toast(`${result.reused?'Verified Resin Preparation opened':'Resin Preparation created'} · thin regions ${thin[0]??'—'} → ${thin[1]??'—'} · suction ${cups[0]??'—'} → ${cups[1]??'—'}`);
    await refreshCore();closeModal();modelModal(result.model.id,true);
  }catch(e){toast(e.message,true);if(btn){btn.disabled=false;btn.textContent='Create Resin Preparation';}}
}

async function modelModal(id, forceHealthRefresh=false) {
  await refreshCore();
  const m = state.models.find(x => x.id === id);
  if (!m) return;
  const [lineage, thumbViewInfo] = await Promise.all([api(`/api/models/${id}/lineage`), api(`/api/models/${id}/thumbnail-view`)]);
  const categories = [...new Set(['Unsorted','Miniatures','Terrain','Functional','Props','Parts','Tools', ...state.taxonomy.categories])];
  const previewMarkup = `
    <div class="model-detail-preview" id="detailPreview">
      <div class="detail-preview-fallback"><div><div class="file-orb">${esc(m.extension.slice(1).toUpperCase())}</div><strong>${previewable(m) ? 'Loading 3D preview…' : 'Preview not available'}</strong><span style="display:block;margin-top:4px;font-size:9px">${previewable(m) ? 'Drag to inspect · choose any angle as the catalogue thumbnail' : 'This file type is stored and catalogued normally.'}</span></div></div>
      <div class="detail-preview-meta"><span class="detail-meta-pill">${esc(m.category)}</span><span class="detail-meta-pill">${esc(dims(m))}</span></div>
    </div>${previewable(m)?`<div class="thumbnail-view-toolbar"><div><strong id="thumbnailViewState">${thumbViewInfo.local&&Object.keys(thumbViewInfo.local).length?'Custom thumbnail angle':thumbViewInfo.inherited?'Inherited thumbnail angle':'Automatic thumbnail angle'}</strong><small>Rotate or zoom the model, then save the catalogue view.</small></div><div class="mini-actions"><button type="button" class="small-btn" id="setThumbViewBtn">Set current view</button><button type="button" class="small-btn" id="resetThumbViewBtn">${m.parent_model_id?'Use inherited':'Use automatic'}</button></div></div>`:''}`;
  openModal(m.title, `
    <div class="model-detail-layout">
      <div class="model-detail-preview-column"><div class="model-detail-preview-sticky">${previewMarkup}</div></div>
      <form id="modelForm" class="fields">
        ${field('title', 'Title', m.title, 'text', 'wide')}
        ${selectField('category', 'Category', categories, m.category)}
        ${field('creator', 'Creator / designer', m.creator)}
        ${field('tags', 'Tags', m.tags?.join(', '), 'text', 'wide', 'miniature, goblin, fantasy')}
        ${field('source_url', 'Source URL', m.source_url, 'url', 'wide', 'https://…')}
        ${field('license', 'Licence', m.license)}
        ${selectField('status', 'Status', ['Ready','Needs repair','Needs supports','Printed','Archived'], m.status)}
        <div class="field wide"><label>Notes</label><textarea name="notes" placeholder="Orientation tips, support notes, scale, folder details…">${esc(m.notes)}</textarea></div>
        <div class="field wide"><label>Stored file</label><div class="detail-file-info"><strong>${esc(m.original_filename)}</strong><small>${esc(m.extension.toUpperCase())} · ${fmtBytes(m.size_bytes)} · ${dims(m)}${m.triangles ? ` · ${Number(m.triangles).toLocaleString()} triangles/faces` : ''}<br><span class="mono">SHA ${esc(m.sha256.slice(0, 16))}…</span></small></div></div>
        <div class="form-section health-section">
          <div class="form-section-title"><span>Model health</span><span id="healthHeaderBadge" class="health-header-badge ${m.health?healthClass(m.health.grade):'unknown'}">${m.health?`${esc(m.health.grade)} · ${esc(m.health.score)}/100`:'Not analysed'}</span></div>
          <div class="health-toolbar"><div class="field"><label>Check against printer</label><select id="healthPrinterSelect"><option value="">No printer · geometry only</option>${state.printers.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select></div><div class="health-actions"><button type="button" class="small-btn" id="healthAnalyseBtn">${m.health?'Re-analyse':'Analyse model'}</button><button type="button" class="small-btn health-repair-button" id="healthRepairBtn" hidden>Create Safe Repair version</button></div></div>
          <div id="healthReportBody">${m.health?'<div class="health-loading passive"><strong>Loading cached health report…</strong></div>':'<div class="health-empty"><span class="health-orb unknown">◇</span><div><strong>Not analysed yet</strong><p>Run Model Health to inspect mesh integrity. Select one of your printers to add thin-feature and resin/FDM-specific manufacturing screening.</p></div></div>'}</div>
        </div>
        <div class="form-section lineage-section">
          <div class="form-section-title"><span>Model lineage</span><span class="lineage-count">${lineage.family.length} version${lineage.family.length===1?'':'s'}</span></div>
          <div class="lineage-current"><span class="lineage-symbol">${m.parent_model_id?'↳':'◇'}</span><div><strong>${esc(m.version_label||'Original')}</strong><small>${m.parent_model_id?`${esc(m.derivation_type||'Derived')} from an earlier version`:'Original source model'}</small></div></div>
          ${lineageTreeHtml(lineage,id)}
          <div class="lineage-actions"><button type="button" class="small-btn" id="linkVersionBtn">Link existing model as a version</button>${previewable(m)?'<button type="button" class="small-btn" id="lineageWorkshopBtn">Create version in Workshop</button>':''}</div>
        </div>
        ${state.projects.length ? `<div class="form-section"><div class="form-section-title">Add this model to a project</div><div class="fields"><div class="field wide"><select id="addProjectSelect"><option value="">Choose project…</option>${state.projects.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select></div>${field('project_qty', 'Quantity', 1, 'number')}${field('project_variant', 'Variant / role', '', 'text', '', 'left arm, 32 mm, roof…')}<div class="field wide"><button type="button" class="small-btn" id="addProjectBtn">＋ Add to selected project</button></div></div></div>` : ''}
      </form>
    </div>`,
    `<button class="danger" id="deleteModelBtn">Delete</button>${m.source_url ? '<button class="ghost" id="sourceModelBtn">Open source</button>' : ''}<button class="ghost" id="downloadModelBtn">Download</button>${previewable(m) ? '<button class="ghost" id="workshopModelBtn">Workshop</button>' : ''}<button class="primary" id="saveModelBtn">Save changes</button>`,
    `Model details · v${document.body.dataset.appVersion||'unknown'}`);

  requestAnimationFrame(() => initDetailPreview(m, thumbViewInfo));
  if (m.health) requestAnimationFrame(() => loadModelHealth(id, forceHealthRefresh));
  if ($('#healthAnalyseBtn')) $('#healthAnalyseBtn').onclick = () => loadModelHealth(id, true);
  if ($('#healthPrinterSelect')) $('#healthPrinterSelect').onchange = () => { if ($('#healthHeaderBadge')?.textContent !== 'Not analysed') loadModelHealth(id, false); };
  if ($('#healthRepairBtn')) $('#healthRepairBtn').onclick = () => safeRepairModel(id);
  if ($('#setThumbViewBtn')) $('#setThumbViewBtn').onclick = async () => {
    const view=captureDetailThumbnailView(); if(!view)return toast('3D preview is still loading',true);
    try{await api(`/api/models/${id}/thumbnail-view`,jsonOpt('PUT',view));$('#thumbnailViewState').textContent='Custom thumbnail angle';toast('Thumbnail view saved · cached preview will regenerate');}
    catch(e){toast(e.message,true);}
  };
  if ($('#resetThumbViewBtn')) $('#resetThumbViewBtn').onclick = async () => {
    try{const info=await api(`/api/models/${id}/thumbnail-view`,{method:'DELETE'});applyDetailThumbnailView(info.effective);$('#thumbnailViewState').textContent=info.inherited?'Inherited thumbnail angle':'Automatic thumbnail angle';toast(info.inherited?'Using inherited family thumbnail angle':'Using automatic thumbnail angle');}
    catch(e){toast(e.message,true);}
  };
  $('#saveModelBtn').onclick = async () => {
    const d = formDataObject($('#modelForm'));
    delete d.project_qty; delete d.project_variant;
    d.tags = d.tags.split(',').map(x => x.trim()).filter(Boolean);
    try { await api(`/api/models/${id}`, jsonOpt('PATCH', d)); toast('Model updated'); closeModal(); renderPage(); }
    catch (e) { toast(e.message, true); }
  };
  $('#downloadModelBtn').onclick = () => location.href = `/api/models/${id}/file?download=true`;
  if ($('#sourceModelBtn')) $('#sourceModelBtn').onclick = () => window.open(m.source_url, '_blank', 'noopener');
  if ($('#workshopModelBtn')) $('#workshopModelBtn').onclick = () => { state.workshopModelId = id; closeModal(); setPage('workshop'); };
  if ($('#lineageWorkshopBtn')) $('#lineageWorkshopBtn').onclick = () => { state.workshopModelId = id; closeModal(); setPage('workshop'); };
  $$('[data-lineage-open]').forEach(b => b.onclick = () => { if (b.dataset.lineageOpen !== id) modelModal(b.dataset.lineageOpen); });
  $('#linkVersionBtn').onclick = () => {
    const candidates = state.models.filter(x => x.id !== id);
    openModal('Link existing version', `<div class="lineage-save-intro"><span class="lineage-symbol">⌁</span><div><strong>Make another library model a child of this version.</strong><small>The file is not changed or duplicated; LayerVault only records its place in the family tree.</small></div></div><form id="linkVersionForm" class="fields">${selectField('child_id','Existing model',candidates.map(x=>({value:x.id,label:x.title})),candidates[0]?.id||'','wide')}${field('version_label','Version label','Variant','text','wide')}${selectField('derivation_type','Change type',['Scaled','Rotated','Mirrored','Repaired','Supported','Hollowed','Remixed','Variant','Modified'],'Variant','wide')}</form>`, `<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="confirmLinkVersion">Link version</button>`, 'Model lineage');
    $('#confirmLinkVersion').onclick = async()=>{ const d=formDataObject($('#linkVersionForm')); if(!d.child_id)return; try{await api(`/api/models/${d.child_id}/lineage/link`,jsonOpt('POST',{parent_model_id:id,version_label:d.version_label,derivation_type:d.derivation_type})); toast('Version linked'); closeModal(); modelModal(id);}catch(e){toast(e.message,true);} };
  };
  $('#deleteModelBtn').onclick = async () => {
    if (!(await confirmAction('Delete model?', `“${m.title}” and its stored file will be permanently removed.`))) return;
    await api(`/api/models/${id}`, { method: 'DELETE' });
    toast('Model deleted'); closeModal(); renderPage();
  };
  if ($('#addProjectBtn')) $('#addProjectBtn').onclick = async () => {
    const pid = $('#addProjectSelect').value;
    if (!pid) return toast('Choose a project first', true);
    const quantity = Math.max(1, Number($('[name=project_qty]').value || 1));
    const variant = $('[name=project_variant]').value.trim();
    try { await api(`/api/projects/${pid}/models/${id}`, jsonOpt('POST', { quantity, variant })); toast('Added to project'); } catch(e) { toast(e.message || 'Could not add model to project', true); }
  };
}

function uploadWizard(files) {
  const list = [...files];
  const folder=state.page==='library'&&!state.library.unfiled?collectionById(state.library.collectionId):null;
  const targetFolderId=folder?.kind==='manual'?folder.id:'';
  openModal('Add models', `
    <form id="uploadMeta" class="fields">
      ${targetFolderId?`<div class="field wide"><div class="upload-folder-target"><span class="folder-glyph small"><i></i></span><div><strong>File into ${esc(collectionPathLabel(folder))}</strong><small>Uploaded models will be added to the folder you are currently viewing.</small></div></div></div>`:''}
      ${selectField('category', 'Category', ['Unsorted','Miniatures','Terrain','Functional','Props','Parts','Tools'], 'Unsorted')}
      ${field('tags', 'Tags', '', 'text', '', 'fantasy, terrain, 28mm')}
      ${field('creator', 'Creator / designer', '', 'text', 'wide')}
      ${field('source_url', 'Source URL', '', 'url', 'wide', 'Optional source / purchase page')}
      ${field('license', 'Licence', '', 'text', 'wide', 'Personal use, CC BY, commercial…')}
      <div class="field wide"><label>Notes applied to these files</label><textarea name="notes" placeholder="Collection name, scale, support notes…"></textarea></div>
      <div class="field wide"><label>Files and library names (${list.length})</label><div class="upload-list renameable">${list.map((f,i) => `<div class="upload-item upload-rename-item"><span class="upload-file-meta"><strong>${esc(f.name)}</strong><small>${fmtBytes(f.size)}</small></span><label><span>Library name</span><input type="text" data-upload-title="${i}" value="${esc(f.name.replace(/\.[^.]+$/,''))}" maxlength="180" autocomplete="off"></label></div>`).join('')}</div><small class="field-note">Rename each model before it is added. The original filename is still retained for traceability.</small></div>
    </form>`,
    `<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="startUpload">Upload ${list.length} file${list.length === 1 ? '' : 's'}</button>`,
    'Library import');
  $('#startUpload').onclick = async () => {
    const meta = formDataObject($('#uploadMeta'));
    let added = 0, dupes = 0, failed = 0; const importedIds=[];
    $('#startUpload').disabled = true;
    $('#startUpload').textContent = `Uploading 0 / ${list.length}`;
    for (let i = 0; i < list.length; i++) {
      const f = list[i];
      const fd = new FormData();
      fd.append('file', f);
      Object.entries(meta).forEach(([k, v]) => fd.append(k, v));
      fd.append('title', $(`[data-upload-title="${i}"]`)?.value.trim() || f.name.replace(/\.[^.]+$/,''));
      try {
        const r = await api('/api/models/upload', { method: 'POST', body: fd });
        if (r.zip) for (const x of r.items) { x.created ? added++ : dupes++; if(x.model?.id)importedIds.push(x.model.id); }
        else { r.created ? added++ : dupes++; if(r.model?.id)importedIds.push(r.model.id); }
      } catch (e) { failed++; toast(`${f.name}: ${e.message}`, true); }
      $('#startUpload').textContent = `Uploading ${i + 1} / ${list.length}`;
    }
    if(targetFolderId&&importedIds.length){try{await api(`/api/collections/${targetFolderId}/models`,jsonOpt('POST',{model_ids:[...new Set(importedIds)]}));}catch(e){toast(`Models imported, but folder filing failed: ${e.message}`,true);}}
    closeModal();
    toast(`${added} added${dupes ? `, ${dupes} duplicate${dupes === 1 ? '' : 's'} reused` : ''}${targetFolderId?' · filed into current folder':''}${failed ? `, ${failed} failed` : ''}`, failed > 0);
    renderPage();
  };
}

function newProjectModal() {
  openModal('New project', `<form id="projectForm" class="fields">${field('name','Project name','','text','wide','e.g. Goblin warband')}
    <div class="field wide"><label>Description</label><textarea name="description" placeholder="What are you building, and what needs to be printed?"></textarea></div>
    ${selectField('status','Status',['Planning','Ready to print','Printing','Complete','On hold'],'Planning')}
    ${field('due_date','Target date','','date')}
    ${field('tags','Tags','','text','wide','','campaign, terrain, gift')}
    </form>`, `<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="createProjectBtn">Create project</button>`, 'Project');
  $('#createProjectBtn').onclick = async () => {
    const d = formDataObject($('#projectForm'));
    d.tags = d.tags.split(',').map(x => x.trim()).filter(Boolean);
    await api('/api/projects', jsonOpt('POST', d));
    toast('Project created'); closeModal(); renderProjects();
  };
}

function projectRatingOptions(kind,value=3) {
  const labels=kind==='urgency'?['Later','Flexible','Normal','Soon','Urgent']:['Optional','Useful','Standard','Important','Critical'];
  return labels.map((label,index)=>`<option value="${index+1}" ${Number(value)===index+1?'selected':''}>${index+1} · ${label}</option>`).join('');
}
function projectPriorityLabel(score=6){return score>=9?'Print next':score>=7?'High priority':score>=5?'Normal priority':'Lower priority';}
function projectLinksFromEditor() {
  return $$('[data-project-model-row]', $('#modalBody')).map(row => ({
    model_id: row.dataset.projectModelRow,
    quantity: Math.max(1, Number($('[data-project-qty]', row)?.value || 1)),
    variant: $('[data-project-variant]', row)?.value.trim() || '',
    urgency: Number($('[data-project-urgency]', row)?.value || 3),
    importance: Number($('[data-project-importance]', row)?.value || 3)
  }));
}

function projectEditorPayload({ includePending = false, excludeModelId = '' } = {}) {
  const form = $('#projectEdit');
  if (!form) throw new Error('Project editor is not available');
  const d = formDataObject(form);
  d.tags = String(d.tags || '').split(',').map(x => x.trim()).filter(Boolean);
  d.models = projectLinksFromEditor().filter(x => x.model_id !== excludeModelId);
  if (includePending) {
    const mid = $('#projectModelValue')?.value || '';
    if (mid && !d.models.some(x => x.model_id === mid)) {
      d.models.push({
        model_id: mid,
        quantity: Math.max(1, Number($('#projectModelQty')?.value || 1)),
        variant: $('#projectModelVariant')?.value.trim() || '',
        urgency: Number($('#projectModelUrgency')?.value || 3),
        importance: Number($('#projectModelImportance')?.value || 3)
      });
    }
  }
  return d;
}

async function saveProjectEditor(id, { includePending = false, excludeModelId = '', closeAfter = false, button = null, success = 'Project saved' } = {}) {
  const original = button?.textContent;
  if (button) { button.disabled = true; button.classList.add('busy'); button.textContent = 'Saving…'; }
  try {
    const updated = await api(`/api/projects/${id}`, jsonOpt('PATCH', projectEditorPayload({ includePending, excludeModelId })));
    toast(success);
    state.projects = await api('/api/projects');
    if (closeAfter) {
      closeModal();
      renderProjects();
    } else {
      await projectModal(updated.id);
    }
    return updated;
  } catch (e) {
    toast(e.message || 'Could not save project', true);
    return null;
  } finally {
    if (button?.isConnected) { button.disabled = false; button.classList.remove('busy'); button.textContent = original; }
  }
}

async function projectModal(id) {
  let p;
  try {
    [p, state.models] = await Promise.all([api(`/api/projects/${id}`), api('/api/models')]);
  } catch (e) {
    toast(e.message || 'Could not open project', true);
    return;
  }
  const available = state.models.filter(m => !p.models.some(pm => pm.id === m.id));
  openModal(p.name, `
    <form id="projectEdit" class="fields" novalidate>
      ${field('name','Name',p.name,'text','wide')}
      <div class="field wide"><label>Description</label><textarea name="description">${esc(p.description)}</textarea></div>
      ${selectField('status','Status',['Planning','Ready to print','Printing','Complete','On hold'],p.status)}
      ${field('due_date','Target date',p.due_date || '','date')}
      ${field('tags','Tags',p.tags?.join(', '),'text','wide')}
    </form>
    <div class="section-head project-models-head"><div><h2>Project models</h2><p>${p.models.length} currently linked · highest combined urgency and importance appears first. Changes are committed by <strong>Save project</strong>.</p></div></div>
    ${p.models.length ? `<div class="list project-model-list">${p.models.map(m => `
      <div class="list-row project-model-row" data-project-model-row="${m.id}">
        <div class="project-model-thumb">${previewable(m)?`<img src="${thumbUrl(m)}" onerror="this.remove()" alt="">`:`<span>${esc(m.extension.slice(1).toUpperCase())}</span>`}</div>
        <div class="grow"><strong>${esc(m.title)}</strong><small>${esc(m.original_filename)}</small></div>
        <div class="project-priority-score score-${Math.min(10,Number(m.urgency||3)+Number(m.importance||3))}"><b>${Number(m.urgency||3)+Number(m.importance||3)}</b><span>/ 10</span><small>${projectPriorityLabel(Number(m.urgency||3)+Number(m.importance||3))}</small></div>
        <div class="field project-qty"><label>Qty</label><input data-project-qty type="number" min="1" step="1" value="${m.quantity}"></div>
        <div class="field project-variant"><label>Variant / role</label><input data-project-variant value="${esc(m.variant || '')}" placeholder="Optional"></div>
        <div class="field project-rating project-urgency"><label>Urgency</label><select data-project-urgency>${projectRatingOptions('urgency',m.urgency)}</select></div>
        <div class="field project-rating project-importance"><label>Importance</label><select data-project-importance>${projectRatingOptions('importance',m.importance)}</select></div>
        <button type="button" class="icon-btn project-remove" data-remove-project-model="${m.id}" title="Remove from project" aria-label="Remove ${esc(m.title)} from project">×</button>
      </div>`).join('')}</div>` : empty('No models linked', 'Choose a library model below. You can click Add model, or simply choose it and press Save project.')}
    <div class="form-section project-add-panel" style="margin-top:13px">
      <div class="form-section-title"><span>Add another model</span><span class="project-save-hint">Saved with the project</span></div>
      ${available.length ? `<div class="fields">
        <div class="field wide"><label>Library model</label>${modelSearchPickerHtml('projectModel',available,'Search models by title, filename or tag…')}</div>
        <div class="field"><label>Quantity</label><input id="projectModelQty" type="number" min="1" step="1" value="1"></div>
        <div class="field"><label>Variant / role</label><input id="projectModelVariant" placeholder="Optional"></div>
        <div class="field"><label>Urgency</label><select id="projectModelUrgency">${projectRatingOptions('urgency',3)}</select></div>
        <div class="field"><label>Importance</label><select id="projectModelImportance">${projectRatingOptions('importance',3)}</select></div>
        <div class="field wide project-add-actions"><button type="button" class="small-btn" id="projectAddBtn">＋ Add model now</button><small>Selecting a model and pressing <b>Save project</b> also links it.</small></div>
      </div>` : `<div class="project-all-linked"><strong>All library models are already linked.</strong><span>Add another model to your library if this project needs more parts.</span></div>`}
    </div>`,
    `<button type="button" class="danger" id="deleteProjectBtn">Delete project</button><button type="button" class="primary" id="saveProjectBtn">Save project</button>`, 'Project details');

  $('#projectEdit').addEventListener('submit', e => { e.preventDefault(); $('#saveProjectBtn').click(); });
  if(available.length)bindModelSearchPicker('projectModel',available);
  $$('[data-project-urgency],[data-project-importance]').forEach(select=>select.onchange=()=>{const row=select.closest('[data-project-model-row]'),score=Number($('[data-project-urgency]',row).value)+Number($('[data-project-importance]',row).value),badge=$('.project-priority-score',row);badge.className=`project-priority-score score-${score}`;$('b',badge).textContent=score;$('small',badge).textContent=projectPriorityLabel(score);});
  $('#saveProjectBtn').onclick = e => saveProjectEditor(id, { includePending: true, closeAfter: true, button: e.currentTarget, success: 'Project and model links saved' });
  $('#deleteProjectBtn').onclick = async () => {
    if (!(await confirmAction('Delete project?', 'The project will be removed. Its models stay safely in your library.'))) return;
    try {
      await api(`/api/projects/${id}`, { method: 'DELETE' });
      toast('Project deleted'); closeModal(); renderProjects();
    } catch (e) { toast(e.message || 'Could not delete project', true); }
  };
  if ($('#projectAddBtn')) $('#projectAddBtn').onclick = async e => {
    e.preventDefault();
    if (!$('#projectModelValue').value) return toast('Choose a model first', true);
    await saveProjectEditor(id, { includePending: true, button: e.currentTarget, success: 'Model linked and project saved' });
  };
  $$('[data-remove-project-model]').forEach(b => b.onclick = async e => {
    e.preventDefault();
    const row = b.closest('[data-project-model-row]');
    const title = $('.grow strong', row)?.textContent || 'this model';
    if (!(await confirmAction('Remove model from project?', `${title} will stay in your library; only the project link is removed.`, 'Remove'))) return;
    await saveProjectEditor(id, { excludeModelId: b.dataset.removeProjectModel, success: 'Model removed from project' });
  });
}

function newMaterialModal() {
  openModal('Add bottle / spool', `<form id="materialForm" class="fields">${field('name','Stock item name','','text','wide','e.g. Elegoo ABS-Like Grey — Bottle 1')}${selectField('kind','Kind',['Filament','Resin'],'Filament')}${field('brand','Brand')}${field('material','Material','PLA')}${field('color','Colour')}${field('color_hex','Colour chip','#808080','color')}${field('density_g_cm3','Density (g/cm³)','','number')}${field('diameter_mm','Filament diameter (mm)','','number')}${field('gtin','GTIN / barcode')}${field('product_url','Product URL','','url')}${field('initial_amount','Starting amount','1000','number')}${selectField('unit','Unit',['g','ml'],'g')}${field('purchase_price','Purchase price (£)','','number')}${field('supplier','Supplier')}${field('batch_lot','Batch / lot')}${field('purchased_at','Purchased date','','date')}${selectField('stock_status','Status',['Sealed','Open','Empty','Archived'],'Open')}${field('location','Storage location')}${field('opened_at','Opened date','','date')}<div class="field wide"><label>Photo <span class="muted">optional</span></label><input id="newMaterialPhoto" type="file" accept="image/jpeg,image/png,image/webp"><small class="field-note">Cached locally and automatically reused for matching stock in future.</small></div><div class="field wide"><label>Notes</label><textarea name="notes" placeholder="Drying, storage, batch or handling notes…"></textarea></div></form>`, `<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="createMaterialBtn">Add stock item</button>`, 'Inventory');
  $('#createMaterialBtn').onclick=async()=>{try{const d=formDataObject($('#materialForm'));for(const k of ['initial_amount','purchase_price','density_g_cm3','diameter_mm'])d[k]=d[k]?Number(d[k]):null;d.remaining_amount=d.initial_amount;let m=await api('/api/materials',jsonOpt('POST',d));const photo=$('#newMaterialPhoto')?.files?.[0];if(photo){const fd=new FormData();fd.append('file',photo);m=await api(`/api/materials/${m.id}/image`,{method:'POST',body:fd});}toast(photo?'Stock item and reusable photo added':'Stock item added');closeModal();renderMaterials();}catch(err){toast(err.message||'Could not add stock item',true)}};
}
async function updateMaterialStock(id){const m=await api(`/api/materials/${id}`);openModal('Adjust stock',`<form id="stockForm" class="fields">${field('amount_delta',`Change (${m.unit})`,'','number','wide','Use a negative number for usage, positive for restock')}${selectField('kind','Reason',['Manual adjustment','Restock','Measured correction','Waste / spill'],'Manual adjustment')}<div class="field wide"><label>Note</label><input name="note" placeholder="Optional reason or measurement note"></div></form><div class="stock-now"><span>Current stock</span><strong>${Number(m.remaining_amount).toFixed(1)} ${esc(m.unit)}</strong></div>`,`<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="saveStock">Apply adjustment</button>`,'Inventory');$('#saveStock').onclick=async()=>{const d=formDataObject($('#stockForm'));await api(`/api/materials/${id}/adjust`,jsonOpt('POST',{...d,amount_delta:Number(d.amount_delta||0)}));toast('Stock adjusted');closeModal();renderMaterials();};}

async function materialQrModal(id){
  const m=await api(`/api/materials/${id}`);
  openModal('Inventory QR label',`<div class="qr-sheet"><img src="/api/materials/${id}/qr" alt="QR code for ${esc(m.inventory_code||m.name)}"><h3>${esc(m.inventory_code||'Inventory item')}</h3><p>${esc(m.name)}</p><small class="muted">Print or save this label and scan it on a device that can reach LayerVault.</small></div>`,`<a class="ghost button-link" href="/api/materials/${id}/qr" download="${esc(m.inventory_code||'layervault-material')}-qr.png">Download PNG</a><button class="primary" data-close-modal>Done</button>`,'Inventory');
}

async function materialModal(id){
  const m=await api(`/api/materials/${id}`);
  const hasPhoto=m.has_custom_image||m.has_source_image||m.source_image_url;
  const media=`<div class="inventory-detail-media material-media ${hasPhoto?'has-image':''}">${hasPhoto?materialImageTag(m,'inventory-photo-img'):`<div class="material-photo-placeholder"><span style="--material-color:${esc(m.color_hex||'#808080')}"></span><strong>No product photo</strong><small>Add a bottle or spool photo; LayerVault will still retain the recorded colour chip.</small></div>`}<div class="material-media-fallback" style="--material-color:${esc(m.color_hex||'#808080')}"></div>${m.has_custom_image?'<span class="custom-photo-pill">Your photo</span>':m.source_image_url?'<span class="source-photo-pill">Official product</span>':''}<span class="detail-colour-chip" title="${esc(m.color||'Recorded colour')}" style="--material-color:${esc(m.color_hex||'#808080')}"></span><div class="media-actions"><input id="materialPhotoInput" type="file" accept="image/jpeg,image/png,image/webp" hidden><button type="button" class="small-btn" id="materialPhotoBtn">${m.has_custom_image?'Replace photo':'Upload your photo'}</button>${m.has_custom_image?'<button type="button" class="small-btn" id="clearMaterialPhotoBtn">Use official / colour</button>':''}</div></div>`;
  openModal(m.name,`<div class="inventory-detail inventory-detail-polished"><div class="inventory-detail-top">${media}<div class="inventory-detail-summary">${sourceCard(m)}<div class="material-source-row"><span class="inventory-code">${esc(m.inventory_code)}</span>${sourceBadge(m.source_provider)}</div><h3>${esc([m.brand,m.material,m.color].filter(Boolean).join(' · '))}</h3><p class="inventory-balance"><strong>${Number(m.remaining_amount).toFixed(1)} ${esc(m.unit)}</strong><span>${m.remaining_percent??0}% remaining</span><span>${m.remaining_value!=null?money(m.remaining_value):'Cost not set'}</span></p><small class="muted">${esc([m.density_g_cm3&&`ρ ${m.density_g_cm3} g/cm³`,m.diameter_mm&&`${m.diameter_mm} mm`,m.gtin&&`GTIN ${m.gtin}`,m.batch_lot&&`Batch ${m.batch_lot}`,m.supplier,m.location].filter(Boolean).join(' · '))}</small>${m.product_url?`<a class="inline-source-link" href="${esc(m.product_url)}" target="_blank" rel="noopener">Product page ↗</a>`:''}</div></div>${materialSpecsHtml(m.specs,12)}<div class="inventory-insight-strip"><div><small>Attempts</small><strong>${m.print_attempts||0}</strong></div><div><small>Success</small><strong>${m.success_rate!=null?`${m.success_rate}%`:'—'}</strong></div><div><small>Avg rating</small><strong>${m.avg_rating?`${m.avg_rating} ★`:'—'}</strong></div></div><div class="stock-ledger"><div class="section-head compact"><div><h3>Stock ledger</h3><p>Automatic print deductions and manual corrections.</p></div></div>${m.transactions?.length?m.transactions.slice(0,12).map(t=>`<div class="ledger-row"><span><b>${esc(t.kind)}</b><small>${esc(t.note||fmtDate(t.created_at))}</small></span><strong class="${Number(t.amount_delta)<0?'negative':'positive'}">${Number(t.amount_delta)>0?'+':''}${Number(t.amount_delta).toFixed(1)} ${esc(m.unit)}</strong><em>${Number(t.balance_after).toFixed(1)} left</em></div>`).join(''):'<p class="muted">No stock movements yet.</p>'}</div></div>`,`<button class="ghost" id="editMaterialBtn">Edit details</button><button class="ghost" data-material-qr="${m.id}">QR label</button><button class="ghost" data-use-material="${m.id}">Adjust stock</button><button class="primary" data-close-modal>Done</button>`,'Physical stock');
  $('#editMaterialBtn').onclick=()=>editMaterialModal(id);
  $('#materialPhotoBtn').onclick=()=>$('#materialPhotoInput').click();
  $('#materialPhotoInput').onchange=async e=>{const f=e.target.files?.[0];if(!f)return;const fd=new FormData();fd.append('file',f);try{await api(`/api/materials/${id}/image`,{method:'POST',body:fd});toast('Material photo cached and linked');await renderMaterials();materialModal(id);}catch(err){toast(err.message||'Could not save photo',true)}};
  $('#clearMaterialPhotoBtn')?.addEventListener('click',async()=>{await api(`/api/materials/${id}/image`,{method:'DELETE'});toast('Custom photo cleared from this item');await renderMaterials();materialModal(id);});
}

async function editMaterialModal(id) {
  const m=await api(`/api/materials/${id}`);
  const preview=(m.has_custom_image||m.has_source_image||m.source_image_url)?`<img src="/api/materials/${encodeURIComponent(id)}/image?v=${encodeURIComponent(m.custom_image_asset_id||m.source_imported_at||'source')}" alt="Current material photo">`:`<span style="--material-color:${esc(m.color_hex||'#808080')}"></span>`;
  openModal('Edit stock item',`${sourceCard(m)}<form id="materialEdit" class="fields"><div class="field wide material-photo-editor"><label>Material photo</label><div><figure>${preview}<i style="--material-color:${esc(m.color_hex||'#808080')}"></i></figure><label class="small-btn photo-picker">${m.has_custom_image?'Choose replacement photo':'Upload your own photo'}<input id="editMaterialPhoto" type="file" accept="image/jpeg,image/png,image/webp" hidden></label><small>Your uploaded bottle or spool photo overrides catalogue artwork. The colour chip remains separate.</small></div></div>${field('name','Stock item name',m.name,'text','wide')}${selectField('kind','Kind',['Filament','Resin'],m.kind)}${field('brand','Brand',m.brand)}${field('material','Material',m.material)}${field('color','Colour',m.color)}${field('color_hex','Colour chip',m.color_hex||'#808080','color')}${field('density_g_cm3','Density (g/cm³)',m.density_g_cm3??'','number')}${field('diameter_mm','Filament diameter (mm)',m.diameter_mm??'','number')}${field('gtin','GTIN / barcode',m.gtin||'')}${field('product_url','Product URL',m.product_url||'','url')}${field('initial_amount','Nominal / starting amount',m.initial_amount??'','number')}${selectField('unit','Unit',['g','ml'],m.unit)}${field('purchase_price','Purchase price (£)',m.purchase_price??'','number')}${field('supplier','Supplier',m.supplier)}${field('batch_lot','Batch / lot',m.batch_lot)}${field('purchased_at','Purchased date',m.purchased_at||'','date')}${selectField('stock_status','Status',['Sealed','Open','Empty','Archived'],m.stock_status)}${field('location','Storage location',m.location)}${field('opened_at','Opened date',m.opened_at||'','date')}<div class="field wide"><label>Notes</label><textarea name="notes">${esc(m.notes||'')}</textarea></div></form>`,`<button class="ghost" id="backMaterialBtn">Back</button><button class="primary" id="saveMaterialDetailsBtn">Save details</button>`,'Physical stock');
  $('#backMaterialBtn').onclick=()=>materialModal(id);
  $('#editMaterialPhoto').onchange=e=>{const f=e.target.files?.[0];if(!f)return;const img=$('.material-photo-editor figure img');if(img)img.src=URL.createObjectURL(f);else $('.material-photo-editor figure').insertAdjacentHTML('afterbegin',`<img src="${URL.createObjectURL(f)}" alt="Selected replacement photo">`);$('.photo-picker').childNodes[0].textContent='Replacement selected ';};
  $('#saveMaterialDetailsBtn').onclick=async()=>{try{const d=formDataObject($('#materialEdit'));for(const k of ['initial_amount','purchase_price','density_g_cm3','diameter_mm'])d[k]=d[k]?Number(d[k]):null;await api(`/api/materials/${id}`,jsonOpt('PATCH',d));const photo=$('#editMaterialPhoto').files?.[0];if(photo){const fd=new FormData();fd.append('file',photo);await api(`/api/materials/${id}/image`,{method:'POST',body:fd});}toast(photo?'Material details and photo updated':'Material details updated');await renderMaterials();materialModal(id);}catch(err){toast(err.message,true)}};
}

function catalogPrinterOptions(current='') {
  return `<option value="">No printer / generic guidance</option>${state.printers.map(p=>`<option value="${p.id}" ${p.id===current?'selected':''}>${esc(p.name)} · ${esc(techFamily(p.technology))}</option>`).join('')}`;
}

async function materialCatalogModal(initialQuery='') {
  try { state.printers=await api('/api/printers'); } catch {}
  openModal('Search material catalogue',`<div class="catalog-shell"><div class="catalog-guidance"><div><span class="kicker">Material discovery</span><strong>Find major resin brands as well as open material data</strong><p>The official resin index works without a printer and links back to each manufacturer. Choose a resin printer only when you want Open Resin Alliance exposure profiles too.</p></div><div class="catalog-source-chips">${sourceBadge('manufacturer_resin')}${sourceBadge('spoolman')}${sourceBadge('openresin')}</div></div><form id="catalogSearchForm" class="catalog-toolbar"><div class="field catalog-query"><label>Search</label><input id="catalogQuery" value="${esc(initialQuery)}" placeholder="e.g. Anycubic, Siraya Fast, Phrozen Aqua, eSUN PETG" autocomplete="off"></div><div class="field"><label>Source</label><select id="catalogProvider"><option value="all">All sources</option><option value="manufacturer_resin">Official Resin Catalogues</option><option value="spoolman">SpoolmanDB</option><option value="openresin">Open Resin Alliance profiles</option></select></div><div class="field"><label>Printer</label><select id="catalogPrinter">${catalogPrinterOptions()}</select></div><button class="primary catalog-search-btn" id="catalogSearchBtn" type="submit">Search</button></form><div id="catalogWarnings"></div><div id="catalogResults" class="catalog-results">${empty('Search materials and resin brands','Try Anycubic, ELEGOO, Phrozen, Siraya Tech, SUNLU, eSUN, Formlabs or a resin family such as tough or water-washable.')}</div></div>`,`<button class="ghost" data-close-modal>Close</button><button class="primary" id="manualFromCatalog">Add manually instead</button>`,'Material sources');
  $('#manualFromCatalog').onclick=()=>newMaterialModal();
  const run=async()=>{const q=$('#catalogQuery').value.trim();if(q.length<2)return toast('Enter at least two characters',true);const btn=$('#catalogSearchBtn');btn.disabled=true;btn.textContent='Searching…';$('#catalogResults').innerHTML='<div class="catalog-loading"><span></span><strong>Searching sources…</strong></div>';try{const params=new URLSearchParams({q,provider:$('#catalogProvider').value,printer_id:$('#catalogPrinter').value,limit:'48'});const data=await api(`/api/catalog/search?${params}`);$('#catalogWarnings').innerHTML=(data.warnings||[]).map(w=>`<div class="catalog-warning">${esc(w)}</div>`).join('');$('#catalogResults').innerHTML=data.results?.length?data.results.map(r=>`<button type="button" class="catalog-result" data-catalog-provider="${esc(r.provider)}" data-catalog-key="${esc(r.key)}">${catalogMaterialImage(r)}<span class="grow"><span class="catalog-result-top">${sourceBadge(r.provider)}${r.has_profile?'<span class="recommended-pill">Recommended settings</span>':''}${r.has_image?'<span class="official-art-pill">Official artwork</span>':''}</span><strong>${esc([r.brand,r.name].filter(Boolean).join(' · '))}</strong><small>${esc([r.material,r.color,r.summary].filter(Boolean).join(' · '))}</small></span><span class="catalog-chevron">›</span></button>`).join(''):empty('No matching materials','Try a broader product, brand or material name.');$$('[data-catalog-provider]').forEach(b=>b.onclick=()=>catalogItemModal(b.dataset.catalogProvider,b.dataset.catalogKey,$('#catalogPrinter').value,q));}catch(err){ $('#catalogWarnings').innerHTML=`<div class="catalog-warning bad">${esc(err.message)}</div>`;$('#catalogResults').innerHTML=empty('Catalogue unavailable','Manual material entry still works, and LayerVault will use cached source data when available.');}finally{btn.disabled=false;btn.textContent='Search';}};
  $('#catalogSearchForm').onsubmit=e=>{e.preventDefault();run()};
  $('#catalogProvider').onchange=()=>{if($('#catalogProvider').value==='openresin'&&!$('#catalogPrinter').value) toast('Choose one of your resin printers for Open Resin Alliance profiles.');};
  if(initialQuery)run();
}

async function catalogItemModal(provider,key,printerId='',backQuery='') {
  let item;
  try{const q=new URLSearchParams({provider,key,printer_id:printerId});item=await api(`/api/catalog/item?${q}`);}catch(err){toast(err.message,true);return;}
  const settings=item.settings||{}; const recs=Object.keys(settings).length?`<div class="catalog-settings"><div class="section-head compact"><div><h3>Recommended starting settings</h3><p>Source guidance, not a calibration result.</p></div><span class="recommended-pill">Recommended</span></div><div class="recipe-mini catalog-recipe">${settingsSummary(settings,item.technology,8)||Object.entries(settings).slice(0,8).map(([k,v])=>`<span><b>${esc(v)}${esc(settingUnit(k,item.technology))}</b>${esc(settingLabel(k,item.technology))}</span>`).join('')}</div></div>`:'';
  const amount=item.package_amount||1000, unit=item.package_unit|| (item.kind==='Resin'?'ml':'g');
  openModal(item.name,`<div class="catalog-detail"><div class="catalog-product-hero">${catalogMaterialImage({...item,provider},'catalog-product-image large')}<div class="grow"><div class="catalog-result-top">${sourceBadge(provider)}<span class="tech-badge">${esc(item.technology)}</span>${item.has_image?'<span class="official-art-pill">Official vendor artwork</span>':''}</div><h3>${esc([item.brand,item.name].filter(Boolean).join(' · '))}</h3><p>${esc([item.material,item.color,item.package_amount?`${item.package_amount}${item.package_unit||''}`:'',item.density?`density ${item.density}`:'',item.diameter_mm?`${item.diameter_mm}mm`:'',item.gtin?`GTIN ${item.gtin}`:''].filter(Boolean).join(' · '))}</p></div>${item.official_product_url?`<a class="small-btn button-link" href="${esc(item.official_product_url)}" target="_blank" rel="noopener">Official product ↗</a>`:item.source_url?`<a class="small-btn button-link" href="${esc(item.source_url)}" target="_blank" rel="noopener">Source ↗</a>`:''}</div>${materialSpecsHtml(item.specs,12)}${recs}${item.source_price!=null?`<div class="source-price-note">Source-listed bottle price: <strong>${esc(item.source_currency||'')}${esc(item.source_price)}</strong>. This is reference metadata and is not converted to GBP automatically.</div>`:''}<div class="catalog-import-panel"><div class="section-head compact"><div><h3>Create your physical stock item</h3><p>Source metadata, official artwork and the separate colour chip are copied into your stock record.</p></div></div><form id="catalogImportForm" class="fields">${field('name','Stock item name',item.material_payload?.name||[item.brand,item.name].filter(Boolean).join(' · '),'text','wide')}${field('initial_amount',`Starting amount (${unit})`,amount,'number')}${field('color','Colour',item.color||'')}${field('purchase_price','Your purchase price (£)','','number')}${field('supplier','Supplier')}${field('batch_lot','Batch / lot')}${field('location','Storage location')}${selectField('stock_status','Status',['Sealed','Open','Empty','Archived'],'Open')}<div class="field wide"><label>Notes</label><textarea name="notes" placeholder="Optional stock or handling notes"></textarea></div>${item.has_profile?`<label class="catalog-profile-choice wide"><input type="checkbox" id="catalogCreateProfile" checked><span><strong>Also save these recommended settings as a profile</strong><small>It remains marked Recommended and linked to ${esc(sourceName(provider))}. Your Print Lab results are still the source of proven settings.</small></span></label>`:''}</form></div></div>`,`<button class="ghost" id="catalogBackBtn">Back to results</button><button class="primary" id="catalogImportBtn">Import to LayerVault</button>`,'Material source');
  $('#catalogBackBtn').onclick=()=>materialCatalogModal(backQuery);
  $('#catalogImportBtn').onclick=async()=>{const btn=$('#catalogImportBtn');btn.disabled=true;btn.textContent='Importing…';try{const d=formDataObject($('#catalogImportForm'));const payload={provider,key,printer_id:printerId,create_profile:!!$('#catalogCreateProfile')?.checked,material_overrides:{...d,initial_amount:Number(d.initial_amount||amount),remaining_amount:Number(d.initial_amount||amount),purchase_price:d.purchase_price?Number(d.purchase_price):null,unit}};const out=await api('/api/catalog/import',jsonOpt('POST',payload));toast(out.profile?'Material and recommended profile imported':'Material imported');closeModal();await renderMaterials();}catch(err){toast(err.message,true);btn.disabled=false;btn.textContent='Import to LayerVault';}};
}

function printerCatalogImage(item, cls='printer-result-image') {
  if (!item?.image_url) return `<div class="${cls} printer-image-fallback"><span>${techFamily(item?.technology)==='Resin'?'◫':'⌂'}</span><small>${esc(techFamily(item?.technology||''))}</small></div>`;
  const q=new URLSearchParams({provider:item.provider_id,key:item.key});
  return `<div class="${cls}"><img src="/api/printer-catalog/image?${q}" alt="${esc(item.model||item.name||'Printer')}" loading="lazy" decoding="async" onerror="this.parentElement.classList.add('image-failed');this.remove()"><div class="printer-image-fallback"><span>${techFamily(item.technology)==='Resin'?'◫':'⌂'}</span><small>${esc(techFamily(item.technology))}</small></div></div>`;
}
async function printerCatalogModal(initialQuery='') {
  const providers=await api('/api/printer-catalog/providers');
  openModal('Search printer catalogue',`<div class="printer-catalog-shell"><div class="catalog-guidance"><div><span class="kicker">Open hardware sources</span><strong>Find your exact printer, then add your physical machine.</strong><p>LayerVault imports source specifications such as build volume, nozzle options and resin display resolution. Source values remain attributed and editable.</p></div><div class="catalog-source-chips">${providers.map(p=>sourceBadge(p.id,p.name)).join('')}</div></div><div class="catalog-toolbar printer-catalog-toolbar"><div class="field catalog-query"><label>Printer</label><input id="printerCatalogQuery" value="${esc(initialQuery)}" placeholder="Saturn 4 Ultra, Bambu P1S, Ender 3…"></div>${selectField('provider','Source',[{value:'all',label:'All open sources'},...providers.map(p=>({value:p.id,label:p.name}))],'all')}${selectField('technology','Technology',['All','FDM','Resin'],'All')}<button class="primary catalog-search-btn" id="printerCatalogSearch">Search</button></div><div id="printerCatalogStatus" class="catalog-warning hidden"></div><div id="printerCatalogResults" class="printer-catalog-results">${empty('Search the open printer catalogue','Use a manufacturer/model name. Imported specifications can always be edited afterwards.')}</div></div>`,`<button class="ghost" data-close-modal>Close</button><button class="ghost" id="printerManualInstead">Add manually instead</button>`,'Hardware sources');
  const run=async()=>{const q=$('#printerCatalogQuery').value.trim();if(q.length<2){toast('Enter at least two characters',true);return;}const provider=$('[name="provider"]',$('#modalBody')).value;const technology=$('[name="technology"]',$('#modalBody')).value.toLowerCase();const box=$('#printerCatalogResults'), status=$('#printerCatalogStatus');box.innerHTML='<div class="catalog-loading">Searching open printer sources…</div>';try{const res=await api(`/api/printer-catalog/search?${new URLSearchParams({q,provider,technology,limit:'30'})}`);status.classList.toggle('hidden',!(res.warnings||[]).length);status.textContent=(res.warnings||[]).join(' · ');box.innerHTML=res.results?.length?res.results.map(r=>`<button class="printer-result" data-printer-source="${esc(r.provider_id)}" data-printer-key="${esc(r.key)}">${printerCatalogImage(r)}<div class="grow"><div class="catalog-result-top">${sourceBadge(r.provider_id)}<span class="tech-badge">${esc(techFamily(r.technology))}</span>${r.merged_source_count>1?`<span class="merged-source-pill">Merged ${r.merged_source_count} sources</span>`:''}</div><strong>${esc([r.manufacturer,r.model].filter(Boolean).join(' · ')||r.name)}</strong><small>${printerSpecs(r).map(esc).join(' · ')||'Open source machine profile'}</small></div><span class="catalog-chevron">›</span></button>`).join(''):empty('No matching printers','Try a shorter model name or another source. Manual entry is always available.');$$('[data-printer-source]',box).forEach(b=>b.onclick=()=>printerCatalogItemModal(b.dataset.printerSource,b.dataset.printerKey,q));}catch(e){box.innerHTML=empty('Catalogue unavailable',e.message);}};
  $('#printerCatalogSearch').onclick=run;$('#printerCatalogQuery').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();run();}};$('#printerManualInstead').onclick=()=>newPrinterModal();if(initialQuery)run();
}
async function printerCatalogItemModal(provider,key,backQuery='') {
  const item=await api(`/api/printer-catalog/item?${new URLSearchParams({provider,key})}`);const specs=printerSpecs(item);const resin=techFamily(item.technology)==='Resin';
  openModal(item.model||item.name,`<div class="printer-source-detail"><div class="printer-source-hero">${printerCatalogImage(item,'printer-source-image')}<div class="grow"><div class="catalog-result-top">${sourceBadge(provider)}<span class="tech-badge">${esc(techFamily(item.technology))}</span></div><h3>${esc([item.manufacturer,item.model].filter(Boolean).join(' · '))}</h3><p>Open-source machine specification. Review the values below, then add your physical printer to inventory.</p>${item.source_url?`<a class="small-btn button-link" href="${esc(item.source_url)}" target="_blank" rel="noopener">View source ↗</a>`:''}</div></div><div class="printer-source-specs">${item.build_x&&item.build_y&&item.build_z?`<div><small>Build volume</small><strong>${esc(`${item.build_x} × ${item.build_y} × ${item.build_z} mm`)}</strong></div>`:''}${resin&&item.resolution_x&&item.resolution_y?`<div><small>Display resolution</small><strong>${esc(`${item.resolution_x} × ${item.resolution_y} px`)}</strong></div>`:''}${resin&&(item.xy_resolution_x_um||item.xy_resolution_y_um)?`<div><small>Calculated XY resolution</small><strong>${esc(`${Number(item.xy_resolution_x_um||item.xy_resolution_y_um).toFixed(1)}${item.xy_resolution_y_um&&item.xy_resolution_x_um!==item.xy_resolution_y_um?` × ${Number(item.xy_resolution_y_um).toFixed(1)}`:''} μm`)}</strong></div>`:''}${!resin&&item.nozzle_options?.length?`<div><small>Nozzle options</small><strong>${esc(item.nozzle_options.map(x=>`${x} mm`).join(' · '))}</strong></div>`:''}${specs.length===0?`<div><small>Profile</small><strong>Machine identity available</strong></div>`:''}</div><div class="printer-source-note"><strong>Starting hardware data, not a guarantee.</strong><span>Manufacturers revise machines and community profiles can lag behind. Verify the exact hardware revision if a dimension or resolution is critical. Your imported copy stays editable.</span></div><form id="printerCatalogImportForm" class="fields">${field('name','Your printer name',item.model||item.name,'text','wide')}${field('serial_number','Serial number')}${field('location','Location')}${field('purchased_at','Purchased date','','date')}${field('purchase_price','Purchase price (£)','','number')}${selectField('printer_status','Status',['Active','Maintenance','Offline','Retired'],'Active')}${field('firmware_version','Firmware')}<div class="field wide"><label>Notes</label><textarea name="notes" placeholder="Nozzle upgrades, screen replacement, enclosure notes…"></textarea></div></form><div class="source-card"><div><span class="kicker">Source provenance</span><strong>${esc(sourceName(provider))}</strong><small>${esc(item.source_license||'Upstream licence not specified')} · source snapshot is retained with your local printer record.</small></div></div></div>`,`<button class="ghost" id="printerCatalogBack">Back to results</button><button class="primary" id="printerCatalogImport">Add to my printers</button>`,'Hardware source');
  $('#printerCatalogBack').onclick=()=>printerCatalogModal(backQuery);$('#printerCatalogImport').onclick=async()=>{const overrides=formDataObject($('#printerCatalogImportForm'));overrides.purchase_price=overrides.purchase_price?Number(overrides.purchase_price):null;const r=await api('/api/printer-catalog/import',jsonOpt('POST',{provider,key,overrides}));toast(`${r.printer.name} added to printer inventory`);closeModal();renderPrinters();};
}
function printerManualFields(p={}) { return `${field('name','Display name',p.name||'','text','wide','e.g. Saturn 4 Ultra')}${selectField('technology','Technology',['FDM','MSLA / Resin','SLA','DLP'],p.technology||'FDM')}${field('manufacturer','Manufacturer',p.manufacturer||'')}${field('model','Model',p.model||'')}${field('serial_number','Serial number',p.serial_number||'')}${field('location','Location',p.location||'')}${field('purchased_at','Purchased date',p.purchased_at||'','date')}${field('purchase_price','Purchase price (£)',p.purchase_price??'','number')}${selectField('printer_status','Status',['Active','Maintenance','Offline','Retired'],p.printer_status||'Active')}${field('firmware_version','Firmware',p.firmware_version||'')}${field('last_service_at','Last serviced',p.last_service_at||'','date')}${field('build_x','Build X (mm)',p.build_x??'','number')}${field('build_y','Build Y (mm)',p.build_y??'','number')}${field('build_z','Build Z (mm)',p.build_z??'','number')}${field('nozzle_mm','Primary nozzle (mm)',p.nozzle_mm??'','number')}${field('resolution_x','Resin display X (px)',p.resolution_x??'','number')}${field('resolution_y','Resin display Y (px)',p.resolution_y??'','number')}${field('xy_resolution_x_um','XY resolution X (μm)',p.xy_resolution_x_um??'','number')}${field('xy_resolution_y_um','XY resolution Y (μm)',p.xy_resolution_y_um??'','number')}<div class="field wide"><label>Notes</label><textarea name="notes">${esc(p.notes||'')}</textarea></div>`; }
function normalisePrinterForm(form){const d=formDataObject(form);for(const k of ['build_x','build_y','build_z','nozzle_mm','purchase_price','resolution_x','resolution_y','xy_resolution_x_um','xy_resolution_y_um'])d[k]=d[k]?Number(d[k]):null;return d;}
function newPrinterModal(){
  openModal('Add printer',`<div class="source-strip compact"><span>TIP</span>${sourceBadge('orca')}${sourceBadge('dragonfruit')}${sourceBadge('uvtools')}<small>Matching FDM and resin printer artwork is applied automatically. Searching the catalogue can also fill build volume and resolution.</small></div><form id="printerForm" class="fields">${printerManualFields()}<div class="field wide"><label>Photo <span class="muted">optional</span></label><input id="newPrinterPhoto" type="file" accept="image/jpeg,image/png,image/webp"><small class="field-note">A custom local photo always takes priority over bundled catalogue artwork.</small></div></form>`,`<button class="ghost" id="searchPrinterInstead">Search catalogue</button><button class="primary" id="createPrinterBtn">Add printer</button>`,'Hardware inventory');
  $('#searchPrinterInstead').onclick=()=>printerCatalogModal();
  $('#createPrinterBtn').onclick=async()=>{try{let p=await api('/api/printers',jsonOpt('POST',normalisePrinterForm($('#printerForm'))));const photo=$('#newPrinterPhoto')?.files?.[0];if(photo){const fd=new FormData();fd.append('file',photo);p=await api(`/api/printers/${p.id}/image`,{method:'POST',body:fd});}toast(photo?'Printer and reusable photo added':'Printer added to inventory');closeModal();renderPrinters();}catch(err){toast(err.message||'Could not add printer',true)}};
}

async function printerModal(id){
  const p=await api(`/api/printers/${id}`);
  const source=p.source_provider?`<div class="source-card wide"><div><span class="kicker">Imported hardware data</span><strong>${esc(sourceName(p.source_provider))}</strong><small>Imported ${fmtDate(p.source_imported_at)} · local edits do not erase the source snapshot.</small></div>${p.source_url?`<a class="small-btn button-link" href="${esc(p.source_url)}" target="_blank" rel="noopener">View source ↗</a>`:''}</div>`:'';
  const media=`<div class="printer-detail-media printer-media ${p.has_custom_image||p.source_image_url?'has-image':''}">${printerImageTag(p,'printer-detail-photo')}<div class="printer-media-fallback"><span>${techFamily(p.technology)==='Resin'?'◫':'⌂'}</span><small>${esc(p.manufacturer||techFamily(p.technology))}</small></div>${p.has_custom_image?'<span class="custom-photo-pill">Your photo</span>':''}<div class="media-actions"><input id="printerPhotoInput" type="file" accept="image/jpeg,image/png,image/webp" hidden><button type="button" class="small-btn" id="printerPhotoBtn">${p.has_custom_image?'Replace photo':'Upload photo'}</button>${p.has_custom_image?'<button type="button" class="small-btn" id="clearPrinterPhotoBtn">Use source / fallback</button>':''}</div></div>`;
  const capabilitySummary=`<div class="hardware-capability-strip"><div><small>Technology</small><strong>${esc(techFamily(p.technology))}</strong></div><div><small>Build volume</small><strong>${p.build_x&&p.build_y&&p.build_z?`${p.build_x} × ${p.build_y} × ${p.build_z} mm`:'Not set'}</strong></div><div><small>${techFamily(p.technology)==='Resin'?'Resolution':'Nozzle'}</small><strong>${techFamily(p.technology)==='Resin'?(p.resolution_x&&p.resolution_y?`${p.resolution_x} × ${p.resolution_y} px`:'Not set'):(p.nozzle_mm?`${p.nozzle_mm} mm`:'Not set')}</strong></div></div>`;
  openModal(p.name,`<div class="printer-detail-polished"><div class="printer-detail-hero">${media}<div class="printer-detail-summary"><div class="material-source-row"><span class="inventory-code">${esc(p.inventory_code||'')}</span>${sourceBadge(p.source_provider)}</div><h3>${esc(p.name)}</h3><p>${esc([p.manufacturer,p.model].filter(Boolean).join(' · ')||'Hardware details')}</p>${capabilitySummary}${source}</div></div><div class="inventory-insight-strip"><div><small>Attempts</small><strong>${p.print_attempts||0}</strong></div><div><small>Success</small><strong>${p.success_rate!=null?`${p.success_rate}%`:'—'}</strong></div><div><small>Runtime</small><strong>${p.print_hours||0}h</strong></div></div><div class="hardware-edit-card"><div class="section-head compact"><div><h3>Printer details</h3><p>Ownership, hardware and maintenance information.</p></div></div><form id="printerEdit" class="fields hardware-fields">${printerManualFields(p)}</form></div></div>`,`<button class="danger" id="deletePrinterBtn">Delete</button><button class="primary" id="savePrinterBtn">Save printer</button>`,'Hardware inventory');
  $('#printerPhotoBtn').onclick=()=>$('#printerPhotoInput').click();
  $('#printerPhotoInput').onchange=async e=>{const f=e.target.files?.[0];if(!f)return;const fd=new FormData();fd.append('file',f);try{await api(`/api/printers/${id}/image`,{method:'POST',body:fd});toast('Printer photo cached and linked');await renderPrinters();printerModal(id);}catch(err){toast(err.message||'Could not save printer photo',true)}};
  $('#clearPrinterPhotoBtn')?.addEventListener('click',async()=>{await api(`/api/printers/${id}/image`,{method:'DELETE'});toast(p.source_image_url?'Using catalogue image again':'Custom photo cleared');await renderPrinters();printerModal(id);});
  $('#savePrinterBtn').onclick=async()=>{await api(`/api/printers/${id}`,jsonOpt('PATCH',normalisePrinterForm($('#printerEdit'))));toast('Printer updated');closeModal();renderPrinters();};
  $('#deletePrinterBtn').onclick=async()=>{if(!(await confirmAction('Delete printer?',`Remove “${p.name}” from your printer inventory? Existing print records will keep their historical data.`)))return;await api(`/api/printers/${id}`,{method:'DELETE'});closeModal();renderPrinters();};
}

function profileFormHtml(p={}){const tech=p.technology||'FDM';const source=p.source_provider?`<div class="source-card wide"><div><span class="kicker">${esc(p.profile_origin||'Recommended')} profile</span><strong>${esc(sourceName(p.source_provider))}</strong><small>Imported source guidance. Editing this local copy does not change the upstream catalogue.</small></div>${p.source_url?`<a class="small-btn button-link" href="${esc(p.source_url)}" target="_blank" rel="noopener">View source ↗</a>`:''}</div>`:'';return `<form id="profileForm" class="fields" data-technology="${esc(tech)}">${source}${field('name','Profile name',p.name||'','text','wide','e.g. 0.03 mm miniatures')}${selectField('technology','Technology',['FDM','MSLA / Resin'],tech)}${selectField('printer_id','Printer',[{value:'',label:'Any printer'},...state.printers.map(x=>({value:x.id,label:x.name}))],p.printer_id||'')}${field('material','Material',p.material||'')}${field('layer_height','Layer height (mm)',p.layer_height??'','number')}<div class="field wide" id="profileSettingsWrap">${settingsEditor(tech,p.settings||{})}</div><div class="field wide"><label>Profile notes</label><textarea name="notes">${esc(p.notes||'')}</textarea></div></form>`;}
function wireTechnologyEditor(form,values={}){const select=form.querySelector('[name=technology]');select?.addEventListener('change',()=>{$('#profileSettingsWrap').innerHTML=settingsEditor(select.value,collectSettings(form))});}
async function newProfileModal(){state.printers=await api('/api/printers');openModal('New print profile',profileFormHtml(),`<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="createProfileBtn">Save profile</button>`,'Recipe library');const form=$('#profileForm');wireTechnologyEditor(form,{});$('#createProfileBtn').onclick=async()=>{const d=formDataObject(form);d.layer_height=d.layer_height?Number(d.layer_height):null;d.settings=collectSettings(form);await api('/api/profiles',jsonOpt('POST',d));toast('Structured profile saved');closeModal();renderPrinters();};}
async function profileModal(id){await refreshCore();const p=state.profiles.find(x=>x.id===id);if(!p)return;openModal(p.name,profileFormHtml(p),`<button class="danger" id="deleteProfileBtn">Delete</button><button class="primary" id="saveProfileBtn">Save profile</button>`,'Recipe library');const form=$('#profileForm');wireTechnologyEditor(form,p.settings||{});$('#saveProfileBtn').onclick=async()=>{const d=formDataObject(form);d.layer_height=d.layer_height?Number(d.layer_height):null;d.settings=collectSettings(form);await api(`/api/profiles/${id}`,jsonOpt('PATCH',d));toast('Profile updated');closeModal();renderPrinters();};$('#deleteProfileBtn').onclick=async()=>{if(!(await confirmAction('Delete print profile?','Historical jobs keep their settings snapshots.')))return;await api(`/api/profiles/${id}`,{method:'DELETE'});closeModal();renderPrinters();};}

function selectedJobTechnology(form){const pid=form.querySelector('[name=printer_id]')?.value,profileId=form.querySelector('[name=profile_id]')?.value;return state.printers.find(p=>p.id===pid)?.technology||state.profiles.find(p=>p.id===profileId)?.technology||form.dataset.technology||'FDM';}
function wireJobRecipeForm(form,initialSettings={}){const render=()=>{$('#jobSettingsWrap').innerHTML=settingsEditor(selectedJobTechnology(form),collectSettings(form));};form.querySelector('[name=printer_id]')?.addEventListener('change',render);form.querySelector('[name=profile_id]')?.addEventListener('change',e=>{const p=state.profiles.find(x=>x.id===e.target.value);$('#jobSettingsWrap').innerHTML=settingsEditor(p?.technology||selectedJobTechnology(form),p?.settings||collectSettings(form));});if(form.id==='jobEdit'){const legacySelect=form.querySelector('[name=model_id]'),legacy=legacySelect?.closest('.field');if(legacy){const match=state.jobs.find(item=>item.name===form.querySelector('[name=name]')?.value&&item.model_id===(legacySelect.value||null)&&item.printer_id===(form.querySelector('[name=printer_id]')?.value||null));const initial=match?.models?.length?match.models:(legacySelect.value?[{model_id:legacySelect.value,quantity:1}]:[]);legacy.outerHTML=jobModelPickerHtml();form._jobModelPicker=bindJobModelPicker(state.models,initial);}}}
async function newJobModal(){return newJobFromFileModal();}

function toolpathImportSummary(metadata={}) {
  const facts=[];
  if(metadata.technology)facts.push(`<span><b>${esc(techFamily(metadata.technology))}</b>print technology</span>`);
  if(metadata.material_volume_ml!=null)facts.push(`<span><b>${Number(metadata.material_volume_ml).toFixed(2)} ml</b>${metadata.volume_estimated?'estimated ':''}material volume</span>`);
  if(metadata.material_weight_g!=null)facts.push(`<span><b>${Number(metadata.material_weight_g).toFixed(2)} g</b>material weight</span>`);
  if(metadata.filament_length_mm!=null)facts.push(`<span><b>${(Number(metadata.filament_length_mm)/1000).toFixed(2)} m</b>filament length</span>`);
  if(metadata.duration_minutes!=null)facts.push(`<span><b>${Math.floor(metadata.duration_minutes/60)}h ${metadata.duration_minutes%60}m</b>estimated duration</span>`);
  const setup=[metadata.suggested_printer_name&&`Printer: ${metadata.suggested_printer_name}`,metadata.suggested_material_name&&`Stock: ${metadata.suggested_material_name}`,metadata.suggested_profile_name&&`Profile: ${metadata.suggested_profile_name}`].filter(Boolean).join(' · ');
  return `<div class="toolpath-import-result"><div class="toolpath-file-mark">${esc(String(metadata.extension||'').replace('.','').toUpperCase()||'FILE')}</div><div class="grow"><strong>${esc(metadata.original_name||'Print file')}</strong><small>${esc(metadata.slicer||'Slicer metadata')} · ${fmtBytes(metadata.size_bytes||0)} · ${Object.keys(metadata.settings||{}).length} parameter${Object.keys(metadata.settings||{}).length===1?'':'s'} found</small><div class="toolpath-facts">${facts.join('')||'<span><b>File attached</b>No recognised estimates were embedded</span>'}</div>${setup?`<p class="toolpath-auto-setup">Automatically selected · ${esc(setup)}</p>`:''}${metadata.warnings?.length?`<p>${metadata.warnings.map(esc).join(' ')}</p>`:''}</div><span class="toolpath-ready">✓ Read</span></div>`;
}
function applyToolpathMaterialAmount(form,metadata={}) {
  const material=state.materials.find(item=>item.id===form.querySelector('[name=material_id]')?.value),volume=metadata.material_volume_ml==null?NaN:Number(metadata.material_volume_ml),weight=metadata.material_weight_g==null?NaN:Number(metadata.material_weight_g),density=material?.density_g_cm3==null?NaN:Number(material.density_g_cm3);
  let amount=null;
  if(material?.unit==='ml'&&Number.isFinite(volume))amount=volume;
  else if(material?.unit==='g'&&Number.isFinite(weight))amount=weight;
  else if(material?.unit==='g'&&Number.isFinite(volume)&&Number.isFinite(density)&&density>0)amount=volume*density;
  else if(Number.isFinite(weight))amount=weight;
  else if(Number.isFinite(volume))amount=volume;
  const input=form.querySelector('[name=material_used]');if(input&&amount!=null)input.value=Number(amount.toFixed(3));
  const hint=$('#jobMaterialUsedHint');if(hint)hint.textContent=material?`Recorded against ${material.inventory_code} in ${material.unit}.`:(amount!=null?`Detected ${Number(amount.toFixed(3))}${Number.isFinite(weight)?'g':'ml'}; choose stock to record the inventory unit.`:'Choose a stock item so LayerVault can apply its g/ml unit.');
}
function applyToolpathSetup(form,metadata={}) {
  const technology=techFamily(metadata.technology||'FDM');form.dataset.technology=technology;
  const assignments=[['printer_id',metadata.suggested_printer_id],['material_id',metadata.suggested_material_id],['profile_id',metadata.suggested_profile_id]];
  for(const [name,value] of assignments){const select=form.querySelector(`[name=${name}]`);if(select&&value&&[...select.options].some(option=>option.value===value))select.value=value;}
  $('#jobSettingsWrap').innerHTML=settingsEditor(technology,{...collectSettings(form),...(metadata.settings||{})});
  applyToolpathMaterialAmount(form,metadata);
}
async function newJobFromFileModal(){
  await refreshCore();let toolpath=null;
  openModal('New print job',`<form id="jobForm" class="fields">
    <div class="field wide toolpath-import-card"><div class="toolpath-import-head"><div><span class="kicker">Optional automatic setup</span><strong>Read a sliced print file</strong><small>G-code, BGCODE, 3MF and PM3 files can supply material usage, duration and print parameters.</small></div><input id="jobToolpathInput" type="file" accept=".gcode,.bgcode,.3mf,.pm3" hidden><button type="button" class="small-btn" id="chooseJobToolpath">Choose print file</button></div><div id="jobToolpathState" class="toolpath-import-empty"><span>⌁</span><div><strong>No print file selected</strong><small>You can still enter every value manually below.</small></div></div><input type="hidden" name="toolpath_token" id="jobToolpathToken"></div>
    ${field('name','Job name','','text','wide','e.g. Goblin archers × 6')}
    ${selectField('project_id','Project',[{value:'',label:'No project'},...state.projects.map(p=>({value:p.id,label:p.name}))],'')}
    ${jobModelPickerHtml()}
    ${selectField('printer_id','Physical printer',[{value:'',label:'No printer'},...state.printers.map(p=>({value:p.id,label:`${p.inventory_code} · ${p.name}`}))],'')}
    ${selectField('material_id','Bottle / spool',[{value:'',label:'No material'},...state.materials.filter(m=>m.stock_status!=='Empty'&&m.stock_status!=='Archived').map(m=>({value:m.id,label:`${m.inventory_code} · ${m.name} · ${Number(m.remaining_amount).toFixed(0)}${m.unit}`}))],'')}
    ${selectField('profile_id','Starting profile',[{value:'',label:'No profile'},...state.profiles.map(p=>({value:p.id,label:p.name}))],'')}
    ${selectField('status','Status',['Queued','Printing','Complete','Failed'],'Queued')}
    ${field('duration_minutes','Estimated / actual minutes','','number')}
    <div class="field"><label>Material used</label><input name="material_used" type="number" step="0.001"><small id="jobMaterialUsedHint">Choose a stock item to apply its g/ml unit.</small></div>
    <div class="field wide" id="jobSettingsWrap">${settingsEditor('FDM',{})}</div>
    <div class="field wide"><label>Print notes</label><textarea name="notes" placeholder="Orientation, supports, model preparation or anything else worth remembering…"></textarea></div>
  </form>`,`<button class="ghost" data-close-modal>Cancel</button><button class="primary" id="createJobBtn">Create print record</button>`,'Print Lab');
  const form=$('#jobForm');form.dataset.technology='FDM';wireJobRecipeForm(form,{});const modelPicker=bindJobModelPicker(state.models,[]);
  $('#chooseJobToolpath').onclick=()=>$('#jobToolpathInput').click();
  $('#jobToolpathInput').onchange=async e=>{const file=e.target.files[0];if(!file)return;const button=$('#chooseJobToolpath'),stateBox=$('#jobToolpathState');button.disabled=true;button.textContent='Reading file…';stateBox.className='toolpath-import-empty busy';stateBox.innerHTML='<span>◌</span><div><strong>Inspecting slicer metadata…</strong><small>Large files are read in bounded sections.</small></div>';try{const body=new FormData();body.append('file',file);toolpath=await api('/api/jobs/toolpath/inspect',{method:'POST',body});$('#jobToolpathToken').value=toolpath.token;stateBox.className='';stateBox.innerHTML=toolpathImportSummary(toolpath);const name=form.querySelector('[name=name]');if(!name.value)name.value=file.name.replace(/\.(?:gcode|bgcode|3mf|pm3)$/i,'');const duration=form.querySelector('[name=duration_minutes]');if(toolpath.duration_minutes!=null)duration.value=toolpath.duration_minutes;applyToolpathSetup(form,toolpath);toast(`${techFamily(toolpath.technology)} setup read from ${file.name}`);}catch(err){toolpath=null;$('#jobToolpathToken').value='';stateBox.className='toolpath-import-empty error';stateBox.innerHTML=`<span>!</span><div><strong>Could not read this print file</strong><small>${esc(err.message)}</small></div>`;toast(err.message,true);}finally{button.disabled=false;button.textContent='Choose another file';e.target.value='';}};
  form.querySelector('[name=material_id]').addEventListener('change',()=>{if(toolpath)applyToolpathMaterialAmount(form,toolpath);});
  $('#createJobBtn').onclick=async()=>{const d=formDataObject(form);d.models=modelPicker.value;d.model_id=d.models[0]?.model_id||null;d.duration_minutes=d.duration_minutes?Number(d.duration_minutes):null;d.material_used=d.material_used?Number(d.material_used):null;d.settings_snapshot=collectSettings(form);d.technology=selectedJobTechnology(form);if(d.status==='Printing')d.started_at=new Date().toISOString();if(['Complete','Failed'].includes(d.status))d.completed_at=new Date().toISOString();try{const j=await api('/api/jobs',jsonOpt('POST',d));toast(toolpath?'Print file attached and job logged':'Print job added');closeModal();if(['Complete','Failed'].includes(j.status))jobModal(j.id);else renderJobs();}catch(err){toast(err.message,true);}};
}

async function jobModal(id){await refreshCore();const j=await api(`/api/jobs/${id}`);const insights=await api(`/api/jobs/insights/recipe?${new URLSearchParams({...(j.model_id?{model_id:j.model_id}:{}),...(j.material_id?{material_id:j.material_id}:{}),...(j.printer_id?{printer_id:j.printer_id}:{})})}`);const tech=j.technology||j.printer_technology||'FDM';openModal(j.name,`<div class="job-detail-layout lab-detail"><div class="job-photo-panel">${j.result_photo?`<img src="/api/jobs/${j.id}/photo" alt="Print result">`:`<div class="job-photo-empty"><span>▧</span><strong>No result photo yet</strong><small>Photos make recipe comparisons much more useful.</small></div>`}<input id="jobPhotoInput" type="file" accept="image/jpeg,image/png,image/webp" hidden><button class="small-btn full" id="chooseJobPhoto">${j.result_photo?'Replace result photo':'Add result photo'}</button><div class="stock-impact-card"><span class="kicker">Inventory impact</span>${j.stock_deducted_amount?`<strong>−${Number(j.stock_deducted_amount).toFixed(1)} ${esc(j.material_unit||'')}</strong><small>from ${esc(j.material_inventory_code||j.material_name||'stock')}</small>${j.material_cost!=null?`<b>${money(j.material_cost)} material cost</b>`:''}`:`<strong>Not deducted yet</strong><small>Stock reconciles when a job is Complete or Failed.</small>`}</div></div><div><form id="jobEdit" class="fields">${field('name','Job name',j.name,'text','wide')}${selectField('status','Status',['Queued','Printing','Complete','Failed'],j.status)}${selectField('project_id','Project',[{value:'',label:'No project'},...state.projects.map(p=>({value:p.id,label:p.name}))],j.project_id||'')}${selectField('model_id','Model',[{value:'',label:'No model'},...state.models.map(m=>({value:m.id,label:m.title}))],j.model_id||'')}${selectField('printer_id','Physical printer',[{value:'',label:'No printer'},...state.printers.map(p=>({value:p.id,label:`${p.inventory_code} · ${p.name}`}))],j.printer_id||'')}${selectField('material_id','Bottle / spool',[{value:'',label:'No material'},...state.materials.map(m=>({value:m.id,label:`${m.inventory_code} · ${m.name}`}))],j.material_id||'')}${selectField('profile_id','Profile used',[{value:'',label:'No profile'},...state.profiles.map(p=>({value:p.id,label:p.name}))],j.profile_id||'')}${field('duration_minutes','Duration (minutes)',j.duration_minutes??'','number')}${field('material_used',`Material used (${j.material_unit||'g/ml'})`,j.material_used??'','number')}<div class="field wide" id="jobSettingsWrap">${settingsEditor(tech,j.settings_snapshot||{})}</div><div class="field wide"><div class="rating-section"><div><label>Overall print success</label><small>How successful was this attempt?</small></div><div class="rating-picker">${[1,2,3,4,5].map(x=>`<label><input type="radio" name="result_rating" value="${x}" ${Number(j.result_rating)===x?'checked':''}><span>★</span></label>`).join('')}</div></div>${resultMetricPicker(j.result_metrics||{})}</div><div class="field wide"><label>Failure categories <span class="muted">optional</span></label>${failurePicker(tech,j.failure_tags||[])}</div><div class="field wide"><label>Failure / issue summary</label><input name="failure_reason" value="${esc(j.failure_reason||'')}"></div><div class="field wide"><label>Print notes</label><textarea name="notes">${esc(j.notes||'')}</textarea></div></form><div class="lab-insights"><span class="kicker">Recipe history</span><div class="inventory-insight-strip"><div><small>Comparable attempts</small><strong>${insights.attempts}</strong></div><div><small>Success rate</small><strong>${insights.success_rate!=null?`${insights.success_rate}%`:'—'}</strong></div><div><small>Average rating</small><strong>${insights.avg_rating?`${insights.avg_rating} ★`:'—'}</strong></div></div>${insights.best&&insights.best.id!==j.id?`<div class="best-recipe-card compact"><div><small>Best comparable result</small><strong>${esc(insights.best.name)}</strong></div>${ratingStars(insights.best.result_rating)}<div class="recipe-mini">${settingsSummary(insights.best.settings_snapshot,insights.best.technology||tech,5)}</div><button class="small-btn" data-best-job="${insights.best.id}">Open result</button></div>`:''}</div></div></div>`,`<button class="danger" id="deleteJobBtn">Delete</button><button class="ghost" id="repeatJobBtn">Repeat setup</button><button class="primary" id="saveJobBtn">Save print record</button>`,'Print Lab result');const form=$('#jobEdit');form.dataset.technology=tech;wireJobRecipeForm(form,j.settings_snapshot||{});$('#chooseJobPhoto').onclick=()=>$('#jobPhotoInput').click();$('#jobPhotoInput').onchange=async e=>{if(!e.target.files[0])return;const fd=new FormData();fd.append('file',e.target.files[0]);await api(`/api/jobs/${id}/photo`,{method:'POST',body:fd});toast('Result photo saved');jobModal(id);};$('[data-best-job]')?.addEventListener('click',e=>jobModal(e.currentTarget.dataset.bestJob));$('#repeatJobBtn').onclick=async()=>{const n=await api(`/api/jobs/${id}/repeat`,{method:'POST'});toast('Repeat job queued with the same recipe');closeModal();jobModal(n.id)};$('#saveJobBtn').onclick=async()=>{const d=formDataObject(form);for(const k of ['duration_minutes','material_used','result_rating'])d[k]=d[k]?Number(d[k]):null;d.settings_snapshot=collectSettings(form);d.technology=selectedJobTechnology(form);d.failure_tags=$$('[data-failure-tag]:checked',form).map(x=>x.value);d.result_metrics=Object.fromEntries($$('[data-result-metric]',form).filter(x=>x.value).map(x=>[x.dataset.resultMetric,Number(x.value)]));if(d.status==='Printing'&&!j.started_at)d.started_at=new Date().toISOString();if(['Complete','Failed'].includes(d.status)&&!j.completed_at)d.completed_at=new Date().toISOString();await api(`/api/jobs/${id}`,jsonOpt('PATCH',d));toast(['Complete','Failed'].includes(d.status)?'Print result saved · stock reconciled':'Print record saved');closeModal();renderJobs();};$('#deleteJobBtn').onclick=async()=>{if(!(await confirmAction('Delete print record?',`“${j.name}” will be removed. Any stock deducted by this job will be restored.`)))return;await api(`/api/jobs/${id}`,{method:'DELETE'});toast('Print record deleted and inventory reconciled');closeModal();renderJobs();};}
async function jobModalWithToolpath(id){await jobModal(id);const job=await api(`/api/jobs/${id}`);if(!job.toolpath_file)return;const panel=$('.job-photo-panel'),metadata=job.toolpath_metadata||{};panel?.insertAdjacentHTML('beforeend',`<div class="job-toolpath-card"><span class="kicker">Sliced print file</span><strong>${esc(job.toolpath_original_name||'Attached print file')}</strong><small>${esc(metadata.slicer||'Slicer metadata')} · ${fmtBytes(job.toolpath_size_bytes||0)}</small><div>${metadata.material_volume_ml!=null?`<span><b>${Number(metadata.material_volume_ml).toFixed(2)} ml</b>volume</span>`:''}${metadata.duration_minutes!=null?`<span><b>${metadata.duration_minutes} min</b>estimate</span>`:''}<span><b>${Object.keys(metadata.settings||{}).length}</b>parameters</span></div><a class="small-btn button-link full" href="/api/jobs/${job.id}/toolpath">Download attached file</a></div>`);}
async function advanceJob(id){const j=state.jobs.find(x=>x.id===id);if(!j)return;const next={Queued:'Printing',Printing:'Complete',Complete:'Queued',Failed:'Queued'}[j.status]||'Printing';const patch={status:next};if(next==='Printing')patch.started_at=new Date().toISOString();if(next==='Complete')patch.completed_at=new Date().toISOString();await api(`/api/jobs/${id}`,jsonOpt('PATCH',patch));toast(`Job moved to ${next}`);if(next==='Complete')return jobModalWithToolpath(id);renderJobs();}

async function scanImport() {
  try {
    toast('Scanning /data/import…');
    const r = await api('/api/library/scan', { method: 'POST' });
    toast(`${r.created} imported, ${r.duplicates} duplicate${r.duplicates === 1 ? '' : 's'} skipped${r.errors.length ? `, ${r.errors.length} errors` : ''}`, !!r.errors.length);
    renderPage();
  } catch (e) { toast(e.message, true); }
}

$('#nav').addEventListener('click', e => {
  const b = e.target.closest('[data-page]');
  if (b) { $('#navScrim').classList.remove('show'); setPage(b.dataset.page); }
});
$('#mobileMenu').onclick = () => { $('.sidebar').classList.toggle('open'); $('#navScrim').classList.toggle('show', $('.sidebar').classList.contains('open')); };
$('#navScrim').onclick = () => { $('.sidebar').classList.remove('open'); $('#navScrim').classList.remove('show'); };
$('#fileInput').addEventListener('change', e => { if (e.target.files.length) uploadWizard(e.target.files); e.target.value = ''; });
$('#scanImportBtn').onclick = scanImport;
$('#modal').addEventListener('click', e => { if (e.target.matches('[data-close-modal]')) closeModal(); });

content.addEventListener('click', async e => {
  const a = e.target.closest('[data-action]');
  if (a) {
    const x = a.dataset.action;
    if (x === 'pick-upload') return $('#fileInput').click();
    if (x === 'scan-import') return scanImport();
    if (x === 'new-project') { if (state.page !== 'projects') { setPage('projects'); setTimeout(newProjectModal, 80); return; } return newProjectModal(); }
    if (x === 'material-catalog') return materialCatalogModal();
    if (x === 'printer-catalog') return printerCatalogModal();
    if (x === 'new-material') return newMaterialModal();
    if (x === 'new-printer') return newPrinterModal();
    if (x === 'new-profile') return newProfileModal();
    if (x === 'new-job') return newJobFromFileModal();
  }

  const newCollection = e.target.closest('[data-new-collection]'); if (newCollection) return newCollectionModal('manual');
  const saveSmart = e.target.closest('[data-save-smart]'); if (saveSmart) return newCollectionModal('smart');
  const editCollection = e.target.closest('[data-edit-collection]'); if (editCollection) return editCollectionModal();
  const special = e.target.closest('[data-library-special]'); if (special?.dataset.librarySpecial==='unfiled') { state.library.collectionId=''; state.library.unfiled=true; state.selectedIds.clear(); return renderLibrary(); }
  const collection = e.target.closest('[data-collection-id]'); if (collection) { state.library.collectionId = collection.dataset.collectionId || ''; state.library.unfiled=false; state.selectedIds.clear(); return renderLibrary(); }
  const clearSelection = e.target.closest('[data-clear-selection]'); if (clearSelection) { state.selectedIds.clear(); refreshSelectionUI(); return; }
  const bulk = e.target.closest('[data-bulk-action]'); if (bulk) return bulkActionModal(bulk.dataset.bulkAction);
  const jf = e.target.closest('[data-job-filter]'); if (jf) { state.jobStatus=jf.dataset.jobFilter; return renderJobs(); }
  const jo = e.target.closest('[data-job-open]'); if (jo) return jobModalWithToolpath(jo.dataset.jobOpen);
  const loadMore = e.target.closest('[data-load-more-models]'); if (loadMore) { state.library.visibleCount += 120; if ($('#libraryGrid')) $('#libraryGrid').innerHTML = libraryGrid(state.models); refreshSelectionUI(); return; }

  const view = e.target.closest('[data-library-view]');
  if (view) {
    state.library.view = view.dataset.libraryView;
    safeStorageSet('layervault-library-view', state.library.view);
    $$('[data-library-view]').forEach(b => b.classList.toggle('active', b.dataset.libraryView === state.library.view));
    if ($('#libraryGrid')) $('#libraryGrid').innerHTML = libraryGrid(state.models);
    return;
  }

  const filter = e.target.closest('[data-library-filter]');
  if (filter) {
    const key = filter.dataset.libraryFilter;
    const value = filter.dataset.value || '';
    if (key === 'clear') Object.assign(state.library, { q:'', category:'', extension:'', status:'', favorite:false, tag:'', sort:'newest' });
    if (key === 'all') Object.assign(state.library, { status:'', favorite:false, tag:'' });
    if (key === 'favorite') state.library.favorite = !state.library.favorite;
    if (key === 'status') state.library.status = state.library.status === value ? '' : value;
    if (key === 'tag') state.library.tag = '';
    if (key === 'clear') return renderLibrary();
    return updateLibrary();
  }

  const tag = e.target.closest('[data-tag-filter]');
  if (tag && state.page === 'library') {
    e.stopPropagation();
    state.library.tag = tag.dataset.tagFilter;
    return renderLibrary();
  }

  const jump = e.target.closest('[data-page-jump]');
  if (jump) { setPage(jump.dataset.pageJump); return; }

  const cat = e.target.closest('[data-library-category]');
  if (cat) {
    state.library.category = cat.dataset.libraryCategory;
    state.library.collectionId = '';
    state.library.unfiled = false;
    state.page = 'library';
    document.body.dataset.page = 'library';
    $$('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === 'library'));
    renderLibrary(cat.dataset.libraryCategory); return;
  }

  const fav = e.target.closest('[data-favorite]');
  if (fav) {
    e.stopPropagation();
    const m = state.models.find(x => x.id === fav.dataset.favorite);
    if (!m) return;
    await api(`/api/models/${m.id}`, jsonOpt('PATCH', { favorite: !m.favorite }));
    if (state.page === 'library') return updateLibrary();
    return renderPage();
  }

  const sel=e.target.closest('[data-select-model]'); if(sel){e.stopPropagation(); const id=sel.dataset.selectModel; sel.checked?state.selectedIds.add(id):state.selectedIds.delete(id); refreshSelectionUI(); return;}
  const mc = e.target.closest('[data-model-id]'); if (mc) return modelModal(mc.dataset.modelId);
  const pc = e.target.closest('[data-project-id]'); if (pc) return projectModal(pc.dataset.projectId);
  const sm = e.target.closest('[data-use-material]'); if (sm) return updateMaterialStock(sm.dataset.useMaterial);
  const qr = e.target.closest('[data-material-qr]'); if (qr) { e.stopPropagation(); return materialQrModal(qr.dataset.materialQr); }
  const po = e.target.closest('[data-printer-open]'); if (po) return printerModal(po.dataset.printerOpen);
  const dp = e.target.closest('[data-delete-printer]'); if (dp) { if (await confirmAction('Delete printer?', 'The printer will be removed from LayerVault. Existing print records remain intact.')) { await api(`/api/printers/${dp.dataset.deletePrinter}`, { method:'DELETE' }); renderPrinters(); } return; }
  const dpr = e.target.closest('[data-delete-profile]'); if (dpr) { e.stopPropagation(); if(await confirmAction('Delete print profile?','Historical jobs keep their settings snapshots.')) { await api(`/api/profiles/${dpr.dataset.deleteProfile}`,{method:'DELETE'}); renderPrinters(); } return; }
  const pro = e.target.closest('[data-profile-open]'); if (pro) return profileModal(pro.dataset.profileOpen);
  const jr = e.target.closest('[data-job-repeat]'); if (jr) { e.stopPropagation(); const n=await api(`/api/jobs/${jr.dataset.jobRepeat}/repeat`,{method:'POST'}); toast('Repeat job queued'); return jobModal(n.id); }
  const js = e.target.closest('[data-job-status]'); if (js) return advanceJob(js.dataset.jobStatus);

  if (e.target.matches('[data-uniform]')) { $$('[data-scale]').forEach(i => i.value = e.target.dataset.uniform); syncTransforms(); return; }
  if (e.target.matches('[data-rot-z]')) { const i = $('[data-rotate=z]'); i.value = Number(i.value) + Number(e.target.dataset.rotZ); syncTransforms(); return; }
  if (e.target.matches('[data-lay-flat]')) { $('[data-rotate=x]').value = -90; syncTransforms(); return; }
  if (e.target.matches('[data-mirror]') && viewer.object) { const axis = e.target.dataset.mirror; viewer.object.scale[axis] *= -1; return; }
  if (e.target.matches('[data-reset-transform]')) return resetTransforms();
  if (e.target.matches('[data-save-version]')) return saveWorkshopVersion();
  if (e.target.matches('[data-export-stl]')) return exportSTL();
  if (e.target.matches('[data-download-original]') && viewer.model) return location.href = `/api/models/${viewer.model.id}/file?download=true`;
});


content.addEventListener('dragstart', e => {
  const card=e.target.closest('.model-card[data-model-id]'); if(!card)return;
  const id=card.dataset.modelId;
  const ids=state.selectedIds.has(id)&&state.selectedIds.size?[...state.selectedIds]:[id];
  e.dataTransfer.effectAllowed='copy';
  e.dataTransfer.setData('application/x-layervault-models',JSON.stringify(ids));
  card.classList.add('dragging-model');
});
content.addEventListener('dragend', () => { $$('.dragging-model,.folder-drop-active',content).forEach(x=>x.classList.remove('dragging-model','folder-drop-active')); });
content.addEventListener('dragover', e => {
  if(!e.dataTransfer?.types?.includes('application/x-layervault-models'))return;
  const folder=e.target.closest('[data-drop-collection]'); if(!folder)return;
  e.preventDefault(); e.dataTransfer.dropEffect='copy';
  $$('[data-drop-collection].folder-drop-active',content).forEach(x=>{if(x!==folder)x.classList.remove('folder-drop-active')});
  folder.classList.add('folder-drop-active');
});
content.addEventListener('dragleave', e => { const folder=e.target.closest('[data-drop-collection]'); if(folder&&!folder.contains(e.relatedTarget))folder.classList.remove('folder-drop-active'); });
content.addEventListener('drop', async e => {
  if(!e.dataTransfer?.types?.includes('application/x-layervault-models'))return;
  const folder=e.target.closest('[data-drop-collection]'); if(!folder)return;
  e.preventDefault(); e.stopPropagation(); folder.classList.remove('folder-drop-active');
  let ids=[]; try{ids=JSON.parse(e.dataTransfer.getData('application/x-layervault-models')||'[]')}catch{}
  if(!ids.length)return;
  try{await api(`/api/collections/${folder.dataset.dropCollection}/models`,jsonOpt('POST',{model_ids:ids}));toast(`${ids.length} model${ids.length===1?'':'s'} added to folder`);state.collections=await api('/api/collections');renderLibrary();}catch(err){toast(err.message,true);}
});

content.addEventListener('input', e => { if (e.target.matches('[data-scale]')) return applyScaleEdit(e.target); if(e.target.matches('[data-dimension]')) return applyDimensionEdit(e.target); if(e.target.matches('[data-rotate]')) return syncTransforms(); });
content.addEventListener('change', e => { if(e.target.matches('#lockProportions')) syncDimensionInputs(); });
let dragDepth=0;
window.addEventListener('dragenter',e=>{if(!e.dataTransfer?.types?.includes('Files'))return; e.preventDefault();dragDepth++;$('#dropOverlay')?.classList.add('show');});
window.addEventListener('dragover',e=>{if(e.dataTransfer?.types?.includes('Files'))e.preventDefault();});
window.addEventListener('dragleave',e=>{if(!e.dataTransfer?.types?.includes('Files'))return;dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)$('#dropOverlay')?.classList.remove('show');});
window.addEventListener('drop',e=>{if(!e.dataTransfer?.files?.length)return;e.preventDefault();dragDepth=0;$('#dropOverlay')?.classList.remove('show');uploadWizard(e.dataTransfer.files);});
window.addEventListener('keydown', e => {
  if (!$('#confirmDialog').classList.contains('hidden')) return;
  const typing=/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName||'');
  if(state.page==='workshop'&&$('#modal').classList.contains('hidden')&&e.key==='Control')setWorkshopCameraModifier(true);
  if(state.page==='workshop'&&!typing&&$('#modal').classList.contains('hidden')){
    const key=e.key.toLowerCase();
    if((e.ctrlKey||e.metaKey)&&key==='z'){e.preventDefault();return e.shiftKey?redoWorkshop():undoWorkshop();}
    if((e.ctrlKey||e.metaKey)&&key==='y'){e.preventDefault();return redoWorkshop();}
    if((e.ctrlKey||e.metaKey)&&key==='c'){e.preventDefault();return copyWorkshopSelection();}
    if((e.ctrlKey||e.metaKey)&&key==='v'){e.preventDefault();return pasteWorkshopClipboard();}
    if((e.ctrlKey||e.metaKey)&&key==='d'){e.preventDefault();return duplicateWorkshopSelection();}
    if((e.ctrlKey||e.metaKey)&&key==='s'){e.preventDefault();return saveWorkshopDesign(false);}
    if(key==='delete'||key==='backspace'){e.preventDefault();return deleteWorkshopSelection();}
    if(key==='m'){e.preventDefault();return setWorkshopMode('translate');}
    if(key==='r'){e.preventDefault();return setWorkshopMode('rotate');}
    if(key==='s'){e.preventDefault();return setWorkshopMode('scale');}
    if(key==='l'){e.preventDefault();return toggleWorkshopAlignment();}
    if(key==='f'){e.preventDefault();return fitWorkshopView();}
  }
  if (e.key === 'Escape') {
    if(state.page==='workshop'&&viewer.selection.size){viewer.selection.clear();refreshWorkshopSelection();return;}
    if (!$('#modal').classList.contains('hidden')) return closeModal();
    $('.sidebar').classList.remove('open'); $('#navScrim').classList.remove('show');
  }
  if (e.key === '/' && state.page === 'library' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) {
    e.preventDefault(); $('#librarySearch')?.focus();
  }
  if (e.key === 'Tab' && !$('#modal').classList.contains('hidden')) {
    const f=focusables($('#modal')); if(!f.length)return; const first=f[0], last=f[f.length-1];
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
    else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
  }
});
window.addEventListener('keyup',e=>{if(e.key==='Control')setWorkshopCameraModifier(false);});
window.addEventListener('blur',()=>setWorkshopCameraModifier(false));
content.addEventListener('keydown', e => {
  if (!['Enter',' '].includes(e.key) || /BUTTON|INPUT|SELECT|TEXTAREA|A/.test(e.target.tagName)) return;
  const model=e.target.closest('[data-model-id]'); if(model){e.preventDefault();modelModal(model.dataset.modelId);return;}
  const project=e.target.closest('[data-project-id]'); if(project){e.preventDefault();projectModal(project.dataset.projectId);return;}
  const job=e.target.closest('[data-job-id]'); if(job){e.preventDefault();jobModalWithToolpath(job.dataset.jobId);}
  const mat=e.target.closest('[data-material-open]'); if(mat){e.preventDefault();materialModal(mat.dataset.materialOpen);return;}
  const prn=e.target.closest('[data-printer-open]'); if(prn){e.preventDefault();printerModal(prn.dataset.printerOpen);return;}
  const prof=e.target.closest('[data-profile-open]'); if(prof){e.preventDefault();profileModal(prof.dataset.profileOpen);return;}
});

window.__LAYERVAULT_READY__ = true;
document.documentElement.dataset.layervaultReady = 'true';
const bootFailure = $('#bootFailure');
if (bootFailure) bootFailure.classList.add('hidden');
const deepLink=new URLSearchParams(location.search); if(deepLink.get('material')){setPage('materials');setTimeout(()=>materialModal(deepLink.get('material')).catch(()=>{}),150);} else setPage('dashboard');
