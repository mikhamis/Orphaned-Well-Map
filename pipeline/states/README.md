# State well-record configs

One JSON file per state (`TX.json`, `PA.json`, ...), copied from `_template.json`.
The build joins every USGS orphaned well in that state to this file.

| key | meaning |
| --- | --- |
| `source.url` | direct download (CSV/TSV/TXT/GeoJSON, or a ZIP containing one; set `member` if the ZIP has several tables). Leave `null` and pass `--state-file XX=path` for files that need a form, login, or format conversion. |
| `columns.api`, `columns.operator` | required |
| `columns.status`, `lat`, `lon` | needed for the nearby-active-wells search and the location fallback match |
| `columns.lease`, `well_name`, `date` | optional; `date` breaks ties when an API appears on several rows |
| `active_status` | case-insensitive regexes; a well counts as active if its status matches any |
| `verified` | set `true` only after spot-checking matches by hand; the site flags unverified states |

## Converting other formats

Shapefiles, file geodatabases, and Excel files need converting to CSV first (GDAL):

```sh
ogr2ogr -f CSV -t_srs EPSG:4326 -lco GEOMETRY=AS_XY wells.csv wells.shp   # adds X/Y columns
```

`-t_srs EPSG:4326` also reprojects state-plane coordinates, which this pipeline does not handle itself.

## Status

No state configs ship yet. The pipeline was written in an environment that couldn't reach
state agency sites, and the URLs and column names here are filled in only after checking
them against the real file. Start with the states holding the most USGS orphan wells
(the build prints per-state counts).
