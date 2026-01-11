# finder/services/osm.py
import os
import time
import random
import requests

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

DEFAULT_UA = "Nearify/1.0 (contact: noreplynearify@gmail.com)"
USER_AGENT = os.getenv("OSM_USER_AGENT", DEFAULT_UA)
CONTACT_EMAIL = os.getenv("OSM_CONTACT_EMAIL", "").strip()

_session = requests.Session()
_session.headers.update(
    {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "en",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
)

_geo_cache = {}
_rev_cache = {}


def _sleep():
    # Nominatim rate limits. Keep it gentle.
    time.sleep(1.05)


def geocode_location(query: str, *, timeout=15):
    """
    Returns: (lat, lon, display_name, error)
    """
    q = (query or "").strip()
    if not q:
        return None, None, "", "Empty location."

    key = q.lower()
    if key in _geo_cache:
        return _geo_cache[key]

    _sleep()

    params = {
        "q": q,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 1,
    }
    if CONTACT_EMAIL:
        params["email"] = CONTACT_EMAIL

    try:
        r = _session.get(NOMINATIM_SEARCH_URL, params=params, timeout=timeout)

        if r.status_code == 403:
            err = (
                "Geocoding blocked (403). Nominatim requires a proper User-Agent and contact.\n"
                "Set these in your .env:\n"
                'OSM_USER_AGENT="Nearify/1.0 (contact: you@example.com)"\n'
                'OSM_CONTACT_EMAIL="you@example.com"\n'
                "Then restart the server."
            )
            result = (None, None, "", err)
            _geo_cache[key] = result
            return result

        r.raise_for_status()
        data = r.json() or []
        if not data:
            result = (None, None, "", "No geocoding results for that location.")
            _geo_cache[key] = result
            return result

        item = data[0]
        lat = float(item["lat"])
        lon = float(item["lon"])
        display = item.get("display_name", q)

        result = (lat, lon, display, None)
        _geo_cache[key] = result
        return result

    except requests.RequestException as e:
        result = (None, None, "", f"Geocoding failed: {e}")
        _geo_cache[key] = result
        return result


def reverse_geocode(lat: float, lon: float, *, timeout=15):
    """
    Returns: (address, city, state, zip_code)
    """
    key = f"{lat:.5f},{lon:.5f}"
    if key in _rev_cache:
        return _rev_cache[key]

    _sleep()

    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "zoom": 18,
        "addressdetails": 1,
    }
    if CONTACT_EMAIL:
        params["email"] = CONTACT_EMAIL

    try:
        r = _session.get(NOMINATIM_REVERSE_URL, params=params, timeout=timeout)
        if r.status_code == 403:
            return ("", "", "", "")
        r.raise_for_status()
        data = r.json() or {}
        addr = data.get("address") or {}

        # Nominatim uses different keys depending on area
        city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("suburb") or ""
        state = addr.get("state") or ""
        zip_code = addr.get("postcode") or ""

        # build street address
        housenumber = addr.get("house_number") or ""
        road = addr.get("road") or ""
        address = (" ".join([housenumber, road])).strip()

        out = (address, city, state, zip_code)
        _rev_cache[key] = out
        return out
    except requests.RequestException:
        return ("", "", "", "")


def _shuffled_overpass_urls():
    urls = OVERPASS_URLS[:]
    random.shuffle(urls)
    return urls


def overpass_search(term: str, lat: float, lon: float, radius_m=8000, limit=40, timeout=20):
    """
    Returns list of normalized dicts:
      {name,address,city,state,zip_code,url,phone,lat,lon,osm_id}
    """
    term = (term or "").strip().lower()
    if not term:
        return []

    TAG_MAP = {
        "gas": [("amenity", "fuel")],
        "gas station": [("amenity", "fuel")],
        "fuel": [("amenity", "fuel")],

        "grocery": [("shop", "supermarket"), ("shop", "convenience"), ("shop", "grocery")],
        "supermarket": [("shop", "supermarket")],
        "convenience": [("shop", "convenience")],

        "salon": [("shop", "hairdresser"), ("shop", "beauty")],
        "barber": [("shop", "barber"), ("shop", "hairdresser")],

        "pizza": [("amenity", "restaurant"), ("amenity", "fast_food")],
        "restaurant": [("amenity", "restaurant")],
        "cafe": [("amenity", "cafe")],
        "coffee": [("amenity", "cafe")],

        "pharmacy": [("amenity", "pharmacy")],
        "hospital": [("amenity", "hospital")],
        "hotel": [("tourism", "hotel")],

        "gym": [("leisure", "fitness_centre"), ("amenity", "gym")],
        "fitness": [("leisure", "fitness_centre"), ("amenity", "gym")],
    }

    pairs = TAG_MAP.get(term)

    if pairs:
        parts = []
        for k, v in pairs:
            parts.append(f'node(around:{radius_m},{lat},{lon})["{k}"="{v}"];')
            parts.append(f'way(around:{radius_m},{lat},{lon})["{k}"="{v}"];')
            parts.append(f'relation(around:{radius_m},{lat},{lon})["{k}"="{v}"];')
        selector = "\n".join(parts)
    else:
        safe = term.replace('"', "").replace("\\", "")
        selector = f"""
          node(around:{radius_m},{lat},{lon})["name"~"{safe}",i];
          way(around:{radius_m},{lat},{lon})["name"~"{safe}",i];
          relation(around:{radius_m},{lat},{lon})["name"~"{safe}",i];

          node(around:{radius_m},{lat},{lon})["amenity"~"{safe}",i];
          way(around:{radius_m},{lat},{lon})["amenity"~"{safe}",i];
          relation(around:{radius_m},{lat},{lon})["amenity"~"{safe}",i];

          node(around:{radius_m},{lat},{lon})["shop"~"{safe}",i];
          way(around:{radius_m},{lat},{lon})["shop"~"{safe}",i];
          relation(around:{radius_m},{lat},{lon})["shop"~"{safe}",i];

          node(around:{radius_m},{lat},{lon})["tourism"~"{safe}",i];
          way(around:{radius_m},{lat},{lon})["tourism"~"{safe}",i];
          relation(around:{radius_m},{lat},{lon})["tourism"~"{safe}",i];
        """

    query = f"""
    [out:json][timeout:60];
    (
      {selector}
    );
    out tags center;
    """

    elements = []
    last_err = None

    for url in _shuffled_overpass_urls():
            try:
                r = _session.post(url, data=query.encode("utf-8"), timeout=timeout)
                r.raise_for_status()
                data = r.json() or {}
                elements = data.get("elements", []) or []
                last_err = None
                break
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
                # DNS fail / no internet / server down
                last_err = e
                continue
            except requests.RequestException as e:
                last_err = e
                continue

        # ✅ instead of raising, return [] so your app stays usable
    if last_err and not elements:
            return []

    results = []
    seen = set()

    for el in elements:
        tags = el.get("tags") or {}

        # center/latlon
        if "lat" in el and "lon" in el:
            rlat, rlon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center") or {}
            rlat, rlon = center.get("lat"), center.get("lon")

        if rlat is None or rlon is None:
            continue

        name = (tags.get("name") or "").strip() or term.title()

        housenumber = tags.get("addr:housenumber", "") or ""
        street = tags.get("addr:street", "") or ""
        address = (" ".join([housenumber, street])).strip()

        city = tags.get("addr:city", "") or tags.get("addr:suburb", "") or ""
        state = tags.get("addr:state", "") or ""
        zip_code = tags.get("addr:postcode", "") or ""

        osm_id = f"{el.get('type','')}_{el.get('id','')}"
        if osm_id in seen:
            continue
        seen.add(osm_id)

        url = (
            tags.get("website", "")
            or tags.get("contact:website", "")
            or tags.get("url", "")
        )
        phone = tags.get("phone", "") or tags.get("contact:phone", "")

        # ✅ If missing address parts, try reverse geocode (best effort)
        if (not address or not city or not state) and rlat and rlon:
            r_address, r_city, r_state, r_zip = reverse_geocode(float(rlat), float(rlon))
            address = address or r_address
            city = city or r_city
            state = state or r_state
            zip_code = zip_code or r_zip

        results.append(
            {
                "osm_id": osm_id,
                "name": name,
                "address": address,
                "city": city,
                "state": state,
                "zip_code": zip_code,
                "url": url,
                "phone": phone,
                "lat": rlat,
                "lon": rlon,
            }
        )

        if len(results) >= limit:
            break

    return results
