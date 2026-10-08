# Third-party data and assets

Bundled Natural Earth land, minor-island, Antarctic ice-shelf and country data are
public domain. Sources: https://www.naturalearthdata.com/about/terms-of-use/ and
https://github.com/nvkelso/natural-earth-vector. These are generalized map datasets,
not survey-accurate coastlines. tools/build_terrain.py reproduces compact geography.

The browser loads Leaflet (BSD-2-Clause) and Turf (MIT) from cdnjs. Dependencies
retain their respective licences. OpenStreetMap background tiles/data require
attribution; the game displays map attribution. Hosts must follow the provider's
usage policy or configure a suitable tile service for their traffic.

No MP3 or EVA JPG artwork is bundled. Hosts are responsible for rights to any
artwork/music they add. These local assets are ignored by Git.
