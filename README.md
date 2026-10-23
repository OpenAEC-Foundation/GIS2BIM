![Image](GIS2BIMLOGO.png)

GIS2BIM is a collection of custom nodes for the Dynamo visual programming environment.  It imports 2D and 3D GIS-information to Autodesk Revit-models. 

To get an impression of GIS2BIM have a look at the workflows in the wiki: https://github.com/DutchSailor/GIS2BIM/wiki/Workflows

![Image](GIS2BIMOpeningImage.png)

## Issues/questions
When you experience bugs, please issue them via 'Issues' in Github.

## Version
Version 0.10.0 released on 10-09-2019. This is the last version for Dynamo 1.x.(Revit 2019 and Dynamo 1.3.3.)

GIS2BIM 0.11.18 can be used for Revit 2020, Revit 2021 and older dynamo versions.

Version 0.12.4 released on 01-06-2024. This is the version for Dynamo 2.x. This dynamopackage is called 'GIS2BIM for Dynamo 2.x'
Works with Revit 2024 and Dynamo 2.x.
For meshes use mesh toolkit version 4.0.0.

## Installation
Installation is possible via the dynamo built-in package manager.

## Material on this repository
-Directory supportfiles contains files with families to use with the nodes and example files.

-Directory nodes contains the versions of the package and the actual nodes

## GIS web services
`GIS2BIM_Data.json` holds the list of web services GIS2BIM uses (`GIS2BIMserversRequests.webserverRequests`); `GIS2BIM_Data_Categorised.json` holds the same services grouped per country and category. Besides the Dutch services the list contains public, keyless services of mapping agencies, cadastres, infrastructure authorities, geological surveys and cities worldwide. An overview per country is in [documentation/GIS_servers.md](documentation/GIS_servers.md).

A request is built as `serverrequestprefix` + bounding box (`minx,miny,maxx,maxy` in the CRS of the request, easting first). WMS prefixes contain `width=3000&height=3000`, which GIS2BIM replaces with the requested image size; `WMTS_TMS` prefixes are XYZ tile templates in EPSG:3857.

Every entry has the fields `serverrequestprefix`, `getCapabilities`, `description`, `service` and `title`. Entries are looked up by `title`, so titles are unique and never change. Newer entries also have:

| Field | Meaning |
|---|---|
| `country` | ISO 3166-1 alpha-2 code, or `EU`, `AFRICA`, `GLOBAL` |
| `coverage` | Area covered by the service |
| `provider` | Organisation publishing the service |
| `category` | `basemap`, `aerial`, `cadastre`, `buildings`, `buildings3d`, `roads`, `rail`, `water`, `structures`, `elevation`, `zoning`, `landcover`, `utilities`, `subsurface`, `protected`, `environment` or `admin` |
| `crs` | Coordinate reference systems advertised by the service (CRS of the request first) |
| `license`, `terms` | Licence as stated by the provider and a link to the licence or terms |
| `cors` | Whether the server allows requests from web pages on other domains |
| `testbbox` | Small bounding box with data, used to test the request (lon/lat for tile services) |
| `maxzoom` | Highest zoom level of a tile service |
| `verified` | Date of the last successful check |

Service types: `WMS`, `WFS`/`WFS_curves`, `WCS` (1.0.0 GetCoverage), `WMTS_TMS`, `OGCAPI_Features`, `ArcGIS_MapServer`, `ArcGIS_FeatureServer` (only where no OGC service exists) and `Download`.

Check the services with `python3 supportfiles/check_servers.py` (options: `--country DE`, `--title ...`, `--report report.json`). It requests every GetCapabilities document, performs the sample request with `testbbox` and reports CORS support.

## Help to develop GIS2BIM
If you are interested in contributing to GIS2BIM, please let me know! You're most welcome.

Notice that this version is very much a beta version, although it is in our opinion usable. If you use it, feedback is very much appreciated.

## More information
https://dutchrevitblog.blogspot.nl/

https://revitstructure-nl.blogspot.nl/

Have a look at the wiki! Every node has a description! https://github.com/DutchSailor/GIS2BIM/wiki
