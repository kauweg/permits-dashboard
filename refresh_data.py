from __future__ import annotations
import csv, io, json, os, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
YEARS = {2022, 2023, 2024, 2025, 2026}
SEATTLE_CSV_URL = "https://data.seattle.gov/api/views/76t5-zqzr/rows.csv?accessType=DOWNLOAD"
BELLEVUE_CSV_URL = os.getenv("BELLEVUE_PERMITS_URL", "").strip() or "https://hub.arcgis.com/api/download/v1/items/fc7da7bd29d4493481b17d032e117d09/csv?layers=0&redirect=true"
MARKET_BOUNDS = [("West Seattle",47.49,47.61,-122.43,-122.34),("Downtown Seattle",47.595,47.625,-122.36,-122.315),("First Hill / Capitol Hill",47.608,47.642,-122.335,-122.29),("South Lake Union / Eastlake",47.615,47.655,-122.35,-122.31),("Queen Anne / Magnolia",47.615,47.675,-122.43,-122.34),("Ballard",47.655,47.695,-122.41,-122.355),("Fremont / Wallingford",47.645,47.675,-122.365,-122.32),("University District / Northeast",47.645,47.73,-122.33,-122.25),("North Seattle",47.675,47.735,-122.38,-122.29),("Central Seattle",47.59,47.63,-122.32,-122.285),("Beacon Hill",47.535,47.595,-122.335,-122.29),("South Seattle",47.49,47.575,-122.33,-122.24),("Greater Duwamish",47.50,47.60,-122.36,-122.30),("Bellevue Downtown",47.600,47.625,-122.215,-122.185),("Wilburton",47.585,47.615,-122.195,-122.165),("Eastgate",47.560,47.590,-122.160,-122.120),("Crossroads",47.605,47.635,-122.150,-122.110),("Factoria",47.555,47.590,-122.190,-122.155),("Bel-Red",47.615,47.650,-122.200,-122.160),("West Bellevue",47.595,47.635,-122.235,-122.200),("Bellevue",47.540,47.660,-122.245,-122.100)]
NEIGHBORHOOD_BOUNDS = [("Alki / Admiral","West Seattle",47.57,47.60,-122.42,-122.37),("West Seattle Junction","West Seattle",47.55,47.58,-122.40,-122.36),("Delridge","West Seattle",47.52,47.58,-122.37,-122.33),("Fauntleroy / Arbor Heights","West Seattle",47.49,47.54,-122.42,-122.36),("Belltown / Pike Market","Downtown Seattle",47.608,47.620,-122.355,-122.335),("Commercial Core","Downtown Seattle",47.603,47.615,-122.340,-122.325),("Pioneer Square / ID","Downtown Seattle",47.595,47.607,-122.340,-122.315),("First Hill","First Hill / Capitol Hill",47.605,47.615,-122.330,-122.315),("Capitol Hill","First Hill / Capitol Hill",47.615,47.642,-122.330,-122.295),("South Lake Union","South Lake Union / Eastlake",47.615,47.630,-122.350,-122.325),("Eastlake","South Lake Union / Eastlake",47.630,47.655,-122.335,-122.315),("Queen Anne","Queen Anne / Magnolia",47.625,47.655,-122.37,-122.34),("Magnolia","Queen Anne / Magnolia",47.625,47.675,-122.43,-122.37),("Ballard","Ballard",47.66,47.69,-122.41,-122.36),("Fremont","Fremont / Wallingford",47.645,47.66,-122.36,-122.34),("Wallingford","Fremont / Wallingford",47.655,47.675,-122.345,-122.32),("U District / Ravenna","University District / Northeast",47.655,47.685,-122.325,-122.295),("Wedgwood / View Ridge","University District / Northeast",47.675,47.71,-122.305,-122.25),("Greenwood / Northgate","North Seattle",47.68,47.735,-122.37,-122.30),("Central District","Central Seattle",47.598,47.625,-122.315,-122.29),("Madison / Leschi","Central Seattle",47.595,47.635,-122.30,-122.275),("Beacon Hill","Beacon Hill",47.535,47.595,-122.325,-122.295),("Columbia City / Rainier","South Seattle",47.54,47.575,-122.305,-122.275),("Rainier Beach","South Seattle",47.49,47.54,-122.29,-122.24),("Downtown Bellevue","Bellevue Downtown",47.600,47.625,-122.215,-122.185),("Wilburton","Wilburton",47.585,47.615,-122.195,-122.165),("Eastgate","Eastgate",47.560,47.590,-122.160,-122.120),("Crossroads","Crossroads",47.605,47.635,-122.150,-122.110),("Factoria","Factoria",47.555,47.590,-122.190,-122.155),("Bel-Red","Bel-Red",47.615,47.650,-122.200,-122.160)]
MULTI = ["multifamily","multi-family","multi family","apartment","apartments","townhome","townhomes","townhouse","townhouses","condo","condominium","rowhouse","rowhouses","mixed use","mixed-use","duplex","triplex","fourplex"]
SINGLE = ["single family","single-family","single family residence","one-family","one family","sfr","one-family dwelling"]
DEMO = [" demol"," demolition"," demo ","teardown"," raze ","remove structure"]
UNIT_PATTERNS=[re.compile(p,re.I) for p in [r"(\d{1,4})\s+units?\b",r"(\d{1,4})[-\s]+unit\b",r"(\d{1,4})\s+apartments?\b",r"(\d{1,4})\s+condos?\b",r"(\d{1,4})\s+townhomes?\b",r"(\d{1,4})\s+townhouses?\b",r"(\d{1,4})\s+dwelling\s+units?\b",r"(\d{1,4})\s+residential\s+units?\b"]]
def norm(x): return " ".join(str(x or "").replace("\xa0"," ").split())
def pick(row, keys):
    lower={str(k).lower():v for k,v in row.items()}
    for k in keys:
        if k in row and norm(row.get(k)): return row.get(k)
        if k.lower() in lower and norm(lower[k.lower()]): return lower[k.lower()]
    return None
def parse_dt(v):
    s=norm(v)
    if not s: return None
    for f in ("%Y-%m-%dT%H:%M:%S.%f","%Y-%m-%dT%H:%M:%S","%Y-%m-%d","%m/%d/%Y","%m/%d/%Y %H:%M:%S","%m/%d/%y"):
        try: return datetime.strptime(s[:26],f)
        except Exception: pass
    try: return datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception: return None
def flt(v):
    try:
        if v in (None,"","NULL"): return None
        return float(v)
    except Exception: return None
def assign(lat,lon,fallback,jur):
    for name,market,a,b,c,d in NEIGHBORHOOD_BOUNDS:
        if lat is not None and lon is not None and a<=lat<=b and c<=lon<=d: return market,name
    for market,a,b,c,d in MARKET_BOUNDS:
        if lat is not None and lon is not None and a<=lat<=b and c<=lon<=d: return market,norm(fallback) or market
    if norm(fallback): return norm(fallback), norm(fallback)
    return ("Bellevue","Bellevue") if jur=="Bellevue" else ("Unknown","Unknown")
def looks_new(t):
    t=f" {norm(t).lower()} "
    return any(k in t for k in [" new ","new construction","new building","new structure","construct","construct new","establish use as and construct","ground up","build"])
def classify(text):
    t=f" {norm(text).lower()} "
    if any(k in t for k in DEMO): return "Demo"
    if not looks_new(t): return None
    if any(h in t for h in MULTI): return "New MF"
    if any(h in t for h in SINGLE): return "New SFR"
    return None
def units(text,category):
    t=norm(text); lo=t.lower()
    for p in UNIT_PATTERNS:
        m=p.search(t)
        if m:
            try: return int(m.group(1)), int(m.group(1))
            except Exception: pass
    if category=="New SFR": return 0,1
    if category=="New MF":
        if "duplex" in lo: return 0,2
        if "triplex" in lo: return 0,3
        if "fourplex" in lo: return 0,4
    return 0,0
def rows_from(url):
    r=requests.get(url,timeout=240); r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))
def build_row(row,jur):
    if jur=="Seattle":
        text=" ".join([norm(pick(row,["permitclass","permit_class"])),norm(pick(row,["permittype","permit_type"])),norm(pick(row,["description","permitdescription","permitdesc"]))])
        issue=parse_dt(pick(row,["issueddate","issuedate","issue_date"])); intake=parse_dt(pick(row,["applicationdate","application_date"])); addr=norm(pick(row,["originaladdress1","address","siteaddress","site_address"])); fallback=norm(pick(row,["neighborhood","neighborhoodname","neighborhood_name"])); lat=flt(pick(row,["latitude","lat"])); lon=flt(pick(row,["longitude","long","lng","lon"]))
    else:
        text=" ".join([norm(pick(row,["PermitType"])),norm(pick(row,["TypeDetailNames"])),norm(pick(row,["WorkDetail"])),norm(pick(row,["StatusDescription"]))])
        issue=parse_dt(pick(row,["IssueDate","IssuedDate"])); intake=parse_dt(pick(row,["ApplicationDate","IntakeDate"])); addr=norm(pick(row,["WorkLocationFullAddress","Address","SiteAddress"])); fallback=norm(pick(row,["NeighborhoodNames","NeighborhoodClusters","Neighborhood"])); lat=flt(pick(row,["Latitude","Lat"])); lon=flt(pick(row,["Longitude","Lng","Lon"]))
    cat=classify(text)
    if not cat: return None
    dt=issue or intake
    if not dt or dt.year not in YEARS: return None
    market,hood=assign(lat,lon,fallback,jur); known,est=units(text,cat)
    return {"jurisdiction":jur,"market":market,"neighborhood":market,"raw_neighborhood":hood,"address":addr,"category":cat,"units":known,"estimated_units":est,"issue_date":issue.date().isoformat() if issue else "","intake_date":intake.date().isoformat() if intake else "","year":dt.year,"latitude":lat,"longitude":lon,"summary":text}
def fetch(debug,jur,url):
    raw=rows_from(url); out=[]; dropped=0; cols=set()
    for r in raw:
        cols.update(r.keys()); item=build_row(r,jur)
        if item: out.append(item)
        else: dropped+=1
    k=jur.lower(); debug[f"{k}_rows_examined"]=len(raw); debug[f"{k}_rows_kept"]=len(out); debug[f"{k}_rows_dropped"]=dropped; debug[f"{k}_unknown_market_rows"]=sum(1 for x in out if x["market"]=="Unknown"); debug[f"{k}_columns_seen"]=sorted(cols)
    return out
def build_outputs(rows,debug):
    cards={"total_permits":len(rows),"seattle_permits":sum(1 for r in rows if r["jurisdiction"]=="Seattle"),"bellevue_permits":sum(1 for r in rows if r["jurisdiction"]=="Bellevue"),"known_markets":len({r["market"] for r in rows if r["market"]!="Unknown"}),"known_neighborhoods":len({r["raw_neighborhood"] for r in rows if r["raw_neighborhood"]!="Unknown"}),"new_sfr":sum(1 for r in rows if r["category"]=="New SFR"),"new_mf":sum(1 for r in rows if r["category"]=="New MF"),"demo":sum(1 for r in rows if r["category"]=="Demo"),"known_units":sum(int(r.get("units") or 0) for r in rows),"estimated_units":sum(int(r.get("estimated_units") or 0) for r in rows)}
    annual={y:{"year":y,"New SFR":0,"New MF":0,"Demo":0,"Total":0,"Known Units":0,"Estimated Units":0} for y in sorted(YEARS)}
    def roll(field):
        g={}
        for r in rows:
            y=r["year"]; cat=r["category"]; ku=int(r.get("units") or 0); eu=int(r.get("estimated_units") or 0)
            if y in annual: annual[y][cat]+=1; annual[y]["Total"]+=1; annual[y]["Known Units"]+=ku; annual[y]["Estimated Units"]+=eu
            key=r.get(field) or "Unknown"
            if key not in g: g[key]={"name":key,"market":r.get("market") or "Unknown","jurisdictions":set(),"years":{str(yy):{"New SFR":0,"New MF":0,"Demo":0,"Total":0,"Known Units":0,"Estimated Units":0} for yy in sorted(YEARS)},"totals":{"New SFR":0,"New MF":0,"Demo":0,"Total":0,"Known Units":0,"Estimated Units":0}}
            o=g[key]; o["jurisdictions"].add(r["jurisdiction"]); ys=o["years"][str(y)]; ys[cat]+=1; ys["Total"]+=1; ys["Known Units"]+=ku; ys["Estimated Units"]+=eu; o["totals"][cat]+=1; o["totals"]["Total"]+=1; o["totals"]["Known Units"]+=ku; o["totals"]["Estimated Units"]+=eu
        out=[]
        for o in g.values(): o["jurisdictions"]=sorted(o["jurisdictions"]); out.append(o)
        return sorted(out,key=lambda x:(-x["totals"]["Total"],x["name"]))
    market_rows=roll("market"); neighborhood_rows=roll("raw_neighborhood")
    summary={"generated_at":datetime.now(timezone.utc).isoformat(),"cards":cards,"annual_series":[annual[y] for y in sorted(annual)],"market_rows":market_rows,"neighborhood_rows":neighborhood_rows,"map_points":rows,"load_notes":[f"Precomputed refresh generated {len(rows)} target permit rows.",f"Seattle kept {debug.get('seattle_rows_kept',0)} rows out of {debug.get('seattle_rows_examined',0)} examined.",f"Bellevue kept {debug.get('bellevue_rows_kept',0)} rows out of {debug.get('bellevue_rows_examined',0)} examined.",f"Known markets after refresh: {cards['known_markets']}.",f"Known neighborhoods after refresh: {cards['known_neighborhoods']}.",f"Known units: {cards['known_units']}; estimated units: {cards['estimated_units']}."] ,"load_errors":debug.get("errors",[])}
    meta={"generated_at":summary["generated_at"],"markets":sorted({r["market"] for r in rows if r.get("market")}),"neighborhoods":sorted({r["raw_neighborhood"] for r in rows if r.get("raw_neighborhood")}),"load_notes":summary["load_notes"],"load_errors":summary["load_errors"]}
    return summary,meta
def main():
    debug={"errors":[]}; rows=[]
    print("Fetching Seattle permits...")
    try: rows.extend(fetch(debug,"Seattle",SEATTLE_CSV_URL))
    except Exception as e: debug["errors"].append(f"Seattle refresh failed: {e}")
    print("Fetching Bellevue permits...")
    try: rows.extend(fetch(debug,"Bellevue",BELLEVUE_CSV_URL))
    except Exception as e: debug["errors"].append(f"Bellevue refresh failed: {e}")
    summary,meta=build_outputs(rows,debug)
    (DATA_DIR/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    (DATA_DIR/"meta.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
    (DATA_DIR/"refresh_debug.json").write_text(json.dumps(debug,indent=2),encoding="utf-8")
    print("Wrote", DATA_DIR/"summary.json"); print("Wrote", DATA_DIR/"meta.json"); print("Wrote", DATA_DIR/"refresh_debug.json")
if __name__=="__main__": main()
