const ODS_BASE = 'https://boamp-datadila.opendatasoft.com';
const DATASET_ID = 'boamp';
const ODS_APIKEY = '';

const TRAINING_TERMS = [
  'formation',
  '"formation professionnelle"',
  'apprentissage',
  '"formation continue"',
  '"actions de formation"',
];

const TRAINING_CPV_WHITELIST = [
  '80500000',
  '80510000',
  '80533100',
  '80570000',
  '80000000',
  '80553000',
  '79632000',
  '79952000',
];

const TRAINING_SERVICE_CATEGORY = '24';

const FIELD_CANDIDATES = {
  date: ['dateparution', 'date_publication', 'datepublication', 'date', 'publication_date', 'record_timestamp'],
  title: ['intitule', 'objet', 'titre', 'title', 'intitulé', 'objet_du_marche'],
  url: ['url', 'lien', 'pageurl', 'url_avis', 'url_detail_avis', 'avis_url', 'link', 'permalink', 'permalien'],
  cpv: ['cpv', 'code_cpv', 'main_cpv', 'codes_cpv'],
  dept: ['departement', 'departement_execution', 'code_departement', 'code_postal', 'departement_principal'],
  buyer: ['acheteur', 'acheteur_nom', 'acheteur_principal', 'acheteur_1'],
  description: ['description', 'objet_detaille', 'texte', 'resume', 'objet', 'objet_du_marche'],
  ref: ['reference', 'referencemarche', 'id', 'id_boamp', 'reference_mapa'],
  serviceCategory: ['categorie_services', 'categorie_service', 'categorie_de_services'],
  nature: ['nature', 'type_avis', 'nature_commune'],
  deadline: ['date_limite_remise_offres', 'date_limite', 'date_limite_reponse'],
  buyerAddress: ['nom_et_adresse_officiels_de_l_organisme_acheteur', 'adresse_acheteur', 'adresse'],
  budget: ['montant', 'montant_ht', 'montant_estime'],
  procedure: ['procedure', 'type_procedure'],
  marketType: ['type_marche', 'nature_marche'],
  place: ['lieu_execution', 'lieu_principal'],
};

class HttpError extends Error {
  constructor(url, status, body) {
    super(`HTTP ${status}`);
    this.url = url;
    this.status = status;
    this.body = body;
  }
}

const schemaCache = { promise: null };
const fieldsCache = { promise: null };

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) {
    let body = '';
    try {
      body = await res.text();
    } catch {
      body = '';
    }
    throw new HttpError(url, res.status, body);
  }
  return res.json();
}

async function getDatasetSchema() {
  if (schemaCache.promise) return schemaCache.promise;
  const suffix = ODS_APIKEY ? `?apikey=${encodeURIComponent(ODS_APIKEY)}` : '';
  const url = `${ODS_BASE.replace(/\/$/, '')}/api/v2/catalog/datasets/${DATASET_ID}${suffix}`;
  schemaCache.promise = fetchJson(url).catch((err) => {
    schemaCache.promise = null;
    throw err;
  });
  return schemaCache.promise;
}

function pickField(candidates, fallback, names) {
  for (const name of candidates) {
    if (names.includes(name)) return name;
  }
  return fallback;
}

async function getResolvedFields() {
  if (fieldsCache.promise) return fieldsCache.promise;
  fieldsCache.promise = getDatasetSchema().then((schema) => {
    const names = (schema?.dataset?.fields || []).map((f) => f?.name).filter(Boolean);
    return {
      date: pickField(FIELD_CANDIDATES.date, 'record_timestamp', names),
      title: pickField(FIELD_CANDIDATES.title, 'title', names),
      url: pickField(FIELD_CANDIDATES.url, 'permalink', names),
      cpv: pickField(FIELD_CANDIDATES.cpv, 'cpv', names),
      dept: pickField(FIELD_CANDIDATES.dept, 'departement', names),
      buyer: pickField(FIELD_CANDIDATES.buyer, 'acheteur', names),
      description: pickField(FIELD_CANDIDATES.description, 'description', names),
      ref: pickField(FIELD_CANDIDATES.ref, 'id', names),
      serviceCategory: pickField(FIELD_CANDIDATES.serviceCategory, 'categorie_services', names),
      nature: pickField(FIELD_CANDIDATES.nature, 'nature', names),
      deadline: pickField(FIELD_CANDIDATES.deadline, 'date_limite_remise_offres', names),
      buyerAddress: pickField(FIELD_CANDIDATES.buyerAddress, 'nom_et_adresse_officiels_de_l_organisme_acheteur', names),
      budget: pickField(FIELD_CANDIDATES.budget, 'montant', names),
      procedure: pickField(FIELD_CANDIDATES.procedure, 'procedure', names),
      marketType: pickField(FIELD_CANDIDATES.marketType, 'type_marche', names),
      place: pickField(FIELD_CANDIDATES.place, 'lieu_execution', names),
    };
  }).catch((err) => {
    fieldsCache.promise = null;
    throw err;
  });
  return fieldsCache.promise;
}

function safeLike(field, value) {
  const v = String(value).replace(/'/g, "''");
  return `string(${field}) LIKE '%${v}%'`;
}

function composeKeywords(manual, useTraining) {
  const parts = [];
  if (manual && manual.trim()) parts.push(manual.trim());
  if (useTraining) parts.push(TRAINING_TERMS.join(' OR '));
  return parts.join(' OR ');
}

function filtersFromParams(params) {
  const page = Math.max(1, parseInt(params.get('page') || '1', 10) || 1);
  const size = Math.min(100, Math.max(1, parseInt(params.get('pageSize') || '20', 10) || 20));
  const useTraining = params.get('useTraining') === '1';
  const useDate = params.get('useDate') !== '0';
  return {
    page,
    pageSize: size,
    useTraining,
    useDate,
    dateFrom: useDate ? (params.get('dateFrom') || null) : null,
    dateTo: useDate ? (params.get('dateTo') || null) : null,
    q: params.get('q') || '',
    cpvPrefix: params.get('cpvPrefix') || '',
    buyer: params.get('buyer') || '',
    deptCodes: params.getAll('deptCodes'),
    nature: params.getAll('nature'),
    sort: params.get('sort') || 'date',
  };
}

function buildExploreUrl(input, fields) {
  const params = new URLSearchParams();
  if (input.keywords) params.set('q', input.keywords);

  const where = [];
  const cpvField = fields.cpv || 'cpv';
  if (input.cpvWhitelist?.length) {
    const clauses = input.cpvWhitelist.map((code) => safeLike(cpvField, code));
    where.push(`(${clauses.join(' OR ')})`);
  }
  if (input.cpvPrefix) {
    const esc = input.cpvPrefix.replace(/'/g, "''");
    where.push(`(string(${cpvField}) LIKE '${esc}%' OR string(${cpvField}) LIKE '%${esc}%')`);
  }
  if (input.deptCodes?.length) {
    const values = input.deptCodes.map((code) => `'${code.replace(/'/g, "''")}'`);
    where.push(`(${fields.dept || 'departement'} IN (${values.join(',')}))`);
  }
  if (input.buyer) {
    where.push(safeLike(fields.buyer || 'acheteur', input.buyer));
  }
  if (input.serviceCategory) {
    where.push(`${fields.serviceCategory || 'categorie_services'} = '${input.serviceCategory.replace(/'/g, "''")}'`);
  }
  if (input.nature?.length) {
    const values = input.nature
      .map((val) => `'${String(val).replace(/'/g, "''")}'`)
      .join(',');
    if (values) where.push(`string(${fields.nature || 'nature'}) IN (${values})`);
  }
  const dateField = fields.date || 'record_timestamp';
  if (input.dateFrom) where.push(`${dateField} >= '${input.dateFrom}'`);
  if (input.dateTo) where.push(`${dateField} <= '${input.dateTo}'`);

  if (where.length) params.set('where', where.join(' AND '));

  if (input.sort === 'deadline' && fields.deadline) params.set('order_by', `-${fields.deadline}`);
  else if (input.sort === 'relevance' && input.keywords) params.set('order_by', 'relevance');
  else params.set('order_by', `-${dateField}`);

  params.set('limit', String(input.pageSize));
  params.set('offset', String((input.page - 1) * input.pageSize));

  if (ODS_APIKEY) params.set('apikey', ODS_APIKEY);
  return `${ODS_BASE.replace(/\/$/, '')}/api/explore/v2.1/catalog/datasets/${DATASET_ID}/records?${params.toString()}`;
}

function buildRecordsV1Url(input, fields) {
  const params = new URLSearchParams();
  params.set('dataset', DATASET_ID);
  params.set('rows', String(input.pageSize));
  params.set('start', String((input.page - 1) * input.pageSize));
  if (input.keywords) params.set('q', input.keywords);
  if (input.cpvWhitelist?.length) {
    input.cpvWhitelist.forEach((code) => params.append(`refine.${fields.cpv || 'cpv'}`, code));
  }
  if (input.serviceCategory) {
    params.append(`refine.${fields.serviceCategory || 'categorie_services'}`, input.serviceCategory);
  }
  if (input.deptCodes?.length) {
    input.deptCodes.forEach((code) => params.append(`refine.${fields.dept || 'code_departement'}`, code));
  }
  if (input.buyer) params.append(`refine.${fields.buyer || 'acheteur'}`, input.buyer);
  if (ODS_APIKEY) params.set('apikey', ODS_APIKEY);
  return `${ODS_BASE.replace(/\/$/, '')}/api/records/1.0/search/?${params.toString()}`;
}

function normalizeRecordUrl(base, datasetId, rawUrl, ref, recordId) {
  const baseNoSlash = base.replace(/\/$/, '');
  let host = '';
  try {
    host = new URL(baseNoSlash).hostname || '';
  } catch {
    host = '';
  }
  const datasetRecord = recordId
    ? `${baseNoSlash}/explore/dataset/${datasetId}/record/?id=${encodeURIComponent(recordId)}`
    : baseNoSlash;
  const isBoamp = host.endsWith('boamp.fr');
  if (!rawUrl) {
    if (isBoamp && ref) return `${baseNoSlash}/avis/detail/${encodeURIComponent(ref)}`;
    return datasetRecord;
  }
  try {
    const href = new URL(rawUrl, `${baseNoSlash}/`).toString();
    if (href === `${baseNoSlash}/` || href.includes('/pages/entreprise-accueil')) {
      if (isBoamp && ref) return `${baseNoSlash}/avis/detail/${encodeURIComponent(ref)}`;
      return datasetRecord;
    }
    return href;
  } catch {
    if (isBoamp && ref) return `${baseNoSlash}/avis/detail/${encodeURIComponent(ref)}`;
    return datasetRecord;
  }
}

function normalizeRecord(record, fields) {
  const base = ODS_BASE.replace(/\/$/, '');
  const row = record.fields || record;
  const recordId = record.id || record.recordid || row.id || row.recordid;
  const title =
    row[fields.title] ||
    row.objet ||
    row.titre ||
    row.title ||
    `Avis #${recordId || ''}`;
  const rawUrl =
    row[fields.url] ||
    row.permalink ||
    row.url_avis ||
    row.pageurl ||
    row.lien ||
    row.link ||
    row.url ||
    row.permalien;
  const ref = row[fields.ref] || recordId;
  const href = normalizeRecordUrl(base, DATASET_ID, rawUrl, ref, recordId);
  const dateValue = row[fields.date] || row.record_timestamp;
  const dateIso = dateValue ? String(dateValue).slice(0, 10) : null;
  const deadlineValue = row[fields.deadline];
  const deadlineIso = deadlineValue ? String(deadlineValue).slice(0, 10) : null;
  return {
    title,
    href,
    ref,
    date_iso: dateIso,
    buyer: row[fields.buyer],
    dept: row[fields.dept],
    cpv: row[fields.cpv],
    description: row[fields.description],
    deadline_iso: deadlineIso,
    buyer_address: row[fields.buyerAddress],
    budget: row[fields.budget],
    procedure: row[fields.procedure],
    market_type: row[fields.marketType],
    place: row[fields.place],
  };
}

async function queryExplore(input, fields) {
  const url = buildExploreUrl(input, fields);
  const data = await fetchJson(url);
  const results = Array.isArray(data.results) ? data.results : [];
  const items = results.map((row) => normalizeRecord(row, fields));
  const total = typeof data.total_count === 'number' ? data.total_count : null;
  return { items, total, debugUrl: url };
}

async function queryRecordsV1(input, fields) {
  const url = buildRecordsV1Url(input, fields);
  const data = await fetchJson(url);
  const results = Array.isArray(data.records) ? data.records : [];
  const items = results.map((row) => normalizeRecord(row, fields));
  const total = typeof data.nhits === 'number' ? data.nhits : null;
  return { items, total, debugUrl: url };
}

function shouldFallback(error) {
  if (error instanceof HttpError) {
    return error.status >= 400 && error.status < 500;
  }
  return true;
}

async function fetchOdsResults(params) {
  const filters = filtersFromParams(params);
  const fields = await getResolvedFields();
  const input = {
    ...filters,
    keywords: composeKeywords(filters.q, filters.useTraining),
    cpvWhitelist: filters.useTraining ? TRAINING_CPV_WHITELIST : [],
    serviceCategory: filters.useTraining ? TRAINING_SERVICE_CATEGORY : null,
  };
  try {
    const primary = await queryExplore(input, fields);
    if (!primary.items.length && filters.useTraining) {
      const fallback = await queryRecordsV1(input, fields);
      return fallback.items.length ? fallback : primary;
    }
    return primary;
  } catch (err) {
    if (shouldFallback(err)) {
      return queryRecordsV1(input, fields);
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

const el = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = text;
  return element;
};

const q = (id) => document.getElementById(id);

const launchBtn = q('launch');
const resetBtn = q('reset');
const statusEl = q('status');
const resultsEl = q('results');
const countEl = q('count');
const debugEl = q('debug');
const summaryEl = q('summary');
const listEl = q('list');
const pageEl = q('page');
const pagesEl = q('pages');
const prevBtn = q('prev');
const nextBtn = q('next');

const useTraining = q('useTraining');
const useDate = q('useDate');
const dateFrom = q('dateFrom');
const dateTo = q('dateTo');
const pageSize = q('pageSize');
const useKeywords = q('useKeywords');
const keywords = q('keywords');
const useCpv = q('useCpv');
const cpvPrefix = q('cpvPrefix');
const useBuyer = q('useBuyer');
const buyer = q('buyer');
const useDept = q('useDept');
const natureAO = q('natureAO');
const natureAT = q('natureAT');
const sortSel = q('sort');
const infinite = q('infinite');
const deptSearch = q('deptSearch');
const addDeptBtn = q('addDept');

const profileName = q('profileName');
const profilesSel = q('profiles');
const saveProfileBtn = q('saveProfile');
const loadProfileBtn = q('loadProfile');
const deleteProfileBtn = q('deleteProfile');
const shareLinkBtn = q('shareLink');

let currentPage = 1;
let totalPages = 1;
let isLoadingMore = false;

function iso(d) {
  return d.toISOString().slice(0, 10);
}

function setDefaultDates() {
  const today = new Date();
  const from = new Date(today.getTime() - 90 * 24 * 3600 * 1000);
  const to = new Date(today.getTime() + 365 * 24 * 3600 * 1000);
  dateFrom.value = iso(from);
  dateTo.value = iso(to);
}

function gatherFilters(page) {
  const params = new URLSearchParams();
  params.set('pageSize', pageSize.value || '20');
  params.set('page', String(page || 1));
  if (useTraining.checked) params.set('useTraining', '1');
  params.set('useDate', useDate.checked ? '1' : '0');
  const sort = (sortSel && sortSel.value) || 'date';
  if (sort && sort !== 'date') params.set('sort', sort);
  if (useDate.checked) {
    if (dateFrom.value) params.set('dateFrom', dateFrom.value);
    if (dateTo.value) params.set('dateTo', dateTo.value);
  }
  if (useKeywords.checked && keywords.value.trim()) params.set('q', keywords.value.trim());
  if (useCpv.checked && cpvPrefix.value.trim()) params.set('cpvPrefix', cpvPrefix.value.trim());
  if (useBuyer.checked && buyer.value.trim()) params.set('buyer', buyer.value.trim());
  const depts = Array.from(document.querySelectorAll('input.dept:checked')).map((input) => input.value);
  depts.forEach((code) => params.append('deptCodes', code));
  if (natureAO.checked) params.append('nature', 'AppelOffre');
  if (natureAT.checked) params.append('nature', 'Attribution');
  return params;
}

function setFiltersFromParams(params) {
  useTraining.checked = params.get('useTraining') === '1';
  useDate.checked = params.get('useDate') !== '0';
  if (params.get('dateFrom')) dateFrom.value = params.get('dateFrom');
  if (params.get('dateTo')) dateTo.value = params.get('dateTo');
  const sort = params.get('sort');
  if (sort && sortSel) sortSel.value = sort;
  const qv = params.get('q') || '';
  useKeywords.checked = !!qv;
  keywords.value = qv;
  const cpv = params.get('cpvPrefix') || '';
  useCpv.checked = !!cpv;
  cpvPrefix.value = cpv;
  const buyerValue = params.get('buyer') || '';
  useBuyer.checked = !!buyerValue;
  buyer.value = buyerValue;
  const deptCodes = params.getAll('deptCodes');
  document.querySelectorAll('input.dept').forEach((input) => {
    input.checked = deptCodes.includes(input.value);
  });
  if (deptCodes.length) useDept.checked = true;
  const natures = params.getAll('nature');
  natureAO.checked = natures.includes('AppelOffre');
  natureAT.checked = natures.includes('Attribution');
  const pz = params.get('pageSize');
  if (pz) pageSize.value = pz;
  updateActiveFiltersView();
}

function refreshProfilesList() {
  const data = JSON.parse(localStorage.getItem('profiles') || '{}');
  profilesSel.innerHTML = '';
  Object.keys(data).forEach((name) => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    profilesSel.appendChild(option);
  });
}

function updateActiveFiltersView() {
  const box = document.getElementById('activeFilters');
  if (!box) return;
  box.innerHTML = '';
  const addChip = (label, action, value) => {
    const span = el('span', 'badge chip', label + ' ');
    if (action) span.dataset.action = action;
    if (value !== undefined && value !== null) span.dataset.value = value;
    const close = el('span', 'chip-x', '×');
    span.appendChild(close);
    box.appendChild(span);
  };
  if (useTraining.checked) addChip('Formation', 'training');
  if (useDate.checked) {
    const from = dateFrom.value || '…';
    const to = dateTo.value || '…';
    addChip(`Période ${from} → ${to}`, 'date');
  }
  if (natureAO.checked) addChip('Nature: AppelOffre', 'nature', 'AppelOffre');
  if (natureAT.checked) addChip('Nature: Attribution', 'nature', 'Attribution');
  if (useKeywords.checked && keywords.value.trim()) addChip(`q: ${keywords.value.trim()}`, 'q');
  if (useCpv.checked && cpvPrefix.value.trim()) addChip(`CPV: ${cpvPrefix.value.trim()}*`, 'cpv');
  if (useBuyer.checked && buyer.value.trim()) addChip(`Acheteur: ${buyer.value.trim()}`, 'buyer');
  const depts = Array.from(document.querySelectorAll('input.dept:checked')).map((input) => input.value);
  if (depts.length) {
    addChip(`Départements: ${depts.join(', ')}`, 'dept');
    depts.forEach((code) => addChip(`Dept ${code}`, 'deptOne', code));
  }
  if (!box.children.length) {
    box.appendChild(el('span', 'badge', 'Aucun filtre actif'));
  }
}

function renderItems(items, append = false) {
  if (!append) listEl.innerHTML = '';
  items.forEach((item) => {
    const article = el('article', 'item');
    if (item.deadline_iso) {
      const now = new Date();
      const deadline = new Date(`${item.deadline_iso}T00:00:00`);
      const diffDays = (deadline - now) / (1000 * 3600 * 24);
      if (diffDays <= 7 && diffDays >= -1) {
        article.classList.add('urgent');
      }
    }
    const title = el('a', 'title', item.title || 'Avis');
    title.href = item.href || '#';
    title.target = '_blank';
    title.rel = 'noopener noreferrer';
    article.appendChild(title);

    const meta = el('div', 'muted small');
    const parts = [];
    if (item.date_iso) parts.push(`Publié le ${item.date_iso}`);
    if (item.ref) parts.push(`Réf. ${item.ref}`);
    meta.textContent = parts.join(' • ');
    article.appendChild(meta);

    const badges = el('div', 'badges');
    if (item.buyer) badges.appendChild(el('span', 'badge', String(item.buyer)));
    if (item.dept) {
      if (Array.isArray(item.dept)) item.dept.slice(0, 3).forEach((val) => badges.appendChild(el('span', 'badge', String(val))));
      else badges.appendChild(el('span', 'badge', String(item.dept)));
    }
    if (item.cpv) {
      if (Array.isArray(item.cpv)) item.cpv.slice(0, 3).forEach((val) => badges.appendChild(el('span', 'badge', String(val))));
      else badges.appendChild(el('span', 'badge', String(item.cpv)));
    }
    if (item.deadline_iso) badges.appendChild(el('span', 'badge', `Limite: ${item.deadline_iso}`));
    article.appendChild(badges);

    if (item.description) article.appendChild(el('div', 'desc', String(item.description)));
    const details = [];
    if (item.place) details.push(`Lieu: ${item.place}`);
    if (item.buyer_address) details.push(`Adresse: ${item.buyer_address}`);
    if (item.procedure) details.push(`Procédure: ${item.procedure}`);
    if (item.market_type) details.push(`Type: ${item.market_type}`);
    if (item.budget) details.push(`Budget: ${item.budget}`);
    if (details.length) article.appendChild(el('div', 'muted small', details.join(' • ')));

    listEl.appendChild(article);
  });
}

async function run(page = 1) {
  if (isLoadingMore) return;
  currentPage = page;
  launchBtn.disabled = true;
  prevBtn.disabled = true;
  nextBtn.disabled = true;
  statusEl.textContent = 'Chargement...';
  if (page === 1) {
    listEl.innerHTML = '';
    resultsEl.classList.add('hidden');
  }
  const params = gatherFilters(currentPage);
  isLoadingMore = page > 1;
  try {
    const data = await fetchOdsResults(params);
    const items = Array.isArray(data.items) ? data.items : [];
    const total = data.total != null ? data.total : (page === 1 ? items.length : null);
    countEl.textContent = total != null ? String(total) : String(items.length);
    debugEl.textContent = data.debugUrl || '';
    if (summaryEl) summaryEl.textContent = total != null ? `Total estimé: ${total}` : '';
    const size = parseInt(pageSize.value, 10) || 20;
    totalPages = total && size ? Math.max(1, Math.ceil(total / size)) : (page === 1 && items.length < size ? 1 : currentPage);
    pageEl.textContent = String(currentPage);
    pagesEl.textContent = String(totalPages);

    renderItems(items, page > 1);

    resultsEl.classList.remove('hidden');
    statusEl.textContent = items.length ? '' : 'Aucun résultat.';
    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = totalPages <= currentPage;
  } catch (err) {
    console.error(err);
    if (err instanceof HttpError) {
      statusEl.textContent = `Erreur API (${err.status})`;
    } else {
      statusEl.textContent = `Erreur: ${err.message || err}`;
    }
  } finally {
    launchBtn.disabled = false;
    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = totalPages <= currentPage;
    isLoadingMore = false;
  }
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

if (launchBtn) launchBtn.addEventListener('click', () => run(1));
if (resetBtn) resetBtn.addEventListener('click', () => {
  useTraining.checked = true;
  useDate.checked = true;
  setDefaultDates();
  useKeywords.checked = true;
  keywords.value = 'formation';
  useCpv.checked = false;
  cpvPrefix.value = '';
  useBuyer.checked = false;
  buyer.value = '';
  useDept.checked = false;
  document.querySelectorAll('input.dept').forEach((input) => {
    input.checked = false;
  });
  natureAO.checked = true;
  natureAT.checked = false;
  pageSize.value = '20';
  sortSel.value = 'date';
  updateActiveFiltersView();
  statusEl.textContent = '';
  resultsEl.classList.add('hidden');
});
if (prevBtn) prevBtn.addEventListener('click', () => {
  if (currentPage > 1) run(currentPage - 1);
});
if (nextBtn) nextBtn.addEventListener('click', () => {
  if (currentPage < totalPages) run(currentPage + 1);
});

if (saveProfileBtn) saveProfileBtn.addEventListener('click', () => {
  const name = (profileName.value || '').trim();
  if (!name) {
    alert('Nom de profil requis');
    return;
  }
  const params = gatherFilters(1);
  const data = JSON.parse(localStorage.getItem('profiles') || '{}');
  data[name] = params.toString();
  localStorage.setItem('profiles', JSON.stringify(data));
  refreshProfilesList();
});

if (loadProfileBtn) loadProfileBtn.addEventListener('click', () => {
  const name = profilesSel.value;
  if (!name) return;
  const data = JSON.parse(localStorage.getItem('profiles') || '{}');
  const qs = data[name];
  if (!qs) return;
  setFiltersFromParams(new URLSearchParams(qs));
  run(1);
});

if (deleteProfileBtn) deleteProfileBtn.addEventListener('click', () => {
  const name = profilesSel.value;
  if (!name) return;
  const data = JSON.parse(localStorage.getItem('profiles') || '{}');
  delete data[name];
  localStorage.setItem('profiles', JSON.stringify(data));
  refreshProfilesList();
});

if (shareLinkBtn) shareLinkBtn.addEventListener('click', async () => {
  const params = gatherFilters(1);
  const link = `${location.origin}${location.pathname}?${params.toString()}`;
  try {
    await navigator.clipboard.writeText(link);
    statusEl.textContent = 'Lien copié dans le presse-papiers';
  } catch {
    window.prompt('Copiez ce lien :', link);
  }
});

const DEPTS = [
  ['75', 'Paris'],
  ['77', 'Seine-et-Marne'],
  ['78', 'Yvelines'],
  ['91', 'Essonne'],
  ['92', 'Hauts-de-Seine'],
  ['93', 'Seine-Saint-Denis'],
  ['94', 'Val-de-Marne'],
  ['95', "Val-d'Oise"],
  ['59', 'Nord'],
  ['62', 'Pas-de-Calais'],
  ['80', 'Somme'],
  ['02', 'Aisne'],
  ['60', 'Oise'],
  ['09', 'Ariège'],
  ['11', 'Aude'],
  ['12', 'Aveyron'],
  ['30', 'Gard'],
  ['31', 'Haute-Garonne'],
  ['32', 'Gers'],
  ['34', 'Hérault'],
  ['46', 'Lot'],
  ['48', 'Lozère'],
  ['65', 'Hautes-Pyrénées'],
  ['66', 'Pyrénées-Orientales'],
  ['81', 'Tarn'],
  ['82', 'Tarn-et-Garonne'],
];

const deptList = document.getElementById('deptList');
if (deptList) {
  DEPTS.forEach(([code, name]) => {
    const option = document.createElement('option');
    option.value = `${code} - ${name}`;
    deptList.appendChild(option);
  });
}

function addDeptFromInput() {
  if (!deptSearch) return;
  const value = (deptSearch.value || '').trim();
  if (!value) return;
  let code = value.split('-')[0].trim();
  if (!/^[0-9]{2,3}$/.test(code)) {
    const hit = DEPTS.find(([, name]) => name.toLowerCase() === value.toLowerCase());
    if (hit) code = hit[0];
  }
  const checkbox = Array.from(document.querySelectorAll('input.dept')).find((input) => input.value === code);
  if (checkbox) {
    checkbox.checked = true;
    useDept.checked = true;
    updateActiveFiltersView();
  }
  deptSearch.value = '';
}

if (addDeptBtn) addDeptBtn.addEventListener('click', addDeptFromInput);
if (deptSearch) {
  deptSearch.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      addDeptFromInput();
    }
  });
}

const IDF_CODES = ['75', '77', '78', '91', '92', '93', '94', '95'];
if (useDept) {
  useDept.addEventListener('change', () => {
    document.querySelectorAll('input.dept').forEach((input) => {
      if (IDF_CODES.includes(input.value)) input.checked = useDept.checked;
    });
    updateActiveFiltersView();
  });
}

window.addEventListener('scroll', () => {
  if (!infinite || !infinite.checked) return;
  if (isLoadingMore) return;
  if (currentPage >= totalPages) return;
  const nearBottom = window.innerHeight + window.scrollY >= document.body.offsetHeight - 200;
  if (!nearBottom) return;
  run(currentPage + 1);
});

[
  useTraining,
  useDate,
  dateFrom,
  dateTo,
  pageSize,
  useKeywords,
  keywords,
  useCpv,
  cpvPrefix,
  useBuyer,
  buyer,
  useDept,
  natureAO,
  natureAT,
].forEach((element) => {
  if (element) element.addEventListener('change', updateActiveFiltersView);
});
document.querySelectorAll('input.dept').forEach((input) => {
  input.addEventListener('change', updateActiveFiltersView);
});

const activeFiltersBox = document.getElementById('activeFilters');
if (activeFiltersBox) {
  activeFiltersBox.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const action = target.dataset.action;
    const value = target.dataset.value;
    switch (action) {
      case 'training':
        useTraining.checked = false;
        break;
      case 'date':
        useDate.checked = false;
        dateFrom.value = '';
        dateTo.value = '';
        break;
      case 'nature':
        if (value === 'AppelOffre') natureAO.checked = false;
        if (value === 'Attribution') natureAT.checked = false;
        break;
      case 'q':
        useKeywords.checked = false;
        keywords.value = '';
        break;
      case 'cpv':
        useCpv.checked = false;
        cpvPrefix.value = '';
        break;
      case 'buyer':
        useBuyer.checked = false;
        buyer.value = '';
        break;
      case 'dept':
        useDept.checked = false;
        document.querySelectorAll('input.dept').forEach((input) => {
          input.checked = false;
        });
        break;
      case 'deptOne': {
        const checkbox = Array.from(document.querySelectorAll('input.dept')).find((input) => input.value === value);
        if (checkbox) checkbox.checked = false;
        if (!document.querySelector('input.dept:checked')) useDept.checked = false;
        break;
      }
      default:
        break;
    }
    updateActiveFiltersView();
    run(1);
  });
}

setDefaultDates();
refreshProfilesList();
if (location.search && location.search.length > 1) {
  setFiltersFromParams(new URLSearchParams(location.search));
}
updateActiveFiltersView();
run(1);
