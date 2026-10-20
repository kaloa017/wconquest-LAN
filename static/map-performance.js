/* One viewport canvas for grid ownership; static geography arrives by region. */
(function(root,factory){
  const module=factory();if(typeof exports==='object')Object.assign(exports,module);
  else {root.WCMap=module;module.install(root);}
})(typeof window==='undefined'?globalThis:window,function(){
  function runs(tiles){
    const cells=Object.values(tiles).filter(t=>t.owner_id&&!t.grid_key.startsWith('island:')).map(t=>{
      const [a,b]=t.grid_key.split(',').map(Number);return {a,b,end:b,key:t.grid_key,owner:t.owner_id,color:t.color||'#888'};
    }).sort((x,y)=>x.a-y.a||x.b-y.b);
    const result=[];
    for(const cell of cells){const last=result.at(-1);if(last&&last.a===cell.a&&last.end+1===cell.b&&last.owner===cell.owner&&last.color===cell.color)last.end=cell.b;else result.push({...cell});}
    return result;
  }
  function visible(run,bounds,grid){return run.a*grid<=bounds.north&&(run.a+1)*grid>=bounds.south&&run.b*grid<=bounds.east&&(run.end+1)*grid>=bounds.west;}
  function install(w){
    let manifest=null,worldLayer=null,baseLayers=[],gridLayer=null,ownershipDirty=true,indexSource=null,gridRuns=[];
    const loaded=new Map(),pending=new Map();let geographyLoad=null,clickSerial=0;
    async function loadRegion(region){
      if(loaded.has(region)){const features=loaded.get(region);loaded.delete(region);loaded.set(region,features);return;}
      if(pending.has(region))return pending.get(region);
      const promise=(async()=>{
        const response=await fetch(manifest.regions[region]);if(!response.ok)throw new Error('Map region unavailable');
        const collection=await response.json();
        for(const feature of collection.features){const entry=pacificIslands[feature.properties.key];if(entry)entry.geometry=feature.geometry;}
        loaded.set(region,collection.features.map(f=>f.properties.key));
        while(loaded.size>12){const oldest=loaded.keys().next().value;for(const key of loaded.get(oldest))if(pacificIslands[key])pacificIslands[key].geometry=null;loaded.delete(oldest);}
      })().finally(()=>pending.delete(region));
      pending.set(region,promise);return promise;
    }
    async function loadVisibleGeometry(){
      if(!manifest||!map||map.getZoom()<6)return;
      const bounds=map.getBounds().pad(.15),regions=new Set();
      for(const feature of Object.values(pacificIslands)){
        const [left,bottom,right,top]=feature.properties.bounds;
        if(bounds.intersects([[bottom,left],[top,right]]))regions.add(feature.properties.region);
      }
      // Sequential batches bound memory and avoid flooding the Pi after a zoom.
      for(const region of regions){await loadRegion(region);if(!map||map.getZoom()<6)return;}
      drawPacificIslands();
    }
    loadLandGeoJSON=async function(){
      if(!geographyLoad)geographyLoad=(async()=>{
        const [cells,index]=await Promise.all([fetch('/api/terrain/cells?v='+encodeURIComponent(gameConfig.version)),fetch('/static/map/manifest.json')]);
        if(!cells.ok||!index.ok)throw new Error('Map data unavailable');
        terrainBits=new Uint8Array(await cells.arrayBuffer());if(terrainBits.length!==236500)throw new Error('Invalid terrain data');
        manifest=await index.json();if(manifest.format!==1)throw new Error('Unsupported map data');
        pacificIslands=Object.fromEntries(manifest.islands.map(properties=>[properties.key,{type:'Feature',properties,geometry:null}]));
        islandBuckets.clear();
        for(const feature of Object.values(pacificIslands)){
          const [left,bottom,right,top]=feature.properties.bounds;
          for(let x=Math.floor(left/5);x<=Math.floor(right/5);x++)for(let y=Math.floor(bottom/5);y<=Math.floor(top/5);y++){
            const key=x+','+y;if(!islandBuckets.has(key))islandBuckets.set(key,[]);islandBuckets.get(key).push(feature);
          }
        }
        const response=await fetch(manifest.world);if(!response.ok)throw new Error('World overview unavailable');
        return response.json();
      })().catch(error=>{geographyLoad=null;throw error;});
      const world=await geographyLoad;
      landGeoJSON={type:'FeatureCollection',features:[]};
      // Keep opaque land behind ownership even if it arrives after the first delta.
      worldLayer=L.geoJSON(world,{interactive:false,pane:'world-overview',renderer:L.canvas({pane:'world-overview',padding:.25}),style:{color:'#465d70',weight:.6,fillColor:'#182b35',fillOpacity:1},smoothFactor:2});
      if(map){map.off('moveend',drawPacificIslands);map.on('moveend zoomend',viewChanged);viewChanged();renderTerritories();}
    };
    const contains=islandContainsPoint;
    islandContainsPoint=function(feature,lat,lng){return !!feature.geometry&&contains(feature,lat,lng);};
    const click=onMapClick;
    onMapClick=async function(event){
      const generation=sessionGeneration,serial=++clickSerial;
      try{
        const {lat,lng}=event.latlng,candidates=islandBuckets.get(Math.floor(lng/5)+','+Math.floor(lat/5))||[];
        const needed=new Set(candidates.filter(f=>{
          const [left,bottom,right,top]=f.properties.bounds;
          return !f.geometry&&(!f.properties.grid_tiles||territories[f.properties.key]?.owner_id)&&left<=lng&&lng<=right&&bottom<=lat&&lat<=top;
        }).map(f=>f.properties.region));
        for(const region of needed)await loadRegion(region);
        if(generation===sessionGeneration&&serial===clickSerial)click(event);
      }catch(error){console.error('Map region failed:',error);toast('This map region could not load. Tap again to retry.','error');}
    };
    const move=onMapMove;
    onMapMove=function(event){if(map.getZoom()<6){hoverInfo(event.latlng);return;}move(event);};
    drawPacificIslands=function(){
      if(!map||!manifest)return;
      if(islandLayer)map.removeLayer(islandLayer);islandLayer=L.layerGroup().addTo(map);
      const bounds=map.getBounds().pad(.1),detailed=map.getZoom()>=6;
      for(const feature of Object.values(pacificIslands)){
        const p=feature.properties,tile=territories[p.key],selected=p.key===selectedKey;
        if(!tile?.owner_id&&!selected)continue;
        const [left,bottom,right,top]=p.bounds;if(!bounds.intersects([[bottom,left],[top,right]]))continue;
        const color=tile?.color||'#f0c040',style={renderer:canvasR,color:selected?'#f0c040':color,weight:selected?2:detailed?1:0,fillColor:color,fillOpacity:.65};
        const layer=detailed&&feature.geometry?L.geoJSON(feature,{bubblingMouseEvents:false,renderer:canvasR,style,smoothFactor:1.5}):L.circleMarker([p.lat,p.lng],{...style,radius:selected?4:2});
        layer.on('click',()=>inspectIsland(p.key)).addTo(islandLayer);
      }
    };
    const Grid=L.Layer.extend({
      onAdd(m){this._map=m;this.canvas=L.DomUtil.create('canvas','ownership-canvas leaflet-zoom-hide');this.canvas.style.pointerEvents='none';m.getPanes().overlayPane.appendChild(this.canvas);this.redraw();},
      onRemove(){cancelAnimationFrame(this.frame);this.canvas.remove();},
      getEvents(){return {moveend:this.redraw,zoomend:this.redraw,viewreset:this.redraw};},
      redraw(){cancelAnimationFrame(this.frame);this.frame=requestAnimationFrame(()=>this.paint());},
      paint(){
        const m=this._map;if(!m||!this.canvas.isConnected)return;
        const size=m.getSize(),pad=size.multiplyBy(.25),origin=m.containerPointToLayerPoint(pad.multiplyBy(-1)),ratio=Math.min(w.devicePixelRatio||1,2);
        L.DomUtil.setPosition(this.canvas,origin);this.canvas.style.width=size.x*1.5+'px';this.canvas.style.height=size.y*1.5+'px';
        this.canvas.width=Math.ceil(size.x*1.5*ratio);this.canvas.height=Math.ceil(size.y*1.5*ratio);
        const ctx=this.canvas.getContext('2d');ctx.scale(ratio,ratio);
        const bounds=m.getBounds().pad(.25),box={north:bounds.getNorth(),south:bounds.getSouth(),east:bounds.getEast(),west:bounds.getWest()},zoom=m.getZoom();
        let count=0;
        for(const run of gridRuns){
          if(!visible(run,box,GRID))continue;
          const left=Math.max(run.b,Math.floor(box.west/GRID)),right=Math.min(run.end,Math.floor(box.east/GRID));
          const a=m.latLngToLayerPoint([(run.a+1)*GRID,left*GRID]).subtract(origin),b=m.latLngToLayerPoint([run.a*GRID,(right+1)*GRID]).subtract(origin);
          ctx.fillStyle=run.color;ctx.globalAlpha=.55;ctx.fillRect(a.x,a.y,b.x-a.x,b.y-a.y);count++;
          if(zoom>=7){ctx.globalAlpha=.6;ctx.strokeStyle=run.color;ctx.lineWidth=.7;const width=(b.x-a.x)/(right-left+1);for(let cell=left;cell<=right;cell++)ctx.strokeRect(a.x+(cell-left)*width,a.y,width,b.y-a.y);}
        }
        if(selectedKey&&!selectedKey.startsWith('island:')){
          const [a,b]=selectedKey.split(',').map(Number),p=m.latLngToLayerPoint([(a+1)*GRID,b*GRID]).subtract(origin),q=m.latLngToLayerPoint([a*GRID,(b+1)*GRID]).subtract(origin);
          ctx.globalAlpha=1;ctx.strokeStyle='#ffe08a';ctx.lineWidth=2;ctx.strokeRect(p.x,p.y,q.x-p.x,q.y-p.y);
        }
        w.WCMap.lastFrame={runs:count,zoom};
      }
    });
    const caps=drawCaps;
    drawCaps=function(){if(!map)return;if(map.getZoom()<5){if(capLayer)map.removeLayer(capLayer);return;}caps();};
    renderTerritories=function(){
      if(!map)return;
      if(ownershipDirty||indexSource!==territories){gridRuns=runs(territories);indexSource=territories;ownershipDirty=false;}
      for(const layer of Object.values(tlayers))map.removeLayer(layer);tlayers={};
      if(!gridLayer||gridLayer._map!==map)gridLayer=new Grid().addTo(map);else gridLayer.redraw();
      drawCaps();drawPacificIslands();
    };
    function viewChanged(){
      if(!map)return;
      if(!baseLayers.length&&w.wcBaseMapLayer)baseLayers=[w.wcBaseMapLayer];
      const detail=map.getZoom()>=6;
      if(!detail&&hoverRect){map.removeLayer(hoverRect);hoverRect=null;}
      if(worldLayer){if(detail&&map.hasLayer(worldLayer))map.removeLayer(worldLayer);else if(!detail&&!map.hasLayer(worldLayer))worldLayer.addTo(map);}
      for(const layer of baseLayers){if(detail&&!map.hasLayer(layer))layer.addTo(map);else if(!detail&&map.hasLayer(layer))map.removeLayer(layer);}
      drawCaps();drawPacificIslands();
      loadVisibleGeometry().catch(error=>{console.warn('Map detail could not load:',error);});
    }
    const init=initMap;
    initMap=function(){baseLayers=[];gridLayer=null;indexSource=null;worldLayer=null;init();const pane=map.createPane('world-overview');pane.style.zIndex='210';pane.style.pointerEvents='none';};
    w.WCMap.loadRegion=loadRegion;
    w.WCMap.invalidateOwnership=()=>{ownershipDirty=true;};
  }
  return {runs,visible,install};
});
