#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
generate_ugc_population.py — Canal Meteo
============================================================================
Genera /opt/canalmeteo/data/ugc_population.csv para que tornado_warnings_pipeline.py
pueda calcular la población bajo cada Tornado Warning.

UGC = Universal Geographic Code de NWS. Formato: SSCnnn donde:
  SS  = state abbrev (TX, KS, OK...)
  C   = 'C' for county (FIPS county) or 'Z' for forecast zone
  nnn = 3-digit county code

Este script:
  1. Descarga la lista de UGCs desde NWS shapefile metadata
  2. Cruza UGC ↔ FIPS de condado
  3. Descarga población del Census Bureau ACS (American Community Survey)
  4. Genera CSV: ugc,population

Solo necesita ejecutarse 1 vez (o anualmente cuando Census actualiza datos).

Uso:
    python3 generate_ugc_population.py
    sudo mv /tmp/ugc_population.csv /opt/canalmeteo/data/

Requisitos:
    pip install requests
============================================================================
"""

import csv
import requests
import sys
from pathlib import Path

OUT_PATH = "/tmp/ugc_population.csv"

# Census Bureau ACS 5-year estimates (latest published)
# B01003_001E = Total population
CENSUS_API = "https://api.census.gov/data/2022/acs/acs5"

# Mapping state name/abbrev for state FIPS lookup
STATE_FIPS = {
    'AL':'01','AK':'02','AZ':'04','AR':'05','CA':'06','CO':'08','CT':'09',
    'DE':'10','DC':'11','FL':'12','GA':'13','HI':'15','ID':'16','IL':'17',
    'IN':'18','IA':'19','KS':'20','KY':'21','LA':'22','ME':'23','MD':'24',
    'MA':'25','MI':'26','MN':'27','MS':'28','MO':'29','MT':'30','NE':'31',
    'NV':'32','NH':'33','NJ':'34','NM':'35','NY':'36','NC':'37','ND':'38',
    'OH':'39','OK':'40','OR':'41','PA':'42','RI':'44','SC':'45','SD':'46',
    'TN':'47','TX':'48','UT':'49','VT':'50','VA':'51','WA':'53','WV':'54',
    'WI':'55','WY':'56'
}

def fetch_county_pop(state_fips):
    """Get population per county within a state."""
    params = {
        "get": "NAME,B01003_001E",
        "for": "county:*",
        "in": f"state:{state_fips}"
    }
    r = requests.get(CENSUS_API, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    # First row is headers
    headers = data[0]
    rows = data[1:]
    name_idx = headers.index("NAME")
    pop_idx = headers.index("B01003_001E")
    state_idx = headers.index("state")
    county_idx = headers.index("county")
    out = []
    for row in rows:
        try:
            pop = int(row[pop_idx])
        except (ValueError, TypeError):
            pop = 0
        out.append({
            "name": row[name_idx],
            "population": pop,
            "state_fips": row[state_idx],
            "county_fips": row[county_idx]  # 3-digit
        })
    return out

def main():
    print("Generando ugc_population.csv desde Census ACS5...")
    rows = []
    for state_abbr, state_fips in STATE_FIPS.items():
        try:
            counties = fetch_county_pop(state_fips)
            for c in counties:
                # UGC code format for county: {STATE}C{COUNTY_FIPS}
                ugc = f"{state_abbr}C{c['county_fips']}"
                rows.append({
                    "ugc": ugc,
                    "state": state_abbr,
                    "county_fips": c["county_fips"],
                    "name": c["name"],
                    "population": c["population"]
                })
            print(f"  {state_abbr}: {len(counties)} condados")
        except Exception as e:
            print(f"  ⚠️  {state_abbr}: error {e}")

    print(f"\nEscribiendo {len(rows)} filas en {OUT_PATH}")
    Path(OUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ugc","state","county_fips","name","population"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ Listo. Mueve a su ubicación final:")
    print(f"   sudo mv {OUT_PATH} /opt/canalmeteo/data/ugc_population.csv")
    print(f"\nPara probar lookup:")
    print(f"   grep '^TXC' {OUT_PATH} | head -5")

if __name__ == "__main__":
    main()
