"""
Back-end Flask application serving a minimal HTML/CSS front for BOAMP search.

Purpose
- Provide a Python-only back end (single dependency: Flask) that queries the
  Opendatasoft (ODS) APIs for the BOAMP dataset and renders results
  server-side (no JavaScript required on the front end).

Design goals
- Minimal dependencies (Flask only; HTTP uses Python stdlib `urllib`).
- Two top-level folders: `Front-end/` for display and `Back-end/` for logic.
- Server-rendered filters and results to satisfy “only HTML/CSS front”.
- Robust error handling and clear, exhaustive documentation of variables and
  functions, including expected inputs/outputs and likely error causes.

Environment variables
- `ODS_BASE`: Base URL of Opendatasoft portal (default: boamp-datadila).
- `DATASET_ID`: Slug of the dataset to query (default: "boamp").
- `ODS_APIKEY`: Optional ODS API key if required by the portal.

Endpoints
- GET `/`: Main page with filter form and results list.

Notes on ODS APIs
- Explore v2.1 (preferred): `${ODS_BASE}/api/explore/v2.1/catalog/datasets/${DATASET_ID}/records`
- Records v1 (fallback): `${ODS_BASE}/api/records/1.0/search/`

Copyright
- This file intentionally contains detailed comments per user request.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from flask import Flask, request, render_template, jsonify
from flask import Response
# Response: utile pour renvoyer des fichiers (CSV/ICS) avec bon mimetype

# Standard library HTTP client utilities
from urllib.parse import urlencode, urljoin, urlparse
# Remarque: ces utilitaires sont utilisés dans la construction d'URL ODS,
# la normalisation des liens de résultats, et l'encodage de query strings.
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import ssl
try:
    import certifi  # type: ignore
except Exception:  # certifi optional; installed via requirements
    certifi = None  # type: ignore


# --------------------------------------------------------------------------------------
# Configuration and domain constants
# --------------------------------------------------------------------------------------

# ODS portal base URL. If not provided, defaults to boamp-datadila (public portal).
# Default to the Opendatasoft BOAMP portal (stable API endpoints)
ODS_BASE: str = os.environ.get("ODS_BASE", "https://boamp-datadila.opendatasoft.com")
# Exemple d'usage: changer pour un portail ODS interne -> exportez ODS_BASE.

# Dataset slug. "boamp" is the standard dataset for BOAMP notices on the portal.
DATASET_ID: str = os.environ.get("DATASET_ID", "boamp")
# Exemple d'usage: certains portails hébergent un dataset "boamp_test".

# Optional API key for portals requiring authentication/quotas. If absent, requests
# are made anonymously. Keep in mind that some portals throttle or forbid anonymous access.
ODS_APIKEY: Optional[str] = os.environ.get("ODS_APIKEY")
# Si None, appels anonymes (souvent suffisants en lecture publique).

# Preference for Explore v2.1 first (True) or Records v1 first (False)
PREFER_EXPLORE: bool = os.environ.get("PREFER_EXPLORE", "1").lower() in {"1", "true", "yes", "on"}
# Mettre à 0 si certaines clauses WHERE sont refusées par le portail.

# Timeouts and caching
REQUEST_TIMEOUT_SECONDS: int = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "30"))
# Augmentez si réseau lent/filtré; baissez pour éviter de bloquer l'UI.
RESULTS_CACHE_TTL_SECONDS: int = int(os.environ.get("RESULTS_CACHE_TTL_SECONDS", "60"))
# Adapter selon le volume et la fréquence de consultation.
_RESULTS_CACHE: Dict[str, Dict[str, Any]] = {}
# Structure: { key: { value: (records,total,debug_url,fields), ts: float } }
AUTO_FALLBACK_INSECURE_SSL: bool = os.environ.get("AUTO_FALLBACK_INSECURE_SSL", "1").lower() in {"1", "true", "yes", "on"}
# Si True, retente 1 fois en SSL non vérifié lorsqu'un CERTIFICATE_VERIFY_FAILED survient.
# Utile pour les environnements d'entreprise; à désactiver en production stricte.


# Curated list of Île-de-France departments for quick filtering in the UI.
IDF_DEPARTEMENTS: List[Dict[str, str]] = [
    {"code": "75", "name": "75 – Paris"},
    {"code": "77", "name": "77 – Seine-et-Marne"},
    {"code": "78", "name": "78 – Yvelines"},
    {"code": "91", "name": "91 – Essonne"},
    {"code": "92", "name": "92 – Hauts-de-Seine"},
    {"code": "93", "name": "93 – Seine-Saint-Denis"},
    {"code": "94", "name": "94 – Val-de-Marne"},
    {"code": "95", "name": "95 – Val d'Oise"},
]


# Curated keyword buckets to simplify text search composition for users.
KEYWORD_BUCKETS: Dict[str, List[str]] = {
    "UX/UI": [
        "UX",
        "UI",
        "design d'interface",
        "recherche utilisateur",
        "prototypage",
        "Figma",
        "ergonomie",
    ],
    "3D / Motion": ["3D", "motion design", "animation", "After Effects", "Cinema 4D", "Blender"],
    "Unity / Unreal": ["Unity", "Unreal", "jeu vidéo", "temps réel", "VR", "AR", "XR"],
    "IA créatives": [
        "intelligence artificielle",
        "IA générative",
        "Stable Diffusion",
        "Midjourney",
        "prompt",
        "création assistée",
    ],
    "Data / BI": ["data", "Power BI", "Excel avancé", "Tableau", "analyse de données", "visualisation"],
    "Dev Web": ["développement web", "JavaScript", "TypeScript", "React", "Next.js", "Node.js"],
    "Marketing digital": ["marketing digital", "SEO", "SEA", "social media", "campagnes", "automation"],
    "Soft skills / Management": [
        "management",
        "prise de parole",
        "communication",
        "gestion de projet",
        "agilité",
        "scrum",
    ],
}


# Training perimeter per user guidance
# - TRAINING_TERMS: Optional text terms to broaden search for "formation".
# - TRAINING_CPV_WHITELIST: Official CPV codes considered as training.
# - TRAINING_SERVICE_CATEGORY: EU service category signaling professional training.
TRAINING_TERMS: List[str] = [
    "formation",
    '"formation professionnelle"',
    "apprentissage",
    '"formation continue"',
    '"actions de formation"',
]

TRAINING_CPV_WHITELIST: List[str] = [
    # Curated list from user for formation domain
    "80500000",  # Services de formation
    "80510000",  # Services de formation spécialisés
    "80533100",  # Formation en technologies de l’information
    "80570000",  # Services de formation continue
    "80000000",  # Enseignement et formation générale
    "80553000",  # Formation à distance
    "79632000",  # Services de formation et de conseil en gestion du personnel
    "79952000",  # Organisation de séminaires / conférences
]

# Human-friendly catalog of CPV codes (subset focused on formation)
CPV_CATALOG: List[Dict[str, str]] = [
    {"code": "80500000", "domaine": "Formation professionnelle", "description": "Services de formation"},
    {"code": "80510000", "domaine": "Formation du personnel", "description": "Services de formation spécialisés"},
    {"code": "80533100", "domaine": "Formation en informatique", "description": "Formation en technologies de l’information"},
    {"code": "80570000", "domaine": "Formation continue", "description": "Services de formation continue"},
    {"code": "80000000", "domaine": "Enseignement et formation", "description": "Enseignement et formation générale"},
    {"code": "80553000", "domaine": "Formation à distance", "description": "Formation à distance"},
    {"code": "79632000", "domaine": "Conseil en formation", "description": "Services de formation et de conseil en gestion du personnel"},
    {"code": "79952000", "domaine": "Événements pédagogiques", "description": "Organisation de séminaires / conférences"},
]

TRAINING_SERVICE_CATEGORY: int = 24


# Field candidates: semantic keys mapped to possible dataset column names.
# Used to resolve the actual column names from the dataset schema.
FIELD_CANDIDATES: Dict[str, List[str]] = {
    "date": [
        "dateparution",
        "date_publication",
        "datepublication",
        "date",
        "publication_date",
        "record_timestamp",
    ],
    "title": ["intitule", "objet", "titre", "title", "intitulé", "objet_du_marche"],
    "url": [
        "url",
        "lien",
        "pageurl",
        "url_avis",
        "url_detail_avis",
        "avis_url",
        "link",
        "permalink",
        "permalien",
        "permalink_avis",
        "permalien_avis",
    ],
    "cpv": ["cpv", "cpvs", "code_cpv", "codes_cpv", "cpv_principal"],
    "dept": [
        "lieu_execution_code",
        "code_departement",
        "departement",
        "code_dept",
        "dept",
        "code_insee_departement",
    ],
    "buyer": ["acheteur", "acheteur_nom", "acheteur_name", "organisme", "acheteur.principal"],
    "description": ["description", "objet", "objet_detail", "objetcomplet", "texte"],
    "ref": [
        "reference",
        "référence",
        "numero",
        "num_avis",
        "identifiant",
        "no_avis",
        "num_annonce",
        "id",
        "recordid",
    ],
    "serviceCategory": [
        "categorie_services",
        "categorie_service",
        "categorie",
        "categorie_de_services",
        "category_service",
        "service_category",
    ],
    "nature": [
        "nature",
        "nature_avis",
        "type_avis",
        "type",
        "etat",
        "etat_avis",
    ],
    # Date limite de réception des offres
    "deadline": [
        "date_limite_remise_offres",
        "date_limite_de_reception_des_offres",
        "date_limite_offres",
        "date_reception_offres",
        "date_reponse",
        "date_limite",
        "date_depot_offre",
        "deadline",
    ],
    # Nom et adresse officiels de l'organisme acheteur (texte long)
    "buyerAddress": [
        "nom_et_adresse_officiels_de_l_organisme_acheteur",
        "nom_et_adresse_officiels_de_lorganisme_acheteur",
        "acheteur_adresse",
        "adresse_acheteur",
        "organisme_adresse",
        "acheteur_coordonnees",
        "coordonnees_acheteur",
        "adresse",
    ],
    # Budget / montant estimé
    "budget": [
        "montant",
        "montant_estime",
        "valeur",
        "budget",
        "amount",
    ],
    # Procédure / type de procédure
    "procedure": [
        "procedure",
        "type_procedure",
        "mode_de_passation",
        "procedure_type",
    ],
    # Type de marché (service/fourniture/travaux)
    "marketType": [
        "type_marche",
        "type_du_marche",
        "type",
    ],
    # Lieu d'exécution (ville/département/pays)
    "place": [
        "lieu_execution",
        "lieu_execution_nom",
        "lieu_dexecution",
        "localisation",
        "ville",
        "commune",
    ],
}


@dataclass
class ResolvedFields:
    """Represents resolved dataset column names.

    Attributes
    - date: Column name for publication date.
    - title: Column name for title/intitulé.
    - url: Column name for URL/permalink.
    - cpv: Column name for CPV (may be string or array in records).
    - dept: Column name for department code.
    - buyer: Column name for buyer (acheteur).
    - description: Column name for description/object.
    - ref: Column name for reference or record id.
    - serviceCategory: Column for service category (for training use case).

    Exceptions
    - None directly; if a field cannot be resolved, a safe fallback is used.
    """

    date: str = "record_timestamp"
    title: str = "title"
    url: str = "permalink"
    cpv: str = "cpv"
    dept: str = "departement"
    buyer: str = "acheteur"
    description: str = "description"
    ref: str = "id"
    serviceCategory: str = "categorie_services"
    nature: str = "nature"
    deadline: str = "date_limite_remise_offres"
    buyerAddress: str = "nom_et_adresse_officiels_de_l_organisme_acheteur"
    budget: str = "montant"
    procedure: str = "procedure"
    marketType: str = "type_marche"
    place: str = "lieu_execution"


# Simple in-memory schema cache to avoid hitting the ODS catalog on each request.
_SCHEMA_CACHE: Dict[str, Any] = {"value": None, "ts": 0.0}
_SCHEMA_TTL_SECONDS: int = 600  # 10 minutes


def _http_get_json(url: str) -> Any:
    # Utilité: point central pour tous les GET JSON réseau (schema, records...).
    # Entrée: `url` entièrement construite.
    # Sortie: objet Python (dict/list) parse du JSON retourné.
    # Erreurs: URLError/HTTPError/JSONDecodeError; fallback SSL possible si activé.
    """Perform an HTTP GET and parse a JSON response.

    Parameters
    - url: Absolute URL to fetch.

    Returns
    - Parsed JSON object (typically dict) on success.

    Exceptions
    - URLError/HTTPError: Network issue, DNS failure, TLS error, HTTP 4xx/5xx.
    - json.JSONDecodeError: Response is not valid JSON.

    Likely error causes
    - Wrong `ODS_BASE` or `DATASET_ID`.
    - Portal requires API key and `ODS_APIKEY` not provided.
    - Temporary outage or rate limiting by the portal.
    """
    req = Request(
        url,
        headers={
            "User-Agent": "Minimal-BOAMP-Client/1.0",
            "Accept": "application/json",
            "Connection": "close",
        },
    )
    # Build an SSL context using certifi when available, unless insecure is allowed
    allow_insecure = os.environ.get("ALLOW_INSECURE_SSL", "0").lower() in {"1", "true", "yes", "on"}
    # Allow overriding CA bundle via common env vars
    ca_file = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE")
    ca_path = os.environ.get("SSL_CERT_DIR")

    local_ca_guess = os.path.join(os.path.dirname(__file__), "local_ca.pem")
    local_ca_file = os.environ.get("LOCAL_CA_FILE") or (local_ca_guess if os.path.exists(local_ca_guess) else None)

    if allow_insecure:
        context = ssl._create_unverified_context()  # nosec - user-controlled opt-in
    else:
        try:
            if ca_file or ca_path:
                context = ssl.create_default_context(cafile=ca_file, capath=ca_path)
            elif certifi is not None:
                context = ssl.create_default_context(cafile=certifi.where())
            else:
                context = ssl.create_default_context()
            # If a local/company CA certificate is provided, add it
            if local_ca_file:
                try:
                    context.load_verify_locations(cafile=local_ca_file)
                except Exception:
                    pass
        except Exception:
            context = ssl.create_default_context()
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS, context=context) as resp:
            data = resp.read()
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        # Auto-fallback to insecure SSL once if verification fails
        msg = str(e)
        if (not allow_insecure) and AUTO_FALLBACK_INSECURE_SSL and (
            "CERTIFICATE_VERIFY_FAILED" in repr(e) or "certificate verify failed" in msg.lower()
        ):
            insecure_ctx = ssl._create_unverified_context()  # nosec - explicit fallback
            with urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS, context=insecure_ctx) as resp:
                data = resp.read()
            return json.loads(data.decode("utf-8"))
        raise


def fetch_dataset_schema(force_refresh: bool = False) -> Dict[str, Any]:
    # Utilité: obtenir la liste des champs du dataset cible pour résoudre les noms.
    # Entrée: `force_refresh` pour ignorer le cache schéma.
    # Sortie: dict conforme à l'API ODS "dataset metadata".
    # Erreurs: celles de `_http_get_json` (réseau/HTTP/JSON).
    """Fetch the ODS dataset schema, with basic in-memory caching.

    Parameters
    - force_refresh: If True, skip cache and re-fetch the schema.

    Returns
    - Dict with dataset schema as returned by `${ODS_BASE}/api/v2/catalog/datasets/${DATASET_ID}`.

    Exceptions
    - Propagates network/HTTP/JSON errors from `_http_get_json`.

    Likely error causes
    - Network issues, wrong portal base, missing dataset, missing/invalid API key.
    """
    now = time.time()
    cached = _SCHEMA_CACHE.get("value")
    if not force_refresh and cached and (now - _SCHEMA_CACHE.get("ts", 0)) < _SCHEMA_TTL_SECONDS:
        return cached  # type: ignore[return-value]

    base = ODS_BASE.rstrip("/")
    url = f"{base}/api/v2/catalog/datasets/{DATASET_ID}"
    if ODS_APIKEY:
        url = f"{url}?{urlencode({'apikey': ODS_APIKEY})}"
    schema = _http_get_json(url)
    _SCHEMA_CACHE["value"] = schema
    _SCHEMA_CACHE["ts"] = now
    return schema


def resolve_fields(schema: Dict[str, Any]) -> ResolvedFields:
    # Utilité: cartographier des clés sémantiques (date, url, cpv...) vers les
    # noms effectifs présents dans le dataset du portail courant.
    # Entrée: `schema` JSON.
    # Sortie: instance `ResolvedFields` avec noms de colonnes finalisés.
    """Resolve dataset column names using `FIELD_CANDIDATES`.

    Parameters
    - schema: Dict obtained from `fetch_dataset_schema`.

    Returns
    - `ResolvedFields` with best-effort column names found in the dataset.

    Exceptions
    - None. If expected structures are missing, default fallbacks are used.

    Likely error causes
    - Schema shape differs from the expected ODS catalog response. In practice,
      we stick to safe defaults if fields cannot be discovered.
    """
    names: List[str] = []
    try:
        names = [f.get("name", "") for f in (schema.get("dataset", {}).get("fields", []) or [])]
    except Exception:
        names = []

    def pick(candidates: Iterable[str], fallback: str) -> str:
        for c in candidates:
            if c in names:
                return c
        return fallback

    return ResolvedFields(
        date=pick(FIELD_CANDIDATES["date"], "record_timestamp"),
        title=pick(FIELD_CANDIDATES["title"], "title"),
        url=pick(FIELD_CANDIDATES["url"], "permalink"),
        cpv=pick(FIELD_CANDIDATES["cpv"], "cpv"),
        dept=pick(FIELD_CANDIDATES["dept"], "departement"),
        buyer=pick(FIELD_CANDIDATES["buyer"], "acheteur"),
        description=pick(FIELD_CANDIDATES["description"], "description"),
        ref=pick(FIELD_CANDIDATES["ref"], "id"),
        serviceCategory=pick(FIELD_CANDIDATES["serviceCategory"], "categorie_services"),
        nature=pick(FIELD_CANDIDATES["nature"], "nature"),
        deadline=pick(FIELD_CANDIDATES["deadline"], "date_limite_remise_offres"),
        buyerAddress=pick(FIELD_CANDIDATES["buyerAddress"], "nom_et_adresse_officiels_de_l_organisme_acheteur"),
        budget=pick(FIELD_CANDIDATES["budget"], "montant"),
        procedure=pick(FIELD_CANDIDATES["procedure"], "procedure"),
        marketType=pick(FIELD_CANDIDATES["marketType"], "type_marche"),
        place=pick(FIELD_CANDIDATES["place"], "lieu_execution"),
    )


def _safe_like_fragment(field: str, value: str) -> str:
    """Return a SQL-like safe fragment for Explore `where` using LIKE.

    Parameters
    - field: Dataset field name to target.
    - value: User-provided search value.

    Returns
    - A fragment like `string(field) LIKE '%escaped%'` where single quotes in
      `value` are doubled to avoid breaking the expression.

    Exceptions
    - None. All inputs coerced to string; quotes are safely doubled.

    Likely error causes
    - None for the function. Upstream issues: field not present in dataset.
    """
    v = str(value).replace("'", "''")
    return f"string({field}) LIKE '%{v}%'"


def build_explore_url(
    *,
    keywords: str,
    cpv_prefix: str,
    dept_codes: List[str],
    buyer: Optional[str],
    service_category_equals: Optional[str],
    cpv_whitelist: Optional[List[str]],
    nature_in: Optional[List[str]],
    sort: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    page: int,
    page_size: int,
    fields: ResolvedFields,
) -> str:
    # Utilité: assembler les paramètres Explore v2.1 (q, where, tri, pagination).
    # Sortie: URL prête à être appelée via `_http_get_json`.
    # Attention: la validité des champs/WHERE dépend du schéma réel du dataset.
    """Build an Explore v2.1 query URL.

    Parameters
    - keywords: Free text used in `q` parameter (can be empty).
    - cpv_prefix: Optional CPV prefix; expands to a broad LIKE on `fields.cpv`.
    - dept_codes: List of department codes to filter with `IN (...)`.
    - buyer: Optional buyer name to filter via LIKE.
    - service_category_equals: Optional exact match on service category field.
    - cpv_whitelist: Optional list of CPV codes enforced via ORed LIKEs.
    - date_from/date_to: Optional ISO dates (YYYY-MM-DD) bounds on `fields.date`.
    - page/page_size: Pagination controls converted to `offset`/`limit`.
    - fields: ResolvedFields indicating actual dataset column names.

    Returns
    - Absolute Explore v2.1 URL with encoded query parameters.

    Exceptions
    - None. String building only.

    Likely error causes
    - Using a field that does not exist in the dataset may produce 4xx from ODS.
    """
    params: List[Tuple[str, str]] = []
    if keywords and keywords.strip():
        params.append(("q", keywords.strip()))

    where: List[str] = []

    # CPV whitelist: build (string(cpv) LIKE '%...%' OR ...)
    if cpv_whitelist:
        parts = [
            _safe_like_fragment(fields.cpv or "cpv", c)
            for c in cpv_whitelist
            if str(c).strip()
        ]
        if parts:
            where.append("(" + " OR ".join(parts) + ")")

    # CPV prefix: loose match on cpv field
    if cpv_prefix:
        prefix = str(cpv_prefix).replace("'", "''")
        where.append(
            f"(string({fields.cpv or 'cpv'}) LIKE '{prefix}%' OR string({fields.cpv or 'cpv'}) LIKE '%{prefix}%')"
        )

    # Departments IN (...)
    if dept_codes:
        in_list = ",".join([f"'{c}'" for c in dept_codes])
        where.append(f"({fields.dept or 'departement'} IN ({in_list}))")

    # Buyer LIKE '%...%'
    if buyer and buyer.strip():
        where.append(_safe_like_fragment(fields.buyer or "acheteur", buyer))

    # Service category equality (for training use case)
    if service_category_equals not in (None, ""):
        cat_val = str(service_category_equals).replace("'", "''")
        where.append(f"{fields.serviceCategory or 'categorie_services'} = '{cat_val}'")

    # Nature IN ('AppelOffre','Attribution') if provided
    if nature_in:
        values = [f"'{str(v).replace("'", "''")}'" for v in nature_in if str(v).strip()]
        if values:
            where.append(f"string({fields.nature or 'nature'}) IN ({','.join(values)})")

    # Date range
    date_field = fields.date or "record_timestamp"
    if date_from:
        where.append(f"{date_field} >= '{date_from}'")
    if date_to:
        where.append(f"{date_field} <= '{date_to}'")

    if where:
        params.append(("where", " AND ".join(where)))

    # Order newest first
    # Sorting
    if sort == "deadline" and (fields.deadline or ""):
        params.append(("order_by", f"-{fields.deadline}"))
    elif sort == "relevance" and (keywords and keywords.strip()):
        params.append(("order_by", "relevance"))
    else:
        params.append(("order_by", f"-{date_field}"))
    params.append(("limit", str(page_size)))
    params.append(("offset", str((page - 1) * page_size)))

    if ODS_APIKEY:
        params.append(("apikey", ODS_APIKEY))

    base = ODS_BASE.rstrip("/")
    query = urlencode(params)
    return f"{base}/api/explore/v2.1/catalog/datasets/{DATASET_ID}/records?{query}"


def build_records_v1_url(
    *,
    q: Optional[str],
    dept_codes: List[str],
    buyer: Optional[str],
    cpv_whitelist: Optional[List[str]],
    service_category_equals: Optional[str],
    page: int,
    page_size: int,
    fields: ResolvedFields,
) -> str:
    # Utilité: fallback plus permissif (refine.*) quand Explore rejette WHERE.
    # Limitations: pas de `order_by` avancé ni de WHERE complexes.
    """Build a fallback Records v1 API URL with refine.* parameters.

    Parameters
    - q: Optional text search.
    - dept_codes/buyer/cpv_whitelist/service_category_equals: Refinement filters.
    - page/page_size: Pagination.
    - fields: Resolved column names.

    Returns
    - Absolute Records v1 URL with encoded search/refine parameters.

    Exceptions
    - None. String building only.
    """
    params: List[Tuple[str, str]] = [("dataset", DATASET_ID), ("rows", str(page_size)), ("start", str((page - 1) * page_size))]
    if q:
        params.append(("q", q))

    # cpv whitelist: multiple refine.cpv=value
    if cpv_whitelist:
        for code in cpv_whitelist:
            params.append((f"refine.{fields.cpv or 'cpv'}", str(code)))

    if service_category_equals not in (None, ""):
        params.append((f"refine.{fields.serviceCategory or 'categorie_services'}", str(service_category_equals)))

    if dept_codes:
        for d in dept_codes:
            params.append((f"refine.{fields.dept or 'code_departement'}", d))

    if buyer:
        params.append((f"refine.{fields.buyer or 'acheteur'}", buyer))

    if ODS_APIKEY:
        params.append(("apikey", ODS_APIKEY))

    base = ODS_BASE.rstrip("/")
    return f"{base}/api/records/1.0/search/?{urlencode(params)}"


def _cache_get(key: str) -> Optional[Tuple[List[Dict[str, Any]], Optional[int], str, ResolvedFields]]:
    entry = _RESULTS_CACHE.get(key)
    if not entry:
        return None
    if (time.time() - entry.get("ts", 0)) > RESULTS_CACHE_TTL_SECONDS:
        _RESULTS_CACHE.pop(key, None)
        return None
    return entry.get("value")  # type: ignore[return-value]


def _cache_set(key: str, value: Tuple[List[Dict[str, Any]], Optional[int], str, ResolvedFields]) -> None:
    _RESULTS_CACHE[key] = {"value": value, "ts": time.time()}


def _try_explore(
    *,
    q: str,
    cpv_prefix: str,
    dept_codes: List[str],
    buyer: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    nature_in: Optional[List[str]],
    sort: Optional[str],
    use_training: bool,
    page: int,
    page_size: int,
    fields: ResolvedFields,
) -> Tuple[List[Dict[str, Any]], Optional[int], str, ResolvedFields]:
    # Utilité: exécuter l'appel Explore et renvoyer un tuple standardisé.
    # Erreurs: propage celles de `_http_get_json` (réseau/HTTP/JSON).
    cpv_whitelist = TRAINING_CPV_WHITELIST if use_training else None
    service_cat = str(TRAINING_SERVICE_CATEGORY) if use_training else None
    explore_url = build_explore_url(
        keywords=q,
        cpv_prefix=cpv_prefix,
        dept_codes=dept_codes,
        buyer=buyer,
        service_category_equals=service_cat,
        cpv_whitelist=cpv_whitelist,
        nature_in=nature_in,
        sort=None,  # provided by perform_search
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
        fields=fields,
    )
    data = _http_get_json(explore_url)
    records = list(data.get("results") or [])
    total = data.get("total_count")
    return records, (int(total) if isinstance(total, int) else total), explore_url, fields


def _try_records_v1(
    *,
    q: str,
    dept_codes: List[str],
    buyer: Optional[str],
    use_training: bool,
    page: int,
    page_size: int,
    fields: ResolvedFields,
) -> Tuple[List[Dict[str, Any]], Optional[int], str, ResolvedFields]:
    # Utilité: exécuter l'appel v1 (refine) et renvoyer tuple standardisé.
    cpv_whitelist = TRAINING_CPV_WHITELIST if use_training else None
    service_cat = str(TRAINING_SERVICE_CATEGORY) if use_training else None
    v1_url = build_records_v1_url(
        q=q or None,
        dept_codes=dept_codes,
        buyer=buyer,
        cpv_whitelist=cpv_whitelist,
        service_category_equals=service_cat,
        page=page,
        page_size=page_size,
        fields=fields,
    )
    data = _http_get_json(v1_url)
    records = list(data.get("records") or [])
    total = data.get("nhits")
    return records, (int(total) if isinstance(total, int) else total), v1_url, fields


def perform_search(
    *,
    q: str,
    cpv_prefix: str,
    dept_codes: List[str],
    buyer: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    nature_in: Optional[List[str]],
    use_training: bool,
    page: int,
    page_size: int,
    sort: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[int], str, ResolvedFields]:
    # Utilité: orchestrer la recherche avec cache + stratégie Explore/v1.
    # Entrées principales: `q`, `dept_codes`, `buyer`, bornes de dates, `nature_in`,
    # pagination et tri.
    # Sortie: (records JSON, total, url de debug, champs résolus).
    # Erreurs: propage les erreurs réseau après fallback.
    """Execute search via Explore v2.1 with a fallback to Records v1.

    Parameters
    - q: Final composed keywords (may be empty). Already assembled from
         manual input + keyword buckets + training terms.
    - cpv_prefix: Optional CPV prefix.
    - dept_codes: Selected department codes.
    - buyer: Optional buyer name.
    - date_from/date_to: Optional ISO date bounds (YYYY-MM-DD).
    - use_training: If True, enforce service category and CPV whitelist.
    - page/page_size: Pagination controls.

    Returns
    - (records, total_count, debug_url, fields)
      - records: List of record dicts as returned by ODS v2.1 or transformed v1.
      - total_count: Optional total count; None if not provided by API.
      - debug_url: The URL actually requested against ODS (useful for debugging).
      - fields: ResolvedFields used for this query.

    Exceptions
    - Propagates network/HTTP/JSON errors from `_http_get_json` only after the
      fallback has been attempted. If both fail, the last exception bubbles up.

    Likely error causes
    - Explore `where` clause not accepted by some portals (4xx), triggering the
      fallback path. If fallback also fails, double-check fields, dataset, key.
    """
    schema = fetch_dataset_schema(force_refresh=False)
    fields = resolve_fields(schema)

    # Cache key: include base, dataset, and all filters influencing results
    cache_key = json.dumps(
        {
            "base": ODS_BASE,
            "dataset": DATASET_ID,
            "q": q,
            "cpv_prefix": cpv_prefix,
            "dept_codes": sorted(dept_codes),
            "buyer": buyer,
            "date_from": date_from,
            "date_to": date_to,
            "use_training": use_training,
            "nature_in": nature_in or [],
            "page": page,
            "page_size": page_size,
            "fields": fields.__dict__,
            "sort": sort or "",
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    cached = _cache_get(cache_key)
    if cached:
        return cached

    if PREFER_EXPLORE:
        try:
            result = _try_explore(
                q=q,
                cpv_prefix=cpv_prefix,
                dept_codes=dept_codes,
                buyer=buyer,
                date_from=date_from,
                date_to=date_to,
                nature_in=nature_in,
                sort=sort,
                use_training=use_training,
                page=page,
                page_size=page_size,
                fields=fields,
            )
            _cache_set(cache_key, result)
            return result
        except HTTPError as he:
            # Only fallback on client-side errors (400-499) where WHERE may be rejected
            if 400 <= getattr(he, "code", 0) <= 499:
                result = _try_records_v1(
                    q=q,
                    dept_codes=dept_codes,
                    buyer=buyer,
                    use_training=use_training,
                    page=page,
                    page_size=page_size,
                    fields=fields,
                )
                _cache_set(cache_key, result)
                return result
            raise
        except (URLError, json.JSONDecodeError):
            # Network/parse error -> try v1
            result = _try_records_v1(
                q=q,
                dept_codes=dept_codes,
                buyer=buyer,
                use_training=use_training,
                page=page,
                page_size=page_size,
                fields=fields,
            )
            _cache_set(cache_key, result)
            return result
    # Prefer v1 path
    try:
        result = _try_records_v1(
            q=q,
            dept_codes=dept_codes,
            buyer=buyer,
            use_training=use_training,
            page=page,
            page_size=page_size,
            fields=fields,
        )
        _cache_set(cache_key, result)
        return result
    except (HTTPError, URLError, json.JSONDecodeError):
        result = _try_explore(
            q=q,
            cpv_prefix=cpv_prefix,
            dept_codes=dept_codes,
            buyer=buyer,
            date_from=date_from,
            date_to=date_to,
            nature_in=nature_in,
            sort=sort,
            use_training=use_training,
            page=page,
            page_size=page_size,
            fields=fields,
        )
        _cache_set(cache_key, result)
        return result


def _compose_keywords(manual: str, selected_buckets: List[str], use_training: bool) -> str:
    # Utilité: composer le plein texte depuis mots saisis, buckets, et formation.
    """Compose the final `q` text query.

    Parameters
    - manual: Raw user-entered keywords (can be empty).
    - selected_buckets: Names of the keyword buckets selected by the user.
    - use_training: If True, append training terms.

    Returns
    - String containing an OR-composed expression, e.g. 'ux OR "formation professionnelle"'.

    Exceptions
    - None.

    Likely error causes
    - None: purely deterministic string composition.
    """
    bucket_terms: List[str] = []
    for name in selected_buckets:
        bucket_terms.extend(KEYWORD_BUCKETS.get(name, []))
    bucket_expr = " OR ".join(t for t in bucket_terms if str(t).strip())
    training_expr = " OR ".join(TRAINING_TERMS) if use_training else ""
    manual_expr = manual or ""
    parts = [p for p in [manual_expr, bucket_expr, training_expr] if p and p.strip()]
    return " OR ".join(parts)


def _parse_csv_list(value: Optional[str]) -> List[str]:
    # Utilité: transformer des listes CSV en liste Python en éliminant les vides.
    """Parse a comma-separated list into a list of non-empty trimmed strings.

    Parameters
    - value: Raw string (e.g., "75,92,93") or None.

    Returns
    - List of non-empty trimmed strings. Returns [] if input is None/empty.
    """
    if not value:
        return []
    return [s.strip() for s in value.split(",") if s.strip()]


def _normalize_record_url(base: str, dataset_id: str, raw_url: Optional[str], ref: Optional[str], record_id: Optional[str]) -> str:
    # Utilité: garantir un lien consultable: fiche dataset ou boamp.fr/detail.
    # Entrées: `raw_url` (brut du champ), `ref` (référence d'avis), `record_id`.
    # Sortie: URL absolue stable.
    """Normalize links to point to a stable detail page.

    Rules
    - If `raw_url` is absent and portal host is boamp.fr and `ref` exists, use
      `${base}/avis/detail/${ref}`. Otherwise, fall back to dataset record page.
    - If `raw_url` points to the portal home or "entreprise-accueil", favor the
      dataset record page, unless boamp.fr + ref is available.

    Parameters
    - base: ODS_BASE without trailing slash.
    - dataset_id: Dataset slug.
    - raw_url: URL found in record fields (may be relative/absolute/None).
    - ref: Reference string if available.
    - record_id: ODS internal record id.

    Returns
    - Absolute URL as a string.
    """
    base_no_slash = base.rstrip("/")
    host = ""
    try:
        host = urlparse(base_no_slash).hostname or ""
    except Exception:
        host = ""
    dataset_record = (
        f"{base_no_slash}/explore/dataset/{dataset_id}/record/?id={urlencode({'id': str(record_id or '')}).split('=')[1]}"
        if record_id
        else base_no_slash
    )
    is_boamp_portal = host.endswith("boamp.fr")

    if not raw_url:
        if is_boamp_portal and ref:
            return f"{base_no_slash}/avis/detail/{ref}"
        return dataset_record

    try:
        # `urljoin` resolves relative URLs against the base
        href = urljoin(base_no_slash + "/", raw_url)
        if href == f"{base_no_slash}/" or "/pages/entreprise-accueil" in href:
            if is_boamp_portal and ref:
                return f"{base_no_slash}/avis/detail/{ref}"
            return dataset_record
        return href
    except Exception:
        return (f"{base_no_slash}/avis/detail/{ref}" if is_boamp_portal and ref else dataset_record)


# --------------------------------------------------------------------------------------
# Flask app and HTTP routes
# --------------------------------------------------------------------------------------

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "..", "Front-end", "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "..", "Front-end", "static"),
    static_url_path="/static",
)
# Remarque: cette app sert les templates du dossier Front-end/templates
# et les assets statiques (CSS) du dossier Front-end/static.


@app.get("/search")
def search_page():
    # Utilité: page SSR (optionnelle) listant les résultats côté serveur.
    """Render the advanced search page with filters and results.

    Query parameters (all optional; names match form input names)
    - keywords: Free-text keywords.
    - cpvPrefix: CPV prefix to search.
    - deptCodes: Comma-separated department codes (e.g., "75,92,93").
    - buyer: Buyer (acheteur) text to filter.
    - dateFrom/dateTo: ISO dates (YYYY-MM-DD) for inclusive range.
    - useKeywords/useCpv/useDept/useBuyer/useDate/useTraining: "on" if enabled.
    - selectedBucket: Repeated params for each selected bucket.
    - page/pageSize: Pagination controls (default: 1/20).
    - refreshSchema: If "1", force-refresh the dataset schema cache.

    Returns
    - HTML page rendered from `Front-end/templates/index.html`.

    Exceptions
    - Any exception during data fetching is captured and displayed as an
      error banner in the template instead of raising an HTTP error.
    """
    # Read basic string inputs
    keywords: str = request.args.get("keywords", "")
    cpv_prefix: str = request.args.get("cpvPrefix", "")
    buyer: Optional[str] = request.args.get("buyer") or None
    date_from: Optional[str] = request.args.get("dateFrom") or None
    date_to: Optional[str] = request.args.get("dateTo") or None
    # Departments can arrive as repeated inputs (?deptCodes=75&deptCodes=92) or comma-separated
    dept_codes_raw: List[str] = request.args.getlist("deptCodes")
    if dept_codes_raw:
        dept_codes = [s.strip() for s in dept_codes_raw if s.strip()]
    else:
        dept_codes = _parse_csv_list(request.args.get("deptCodes"))

    # Boolean toggles (HTML checkbox returns "on" when checked)
    use_keywords = request.args.get("useKeywords") == "on"
    use_cpv = request.args.get("useCpv") == "on"
    use_dept = request.args.get("useDept") == "on"
    use_buyer = request.args.get("useBuyer") == "on"
    # Période active par défaut si non spécifiée
    if "useDate" in request.args:
        use_date = _get_bool(request.args.get("useDate"))
    else:
        use_date = True
    # Default to True when no parameter is provided, otherwise respect the flag
    if "useTraining" in request.args:
        use_training = _get_bool(request.args.get("useTraining"))
    else:
        use_training = True

    # Buckets: repeated query parameters like ?selectedBucket=UX/UI&selectedBucket=Data%20/%20BI
    selected_buckets: List[str] = request.args.getlist("selectedBucket")

    # Pagination
    try:
        page = max(1, int(request.args.get("page", "1") or "1"))
    except ValueError:
        page = 1
    try:
        page_size = max(1, min(100, int(request.args.get("pageSize", "20") or "20")))
    except ValueError:
        page_size = 20

    # Optional schema refresh (useful if dataset schema changes)
    if request.args.get("refreshSchema") == "1":
        _SCHEMA_CACHE["ts"] = 0
        try:
            fetch_dataset_schema(force_refresh=True)
        except Exception:
            # Ignore refresh errors here; will surface during search below if any
            pass

    # Compléter une période par défaut si activée mais sans dates fournies
    if use_date and (not date_from or not date_to):
        try:
            from datetime import date, timedelta
            if not date_from:
                date_from = (date.today() - timedelta(days=90)).isoformat()
            if not date_to:
                date_to = (date.today() + timedelta(days=365)).isoformat()
        except Exception:
            pass

    # Compose final text query: only include parts if toggled on
    final_q = _compose_keywords(
        manual=(keywords if use_keywords else ""),
        selected_buckets=selected_buckets,
        use_training=use_training,
    )

    # Build filters according to toggles
    effective_cpv_prefix = cpv_prefix if use_cpv and cpv_prefix.strip() else ""
    effective_dept_codes = dept_codes if use_dept else []
    effective_buyer = (buyer if (use_buyer and buyer and buyer.strip()) else None)
    effective_date_from = date_from if use_date and date_from else None
    effective_date_to = date_to if use_date and date_to else None

    error: Optional[str] = None
    debug_url: str = ""
    fields: ResolvedFields = ResolvedFields()
    records: List[Dict[str, Any]] = []
    total: Optional[int] = None

    try:
        records, total, debug_url, fields = perform_search(
            q=final_q,
            cpv_prefix=effective_cpv_prefix,
            dept_codes=effective_dept_codes,
            buyer=effective_buyer,
            date_from=effective_date_from,
            date_to=effective_date_to,
            use_training=use_training,
            page=page,
            page_size=page_size,
        )
    except Exception as e:  # noqa: BLE001 — intentionally broad to show message in UI
        error = str(e)

    # Compute available buyers list from currently loaded records for the select control
    buyers: List[str] = []
    try:
        seen = set()
        for r in records:
            f = (r.get("fields") or {}) if "fields" in r else r
            b = f.get(fields.buyer)
            if b is None:
                continue
            s = str(b)
            if s and s not in seen:
                seen.add(s)
                buyers.append(s)
        buyers.sort(key=lambda s: s.lower())
    except Exception:
        buyers = []

    # Prepare mapped records for template convenience
    base = ODS_BASE.rstrip("/")
    mapped: List[Dict[str, Any]] = []
    for r in records:
        f = (r.get("fields") or {}) if "fields" in r else r
        title = f.get(fields.title) or f.get("objet") or f.get("titre") or f"Avis #{r.get('id') or r.get('recordid')}"
        raw_url = (
            f.get(fields.url)
            or f.get("permalink")
            or f.get("url_avis")
            or f.get("pageurl")
            or f.get("lien")
            or f.get("link")
            or f.get("url")
            or f.get("permalien")
        )
        ref = f.get(fields.ref) or r.get("id") or r.get("recordid")
        href = _normalize_record_url(base, DATASET_ID, raw_url, ref, r.get("id") or r.get("recordid"))
        date_str = f.get(fields.date) or f.get("record_timestamp")
        date_iso = str(date_str)[:10] if date_str else None
        deadline_str = f.get(fields.deadline)
        deadline_iso = (str(deadline_str)[:10] if deadline_str else None)
        buyer_val = f.get(fields.buyer)
        buyer_address = f.get(fields.buyerAddress)
        dept_val = f.get(fields.dept)
        cpv_val = f.get(fields.cpv)
        description = f.get(fields.description)
        budget_val = f.get(fields.budget)
        procedure_val = f.get(fields.procedure)
        market_type_val = f.get(fields.marketType)
        place_val = f.get(fields.place)

        mapped.append(
            {
                "title": title,
                "href": href,
                "ref": ref,
                "date_iso": date_iso,
                "deadline_iso": deadline_iso,
                "buyer": buyer_val,
                "buyer_address": buyer_address,
                "dept": dept_val,
                "cpv": cpv_val,
                "description": description,
                "budget": budget_val,
                "procedure": procedure_val,
                "market_type": market_type_val,
                "place": place_val,
            }
        )

    # Total pages (if total is known)
    total_pages: int = 1
    if isinstance(total, int) and page_size > 0:
        total_pages = max(1, (total + page_size - 1) // page_size)

    return render_template(
        "index.html",
        # Data for results and pagination
        records=mapped,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        # Filters current state
        keywords=keywords,
        cpv_prefix=cpv_prefix,
        buyer=buyer or "",
        date_from=date_from or "",
        date_to=date_to or "",
        dept_codes=dept_codes,
        use_keywords=use_keywords,
        use_cpv=use_cpv,
        use_dept=use_dept,
        use_buyer=use_buyer,
        use_date=use_date,
        use_training=use_training,
        selected_buckets=selected_buckets,
        # Aux data
        available_buyers=buyers,
        idf_departements=IDF_DEPARTEMENTS,
        keyword_buckets=KEYWORD_BUCKETS,
        # Debug and errors
        debug_url=debug_url,
        error=error,
        ods_base=ODS_BASE,
        dataset_id=DATASET_ID,
    )


@app.get("/")
def index():
    # Utilité: page d'accueil principale (filtres + déclenchement recherche).
    """Render a simple landing page with a single CTA to fetch data.

    Returns
    - HTML page rendered from `Front-end/templates/home.html`.
    """
    return render_template(
        "home.html",
        ods_base=ODS_BASE,
        dataset_id=DATASET_ID,
    )


@app.get("/cpv")
def cpv_page():
    # Utilité: page informative listant les CPV de la formation.
    """Render a page listing the CPV codes and their meaning (formation subset).

    Returns
    - HTML page rendered from `Front-end/templates/cpv.html`.
    """
    return render_template("cpv.html", cpvs=CPV_CATALOG, ods_base=ODS_BASE, dataset_id=DATASET_ID)


def _export_rows_from_json_items(items: List[Dict[str, Any]]) -> List[List[str]]:
    # Utilité: centraliser la construction des lignes pour CSV/Excel.
    rows: List[List[str]] = [["Intitule", "Lien", "Date_limite", "Nom_Adresse_Acheteur"]]
    for it in items:
        rows.append([
            str(it.get("title", "")),
            str(it.get("href", "")),
            str(it.get("deadline_iso", "")),
            str(it.get("buyer_address") or it.get("buyer") or ""),
        ])
    return rows


@app.post("/export/csv")
def export_csv():
    # Utilité: exemple d'export côté serveur (non utilisé par défaut dans l'UI).
    """Export selected items to CSV (server-side), Excel-compatible.

    Body (JSON): { items: [ {title, href, deadline_iso, buyer_address?, buyer?}, ... ] }
    Returns: text/csv attachment 'avis_selection.csv'
    """
    try:
        data = request.get_json(force=True, silent=False) or {}
        items = list(data.get("items") or [])
        rows = _export_rows_from_json_items(items)
        # Build CSV with semicolons and UTF-8 BOM for Excel
        import io, csv
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=';')
        for r in rows:
            writer.writerow(r)
        csv_bytes = ('\ufeff' + buf.getvalue()).encode('utf-8')
        return Response(csv_bytes, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="avis_selection.csv"'})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 400


@app.post("/export/excel")
def export_excel_csv():
    # Utilité: variante mimetype Excel (ouverture directe dans Excel).
    """Export to an Excel-compatible CSV (same content, different mimetype/filename)."""
    try:
        data = request.get_json(force=True, silent=False) or {}
        items = list(data.get("items") or [])
        rows = _export_rows_from_json_items(items)
        import io, csv
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=';')
        for r in rows:
            writer.writerow(r)
        csv_bytes = ('\ufeff' + buf.getvalue()).encode('utf-8')
        return Response(csv_bytes, mimetype='application/vnd.ms-excel', headers={'Content-Disposition': 'attachment; filename="avis_selection.xls"'})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 400


@app.post("/export/ics")
def export_ics():
    # Utilité: générer un calendrier ICS d'échéances (deadlines) sélectionnées.
    """Export deadlines to ICS calendar events.

    Body (JSON): { items: [ {title, href, deadline_iso, buyer_address?}, ... ] }
    """
    try:
        data = request.get_json(force=True, silent=False) or {}
        items = list(data.get("items") or [])
        from datetime import datetime
        def ics_datetime(d: Optional[str]) -> Optional[str]:
            if not d:
                return None
            try:
                # Assume YYYY-MM-DD (all-day event)
                dt = datetime.strptime(d, "%Y-%m-%d")
                return dt.strftime("%Y%m%d")
            except Exception:
                try:
                    dt = datetime.fromisoformat(d)
                    return dt.strftime("%Y%m%dT%H%M%SZ")
                except Exception:
                    return None

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//BOAMP Minimal//FR",
        ]
        for it in items:
            title = str(it.get("title", "Avis BOAMP"))
            url = str(it.get("href", ""))
            deadline = ics_datetime(it.get("deadline_iso") or it.get("date_iso"))
            buyer_addr = str(it.get("buyer_address") or "")
            desc = buyer_addr.replace("\n", " ")
            lines.append("BEGIN:VEVENT")
            lines.append(f"SUMMARY:{title}")
            if deadline and len(deadline) == 8:
                lines.append(f"DTSTART;VALUE=DATE:{deadline}")
                lines.append(f"DTEND;VALUE=DATE:{deadline}")
            elif deadline:
                lines.append(f"DTSTART:{deadline}")
            if url:
                lines.append(f"URL:{url}")
            if desc:
                lines.append(f"DESCRIPTION:{desc}")
            lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        content = "\r\n".join(lines).encode('utf-8')
        return Response(content, mimetype='text/calendar', headers={'Content-Disposition': 'attachment; filename="avis_selection.ics"'})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 400


@app.get("/api/explore-demo")
def api_explore_demo():
    """Call the exact Explore v2.1 endpoint shown in the official docs.

    Query params
    - limit: optional, default 20

    Returns (JSON)
    - { items: [...], total: number|null, debug_url: string }
    """
    try:
        try:
            limit = max(1, min(100, int(request.args.get("limit", "20") or "20")))
        except ValueError:
            limit = 20

        # Resolve fields to map records consistently
        schema = fetch_dataset_schema(force_refresh=False)
        fields = resolve_fields(schema)

        base = ODS_BASE.rstrip("/")
        params = [("limit", str(limit))]
        if ODS_APIKEY:
            params.append(("apikey", ODS_APIKEY))
        debug_url = f"{base}/api/explore/v2.1/catalog/datasets/{DATASET_ID}/records?{urlencode(params)}"

        data = _http_get_json(debug_url)
        results = list(data.get("results") or [])
        total = data.get("total_count")

        items = []
        for r in results:
            f = (r.get("fields") or {}) if "fields" in r else r
            title = (
                f.get(fields.title)
                or f.get("objet")
                or f.get("titre")
                or f.get("title")
                or f"Avis #{r.get('id') or r.get('recordid')}"
            )
            raw_url = (
                f.get(fields.url)
                or f.get("permalink")
                or f.get("url_avis")
                or f.get("pageurl")
                or f.get("lien")
                or f.get("link")
                or f.get("url")
                or f.get("permalien")
            )
            ref = f.get(fields.ref) or r.get("id") or r.get("recordid")
            href = _normalize_record_url(base, DATASET_ID, raw_url, ref, r.get("id") or r.get("recordid"))
            date_str = f.get(fields.date) or f.get("record_timestamp")
            date_iso = str(date_str)[:10] if date_str else None
            deadline_str = f.get(fields.deadline)
            deadline_iso = (str(deadline_str)[:10] if deadline_str else None)
            buyer_address = f.get(fields.buyerAddress)
            items.append(
                {
                    "title": title,
                    "href": href,
                    "ref": ref,
                    "date_iso": date_iso,
                    "buyer": f.get(fields.buyer),
                    "dept": f.get(fields.dept),
                    "cpv": f.get(fields.cpv),
                    "description": f.get(fields.description),
                    "deadline_iso": deadline_iso,
                    "buyer_address": buyer_address,
                    "budget": f.get(fields.budget),
                    "procedure": f.get(fields.procedure),
                    "market_type": f.get(fields.marketType),
                    "place": f.get(fields.place),
                }
            )

        return jsonify({"items": items, "total": total, "debug_url": debug_url})
    except Exception as e:  # noqa: BLE001
        return jsonify({"items": [], "total": None, "error": str(e)}), 200


def _get_bool(arg_value: Optional[str]) -> bool:
    """Interpret a query string boolean value.

    Accepts 'on', 'true', '1' as True (case-insensitive); otherwise False.
    """
    if not arg_value:
        return False
    return arg_value.lower() in {"on", "true", "1", "yes"}


@app.get("/api/search")
def api_search():
    """JSON API to fetch BOAMP results.

    Query parameters (optional)
    - q, cpvPrefix, deptCodes (repeat or comma-separated), buyer,
      dateFrom, dateTo, useTraining, page, pageSize

    Returns (JSON)
    - { items: [ {title, href, ref, date_iso, buyer, dept, cpv, description} ],
        total: number|null, debug_url: string }
    """
    q = request.args.get("q", "")
    cpv_prefix = request.args.get("cpvPrefix", "")
    buyer = request.args.get("buyer") or None
    date_from = request.args.get("dateFrom") or None
    date_to = request.args.get("dateTo") or None
    dept_codes_raw = request.args.getlist("deptCodes")
    if dept_codes_raw:
        dept_codes = [s.strip() for s in dept_codes_raw if s.strip()]
    else:
        dept_codes = _parse_csv_list(request.args.get("deptCodes"))

    # Defaults: last 90 days to today+365, page=1, size=20
    try:
        page = max(1, int(request.args.get("page", "1") or "1"))
    except ValueError:
        page = 1
    try:
        page_size = max(1, min(100, int(request.args.get("pageSize", "20") or "20")))
    except ValueError:
        page_size = 20

    # Default to True if parameter is missing (formation ON by default)
    if "useTraining" in request.args:
        use_training = _get_bool(request.args.get("useTraining"))
    else:
        use_training = True
    use_date_flag = _get_bool(request.args.get("useDate"))
    nature_list = request.args.getlist("nature")
    sort = request.args.get("sort") or None

    # If date filtering is enabled (or dates explicitly provided), ensure bounds
    if (use_date_flag or date_from or date_to):
        if not date_from:
            # last 90 days
            try:
                from datetime import date, timedelta
                date_from = (date.today() - timedelta(days=90)).isoformat()
            except Exception:
                date_from = None
        if not date_to:
            try:
                from datetime import date, timedelta
                date_to = (date.today() + timedelta(days=365)).isoformat()
            except Exception:
                date_to = None
    else:
        date_from = None
        date_to = None

    try:
        records, total, debug_url, fields = perform_search(
            q=q,
            cpv_prefix=cpv_prefix,
            dept_codes=dept_codes,
            buyer=buyer,
            date_from=date_from,
            date_to=date_to,
            nature_in=nature_list,
            use_training=use_training,
            page=page,
            page_size=page_size,
            sort=sort,
        )

        base = ODS_BASE.rstrip("/")
        items: List[Dict[str, Any]] = []
        for r in records:
            f = (r.get("fields") or {}) if "fields" in r else r
            title = (
                f.get(fields.title)
                or f.get("objet")
                or f.get("titre")
                or f.get("title")
                or f"Avis #{r.get('id') or r.get('recordid')}"
            )
            raw_url = (
                f.get(fields.url)
                or f.get("permalink")
                or f.get("url_avis")
                or f.get("pageurl")
                or f.get("lien")
                or f.get("link")
                or f.get("url")
                or f.get("permalien")
            )
            ref = f.get(fields.ref) or r.get("id") or r.get("recordid")
            href = _normalize_record_url(base, DATASET_ID, raw_url, ref, r.get("id") or r.get("recordid"))
            date_str = f.get(fields.date) or f.get("record_timestamp")
            date_iso = str(date_str)[:10] if date_str else None
            deadline_str = f.get(fields.deadline)
            deadline_iso = (str(deadline_str)[:10] if deadline_str else None)
            buyer_address = f.get(fields.buyerAddress)
            items.append(
                {
                    "title": title,
                    "href": href,
                    "ref": ref,
                    "date_iso": date_iso,
                    "buyer": f.get(fields.buyer),
                    "dept": f.get(fields.dept),
                    "cpv": f.get(fields.cpv),
                    "description": f.get(fields.description),
                    "deadline_iso": deadline_iso,
                    "buyer_address": buyer_address,
                }
            )
        return jsonify({"items": items, "total": total, "debug_url": debug_url})
    except Exception as e:  # noqa: BLE001
        # Return JSON with error information but avoid hard 500 to keep UI functional
        return jsonify({"items": [], "total": None, "error": str(e)}), 200


def create_app() -> Flask:
    """Factory for WSGI servers.

    Returns
    - Configured Flask application instance.

    Exceptions
    - None.
    """
    return app


if __name__ == "__main__":
    # Development entrypoint. In production, use a WSGI server (gunicorn/uwsgi)
    # and `create_app()`.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=True)
