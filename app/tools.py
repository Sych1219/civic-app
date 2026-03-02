import httpx
from langchain_core.tools import tool

ONEMAP_SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"


@tool
def geocode_place(place_name: str) -> str:
    """Resolve a Singapore place name or address to latitude and longitude."""
    response = httpx.get(
        ONEMAP_SEARCH_URL,
        params={
            "searchVal": place_name,
            "returnGeom": "Y",
            "getAddrDetails": "N",
            "pageNum": 1,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        return f"Could not geocode '{place_name}'."
    r = results[0]
    return f"{place_name}: lat={r['LATITUDE']}, lng={r['LONGITUDE']}"
