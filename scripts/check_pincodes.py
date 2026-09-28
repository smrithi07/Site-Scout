import pandas as pd
import geopandas as gpd

POLY = "data/raw/pincode/chennai_boundary_datameet.geojson"
DIR = "data/raw/pincode/pincode_directory_bharatpin.csv"


def norm_pin(series):
    return pd.to_numeric(series, errors="coerce").astype("Int64").astype(str)


g = gpd.read_file(POLY)
g["pin"] = norm_pin(g["pin"])
print("== datameet polygons ==")
print("rows:", len(g), "| crs:", g.crs, "| unique pins:", g["pin"].nunique())
print("bounds:", [round(x, 3) for x in g.total_bounds])
print("rows with no pin:", int((g["pin"] == "<NA>").sum()))

d = pd.read_csv(DIR, dtype=str)
print("\n== bharatpin directory ==")
print("total rows:", len(d))
c = d[(d.state.str.lower() == "tamil nadu") & d.pincode.str.startswith("600")].copy()
c["lat"] = pd.to_numeric(c.latitude, errors="coerce")
c["lon"] = pd.to_numeric(c.longitude, errors="coerce")
inside = c[c.lat.between(12.7, 13.4) & c.lon.between(79.9, 80.4)]
print("Chennai (600xxx) rows:", len(c), "| unique pins:", c.pincode.nunique())
print("with coordinates:", int(c.lat.notna().sum()), "| inside Chennai bbox:", len(inside))

print("\n== cross-check ==")
dir_pins, poly_pins = set(c.pincode.unique()), set(g["pin"].unique())
print("directory pins with NO polygon:", sorted(dir_pins - poly_pins))
print("polygon pins NOT in directory:", sorted(poly_pins - dir_pins))

pts = gpd.GeoDataFrame(inside, geometry=gpd.points_from_xy(inside.lon, inside.lat), crs="EPSG:4326")
j = gpd.sjoin(pts, g[["pin", "geometry"]], how="left", predicate="within")
j = j[~j.index.duplicated(keep="first")]
print("post-office points inside any polygon:", int(j["pin"].notna().sum()), "of", len(j))
print("...inside the polygon with the SAME pincode:", int((j["pin"] == j["pincode"]).sum()))