/* Synthetic ownership planning and DOM cost, not a browser FPS benchmark. */
const {performance}=require('node:perf_hooks'),{JSDOM}=require('jsdom'),fs=require('node:fs'),path=require('node:path');
const model=require('../static/map-performance.js'),tiles={};
for(let row=0;row<200;row++)for(let col=0;col<150;col++)tiles[`${row},${col}`]={grid_key:`${row},${col}`,owner_id:1+Math.floor(col/30),color:'#557799'};
const start=performance.now(),runs=model.runs(tiles),planning=performance.now()-start;
const visible=runs.filter(run=>model.visible(run,{north:20,south:10,west:10,east:20},.18));
const dom=new JSDOM('<svg></svg>'),svg=dom.window.document.querySelector('svg'),svgStart=performance.now();
for(const tile of Object.values(tiles)){const node=dom.window.document.createElementNS('http://www.w3.org/2000/svg','path');node.setAttribute('d','M0 0L1 0L1 1L0 1Z');svg.appendChild(node);}
const svgTime=performance.now()-svgStart;
const root=path.join(__dirname,'..'),manifest=JSON.parse(fs.readFileSync(path.join(root,'static/map/manifest.json'),'utf8'));
const size=url=>fs.statSync(path.join(root,url.replace(/^\//,''))).size;
const full=fs.statSync(path.join(root,'data/pacific-islands.geojson.gz')).size;
const startup=size('/static/map/manifest.json.gz')+size(manifest.world+'.gz');
console.log(JSON.stringify({ownedTiles:Object.keys(tiles).length,legacyLeafletCellLayers:Object.keys(tiles).length,newOwnershipCanvases:1,mergedRuns:runs.length,viewportRuns:visible.length,planningMilliseconds:+planning.toFixed(2),illustrativeSvgDOMMilliseconds:+svgTime.toFixed(2),previousGeographyStartupBytes:full+size('/data/land-cells.bin'),newGeographyStartupGzipBytes:startup+size('/data/land-cells.bin.gz'),detailRegions:Object.keys(manifest.regions).length,largestRegionGzipBytes:Math.max(...Object.values(manifest.regions).map(url=>size(url+'.gz')))},null,2));
dom.window.close();
