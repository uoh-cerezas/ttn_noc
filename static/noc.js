(() => {
  const basePath = String(document.body?.dataset.nocBasePath || '').replace(/\/$/, '');
  const esc = value => String(value ?? '-').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const date = value => value ? new Date(value).toLocaleString() : '-';
  const hasLocation = gateway => gateway.latitude != null && gateway.longitude != null && Number.isFinite(Number(gateway.latitude)) && Number.isFinite(Number(gateway.longitude));
  const googleMapsUrl = gateway => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${Number(gateway.latitude)},${Number(gateway.longitude)}`)}`;
  const ttnConsoleUrl = gateway => gateway.ttn_console_url || '#';
  const mapElement = document.getElementById('gatewayMap');
  const tileLayer = document.getElementById('gatewayTiles');
  const markerLayer = document.getElementById('gatewayMarkers');
  const gatewayPopup = document.getElementById('gatewayPopup');
  const sensorMapElement = document.getElementById('sensorMap');
  const sensorTileLayer = document.getElementById('sensorTiles');
  const sensorMarkerLayer = document.getElementById('sensorMarkers');
  const sensorPopup = document.getElementById('sensorPopup');
  const tileSize = 256;
  const mapState = { latitude: -34.45, longitude: -70.85, zoom: 9, initialized: false, dragging: false, pointerId: null, lastX: 0, lastY: 0 };
  const regionBounds = { minLatitude: -35.15, maxLatitude: -33.70, minLongitude: -72.20, maxLongitude: -69.25 };
  let lastTileKey = '';
  let lastGateways = [];
  let lastSensors = [];
  let selectedSensorApplication = '';
  let sensorLastTileKey = '';
  const sensorMapState = { latitude: -34.425, longitude: -70.725, zoom: 8, initialized: false, dragging: false, pointerId: null, lastX: 0, lastY: 0 };
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const clampLatitude = value => clamp(value, -85.05112878, 85.05112878);

  function project(latitude, longitude, zoom) {
    const scale = tileSize * (2 ** zoom);
    const lat = clampLatitude(latitude) * Math.PI / 180;
    return { x: ((longitude + 180) / 360) * scale, y: (1 - Math.log(Math.tan(lat) + (1 / Math.cos(lat))) / Math.PI) / 2 * scale };
  }

  function unproject(x, y, zoom) {
    const scale = tileSize * (2 ** zoom);
    const longitude = x / scale * 360 - 180;
    const n = Math.PI - 2 * Math.PI * y / scale;
    return { latitude: 180 / Math.PI * Math.atan(Math.sinh(n)), longitude };
  }

  function fitZoomFor(element, located, includeRegion = true) {
    const width = element.clientWidth || 1000;
    const height = element.clientHeight || 520;
    // Keep the initial view framed on the Libertador Bernardo O'Higgins
    // region, while still ensuring all located gateways remain visible.
    const lons = [
      ...(includeRegion ? [regionBounds.minLongitude, regionBounds.maxLongitude] : []),
      ...located.map(g => Number(g.longitude)),
    ];
    const lats = [
      ...(includeRegion ? [regionBounds.minLatitude, regionBounds.maxLatitude] : []),
      ...located.map(g => Number(g.latitude)),
    ];
    const lonSpan = Math.max(Math.max(...lons) - Math.min(...lons), .03) * 1.35;
    const latSpan = Math.max(Math.max(...lats) - Math.min(...lats), .03) * 1.35;
    return clamp(Math.floor(Math.min(Math.log2(360 * width / (tileSize * lonSpan)), Math.log2(170 * height / (tileSize * latSpan)))), 8, 16);
  }

  function fitZoom(located) {
    return fitZoomFor(mapElement, located);
  }

  function positionTiles(topLeft) {
    tileLayer.querySelectorAll('img').forEach(image => {
      image.style.left = `${Number(image.dataset.tileX) * tileSize - topLeft.x}px`;
      image.style.top = `${Number(image.dataset.tileY) * tileSize - topLeft.y}px`;
    });
  }

  function hideGatewayPopup() {
    gatewayPopup.hidden = true;
  }

  function showGatewayPopup(gateway, left, top) {
    document.getElementById('gatewayPopupName').textContent = gateway.display_name || gateway.gateway_id || '-';
    const status = document.getElementById('gatewayPopupStatus');
    status.textContent = gateway.online ? 'ONLINE' : 'OFFLINE';
    status.className = gateway.online ? 'online' : 'offline';
    document.getElementById('gatewayPopupLastSeen').textContent = date(gateway.last_seen_at);
    document.getElementById('gatewayPopupCoordinates').textContent = hasLocation(gateway) ? `${Number(gateway.latitude).toFixed(5)}, ${Number(gateway.longitude).toFixed(5)}` : '-';
    document.getElementById('gatewayPopupTtnLink').href = ttnConsoleUrl(gateway);
    document.getElementById('gatewayPopupMapLink').href = googleMapsUrl(gateway);
    gatewayPopup.style.left = `${left}px`;
    gatewayPopup.style.top = `${top}px`;
    gatewayPopup.hidden = false;
  }

  function renderLiveMap(gateways) {
    const located = gateways.filter(hasLocation);
    const note = document.getElementById('mapNote');
    if (!mapState.initialized && located.length) {
      mapState.latitude = (regionBounds.minLatitude + regionBounds.maxLatitude) / 2;
      mapState.longitude = (regionBounds.minLongitude + regionBounds.maxLongitude) / 2;
      mapState.zoom = clamp(fitZoom(located) + 1, 8, 16);
      mapState.initialized = true;
    }

    const width = mapElement.clientWidth || 1000;
    const height = mapElement.clientHeight || 520;
    const center = project(mapState.latitude, mapState.longitude, mapState.zoom);
    const topLeft = { x: center.x - width / 2, y: center.y - height / 2 };
    const worldTiles = 2 ** mapState.zoom;
    const firstX = Math.floor(topLeft.x / tileSize);
    const lastX = Math.floor((topLeft.x + width) / tileSize);
    const firstY = Math.floor(topLeft.y / tileSize);
    const lastY = Math.floor((topLeft.y + height) / tileSize);
    const tileKey = `${mapState.zoom}:${firstX}:${lastX}:${firstY}:${lastY}:${width}:${height}`;

    if (tileKey !== lastTileKey) {
      lastTileKey = tileKey;
      tileLayer.replaceChildren();
      for (let tileX = firstX; tileX <= lastX; tileX++) {
        for (let tileY = firstY; tileY <= lastY; tileY++) {
          if (tileY < 0 || tileY >= worldTiles) continue;
          const wrappedX = ((tileX % worldTiles) + worldTiles) % worldTiles;
          const image = document.createElement('img');
          image.src = `https://tile.openstreetmap.org/${mapState.zoom}/${wrappedX}/${tileY}.png`;
          image.alt = '';
          image.dataset.tileX = tileX;
          image.dataset.tileY = tileY;
          image.addEventListener('error', () => { note.textContent = 'No se pudo cargar el mapa en vivo de OpenStreetMap. Verifica la conexión del navegador.'; }, {once: true});
          tileLayer.appendChild(image);
        }
      }
    }
    positionTiles(topLeft);

    markerLayer.replaceChildren();
    hideGatewayPopup();
    located.forEach(gateway => {
      const point = project(Number(gateway.latitude), Number(gateway.longitude), mapState.zoom);
      const pin = document.createElement('button');
      pin.type = 'button';
      pin.className = `gateway-pin ${gateway.online ? 'online' : 'offline'}`;
      pin.style.left = `${point.x - topLeft.x}px`;
      pin.style.top = `${point.y - topLeft.y}px`;
      pin.title = `${gateway.display_name || gateway.gateway_id} — ${gateway.online ? 'ONLINE' : 'OFFLINE'}`;
      pin.setAttribute('aria-label', pin.title);
      pin.addEventListener('pointerdown', event => event.stopPropagation());
      pin.addEventListener('click', event => {
        event.stopPropagation();
        showGatewayPopup(gateway, point.x - topLeft.x, point.y - topLeft.y);
      });
      markerLayer.appendChild(pin);
    });
    note.textContent = `${located.length} gateway(s) con coordenadas. Azul: online · Rojo: offline. Mapa en vivo: OpenStreetMap.`;
  }

  function hideSensorPopup() {
    sensorPopup.hidden = true;
  }

  function visibleSensors() {
    return lastSensors.filter(sensor => hasLocation(sensor) && (
      !selectedSensorApplication || sensor.application_id === selectedSensorApplication
    ));
  }

  function updateSensorApplicationOptions(sensors) {
    const select = document.getElementById('sensorApplicationFilter');
    const applications = [...new Set(sensors.map(sensor => sensor.application_id).filter(Boolean))].sort();
    const current = selectedSensorApplication;
    select.replaceChildren(new Option('Todos los beneficiarios/campos', ''));
    applications.forEach(application => select.appendChild(new Option(application, application)));
    if (applications.includes(current)) {
      select.value = current;
    } else {
      selectedSensorApplication = '';
      select.value = '';
    }
  }

  function updatePageTitle(tabId) {
    const sensorsActive = tabId === 'sensorView';
    const title = sensorsActive ? 'Monitoreo de sensores' : 'Monitoreo de gateways';
    document.getElementById('pageTitle').textContent = title;
    document.title = `FIC Cerezas — ${title}`;
  }

  function showSensorPopup(sensor, left, top) {
    document.getElementById('sensorPopupName').textContent = sensor.display_name || sensor.device_id || '-';
    const status = document.getElementById('sensorPopupStatus');
    status.textContent = sensor.online ? 'ONLINE' : 'OFFLINE';
    status.className = sensor.online ? 'online' : 'offline';
    const applicationLink = document.getElementById('sensorPopupApplication');
    applicationLink.textContent = sensor.application_id || '-';
    applicationLink.href = sensor.ttn_application_url || '#';
    document.getElementById('sensorPopupLastSeen').textContent = date(sensor.last_seen_at);
    const located = hasLocation(sensor);
    document.getElementById('sensorPopupCoordinates').textContent = located ? `${Number(sensor.latitude).toFixed(5)}, ${Number(sensor.longitude).toFixed(5)}` : '-';
    document.getElementById('sensorPopupTtnLink').href = sensor.ttn_console_url || '#';
    const mapLink = document.getElementById('sensorPopupMapLink');
    mapLink.href = located ? googleMapsUrl(sensor) : '#';
    mapLink.hidden = !located;
    sensorPopup.style.left = `${left}px`;
    sensorPopup.style.top = `${top}px`;
    sensorPopup.hidden = false;
  }

  function renderSensorMap(sensors) {
    const locatedSensors = sensors.filter(hasLocation);
    const note = document.getElementById('sensorMapNote');
    if (!sensorMapState.initialized) {
      if (selectedSensorApplication && locatedSensors.length) {
        const latitudes = locatedSensors.map(sensor => Number(sensor.latitude));
        const longitudes = locatedSensors.map(sensor => Number(sensor.longitude));
        sensorMapState.latitude = (Math.min(...latitudes) + Math.max(...latitudes)) / 2;
        sensorMapState.longitude = (Math.min(...longitudes) + Math.max(...longitudes)) / 2;
        sensorMapState.zoom = clamp(fitZoomFor(sensorMapElement, locatedSensors, false) + 1, 8, 18);
      } else {
        sensorMapState.latitude = (regionBounds.minLatitude + regionBounds.maxLatitude) / 2;
        sensorMapState.longitude = (regionBounds.minLongitude + regionBounds.maxLongitude) / 2;
        sensorMapState.zoom = locatedSensors.length ? clamp(fitZoomFor(sensorMapElement, locatedSensors) + 1, 8, 16) : 8;
      }
      sensorMapState.initialized = true;
    }

    const width = sensorMapElement.clientWidth || 1000;
    const height = sensorMapElement.clientHeight || 520;
    const center = project(sensorMapState.latitude, sensorMapState.longitude, sensorMapState.zoom);
    const topLeft = { x: center.x - width / 2, y: center.y - height / 2 };
    const worldTiles = 2 ** sensorMapState.zoom;
    const firstX = Math.floor(topLeft.x / tileSize);
    const lastX = Math.floor((topLeft.x + width) / tileSize);
    const firstY = Math.floor(topLeft.y / tileSize);
    const lastY = Math.floor((topLeft.y + height) / tileSize);
    const tileKey = `${sensorMapState.zoom}:${firstX}:${lastX}:${firstY}:${lastY}:${width}:${height}`;

    if (tileKey !== sensorLastTileKey) {
      sensorLastTileKey = tileKey;
      sensorTileLayer.replaceChildren();
      for (let tileX = firstX; tileX <= lastX; tileX++) {
        for (let tileY = firstY; tileY <= lastY; tileY++) {
          if (tileY < 0 || tileY >= worldTiles) continue;
          const wrappedX = ((tileX % worldTiles) + worldTiles) % worldTiles;
          const image = document.createElement('img');
          image.src = `https://tile.openstreetmap.org/${sensorMapState.zoom}/${wrappedX}/${tileY}.png`;
          image.alt = '';
          image.dataset.tileX = tileX;
          image.dataset.tileY = tileY;
          image.addEventListener('error', () => { note.textContent = 'No se pudo cargar el mapa en vivo de OpenStreetMap. Verifica la conexión del navegador.'; }, {once: true});
          sensorTileLayer.appendChild(image);
        }
      }
    }
    sensorTileLayer.querySelectorAll('img').forEach(image => {
      image.style.left = `${Number(image.dataset.tileX) * tileSize - topLeft.x}px`;
      image.style.top = `${Number(image.dataset.tileY) * tileSize - topLeft.y}px`;
    });

    sensorMarkerLayer.replaceChildren();
    hideSensorPopup();
    locatedSensors.forEach(sensor => {
      const point = project(Number(sensor.latitude), Number(sensor.longitude), sensorMapState.zoom);
      const pin = document.createElement('button');
      pin.type = 'button';
      pin.className = `gateway-pin ${sensor.online ? 'online' : 'offline'}`;
      pin.style.left = `${point.x - topLeft.x}px`;
      pin.style.top = `${point.y - topLeft.y}px`;
      pin.title = `${sensor.display_name || sensor.device_id} — ${sensor.online ? 'ONLINE' : 'OFFLINE'}`;
      pin.setAttribute('aria-label', pin.title);
      pin.addEventListener('pointerdown', event => event.stopPropagation());
      pin.addEventListener('click', event => {
        event.stopPropagation();
        showSensorPopup(sensor, point.x - topLeft.x, point.y - topLeft.y);
      });
      sensorMarkerLayer.appendChild(pin);
    });
    note.textContent = locatedSensors.length
      ? `${locatedSensors.length} sensor(es) mostrados con coordenadas en TTN. Azul: online · Rojo: offline. Mapa en vivo: OpenStreetMap.`
      : 'No hay sensores con coordenadas para este filtro. Se muestra la Región del Libertador Bernardo O’Higgins.';
  }

  function zoomMap(delta) {
    mapState.zoom = clamp(mapState.zoom + delta, 3, 18);
    renderLiveMap(lastGateways);
  }

  const zoomIn = document.getElementById('zoomIn');
  const zoomOut = document.getElementById('zoomOut');
  zoomIn.addEventListener('pointerdown', event => event.stopPropagation());
  zoomOut.addEventListener('pointerdown', event => event.stopPropagation());
  zoomIn.addEventListener('click', event => { event.stopPropagation(); zoomMap(1); });
  zoomOut.addEventListener('click', event => { event.stopPropagation(); zoomMap(-1); });
  document.getElementById('gatewayPopupClose').addEventListener('click', event => { event.stopPropagation(); hideGatewayPopup(); });
  gatewayPopup.addEventListener('pointerdown', event => event.stopPropagation());
  mapElement.addEventListener('wheel', event => { event.preventDefault(); zoomMap(event.deltaY < 0 ? 1 : -1); }, {passive: false});
  mapElement.addEventListener('pointerdown', event => {
    if (event.target.closest('button, a')) return;
    mapState.dragging = true;
    mapState.pointerId = event.pointerId;
    mapState.lastX = event.clientX;
    mapState.lastY = event.clientY;
    mapElement.classList.add('dragging');
    mapElement.setPointerCapture(event.pointerId);
  });
  mapElement.addEventListener('pointermove', event => {
    if (!mapState.dragging || event.pointerId !== mapState.pointerId) return;
    const center = project(mapState.latitude, mapState.longitude, mapState.zoom);
    const next = unproject(center.x - (event.clientX - mapState.lastX), center.y - (event.clientY - mapState.lastY), mapState.zoom);
    mapState.latitude = next.latitude;
    mapState.longitude = next.longitude;
    mapState.lastX = event.clientX;
    mapState.lastY = event.clientY;
    renderLiveMap(lastGateways);
  });
  mapElement.addEventListener('pointerup', event => { if (event.pointerId === mapState.pointerId) { mapState.dragging = false; mapElement.classList.remove('dragging'); } });
  mapElement.addEventListener('pointercancel', () => { mapState.dragging = false; mapElement.classList.remove('dragging'); });

  function sensorZoomMap(delta) {
    sensorMapState.zoom = clamp(sensorMapState.zoom + delta, 3, 18);
    renderSensorMap(visibleSensors());
  }

  const sensorZoomIn = document.getElementById('sensorZoomIn');
  const sensorZoomOut = document.getElementById('sensorZoomOut');
  sensorZoomIn.addEventListener('pointerdown', event => event.stopPropagation());
  sensorZoomOut.addEventListener('pointerdown', event => event.stopPropagation());
  sensorZoomIn.addEventListener('click', event => { event.stopPropagation(); sensorZoomMap(1); });
  sensorZoomOut.addEventListener('click', event => { event.stopPropagation(); sensorZoomMap(-1); });
  document.getElementById('sensorPopupClose').addEventListener('click', event => { event.stopPropagation(); hideSensorPopup(); });
  sensorPopup.addEventListener('pointerdown', event => event.stopPropagation());
  sensorMapElement.addEventListener('wheel', event => { event.preventDefault(); sensorZoomMap(event.deltaY < 0 ? 1 : -1); }, {passive: false});
  sensorMapElement.addEventListener('pointerdown', event => {
    if (event.target.closest('button, a')) return;
    sensorMapState.dragging = true;
    sensorMapState.pointerId = event.pointerId;
    sensorMapState.lastX = event.clientX;
    sensorMapState.lastY = event.clientY;
    sensorMapElement.classList.add('dragging');
    sensorMapElement.setPointerCapture(event.pointerId);
  });
  sensorMapElement.addEventListener('pointermove', event => {
    if (!sensorMapState.dragging || event.pointerId !== sensorMapState.pointerId) return;
    const center = project(sensorMapState.latitude, sensorMapState.longitude, sensorMapState.zoom);
    const next = unproject(center.x - (event.clientX - sensorMapState.lastX), center.y - (event.clientY - sensorMapState.lastY), sensorMapState.zoom);
    sensorMapState.latitude = next.latitude;
    sensorMapState.longitude = next.longitude;
    sensorMapState.lastX = event.clientX;
    sensorMapState.lastY = event.clientY;
    renderSensorMap(visibleSensors());
  });
  sensorMapElement.addEventListener('pointerup', event => { if (event.pointerId === sensorMapState.pointerId) { sensorMapState.dragging = false; sensorMapElement.classList.remove('dragging'); } });
  sensorMapElement.addEventListener('pointercancel', () => { sensorMapState.dragging = false; sensorMapElement.classList.remove('dragging'); });

  document.getElementById('sensorApplicationFilter').addEventListener('change', event => {
    selectedSensorApplication = event.target.value;
    sensorMapState.initialized = false;
    const filtered = visibleSensors();
    renderSensorMap(filtered);
    renderSensorRows(filtered);
    updateSensorSummary(filtered);
  });

  function updateSensorSummary(sensors) {
    for (const [id, value] of Object.entries({
      sensorsTotal: sensors.length,
      sensorsOnline: sensors.filter(sensor => sensor.online).length,
      sensorsOffline: sensors.filter(sensor => !sensor.online).length,
    })) document.getElementById(id).textContent = value;
  }

  function renderSensorRows(sensors) {
    document.getElementById('sensorRows').innerHTML = sensors.map(sensor => `<tr><td>${esc(sensor.device_id)}</td><td>${esc(sensor.sensor_type || 'No especificado')}</td><td><a href="${sensor.ttn_application_url || '#'}" target="_blank" rel="noopener noreferrer">${esc(sensor.application_id)}</a></td><td class="${sensor.online ? 'online' : 'offline'}">${sensor.online ? 'ONLINE' : 'OFFLINE'}</td><td>${date(sensor.last_seen_at)}</td><td><a href="${googleMapsUrl(sensor)}" target="_blank" rel="noopener noreferrer">${Number(sensor.latitude).toFixed(5)}, ${Number(sensor.longitude).toFixed(5)}</a></td><td><a href="${sensor.ttn_console_url || '#'}" target="_blank" rel="noopener noreferrer">Abrir TTN Cloud</a></td></tr>`).join('');
  }

  document.querySelectorAll('[data-tab]').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('[data-tab]').forEach(item => item.classList.toggle('active', item === button));
      document.querySelectorAll('.tab-panel').forEach(panel => { panel.hidden = panel.id !== button.dataset.tab; });
      updatePageTitle(button.dataset.tab);
      if (button.dataset.tab === 'sensorView') renderSensorMap(visibleSensors());
      else renderLiveMap(lastGateways);
    });
  });

  async function refresh() {
    const data = await fetch(`${basePath}/api/status`).then(response => response.json());
    const s = data.summary;
    lastGateways = data.gateways;
    lastSensors = data.sensors || [];
    updateSensorApplicationOptions(lastSensors);
    for (const [id, value] of Object.entries({gatewaysTotal:s.gateways_total, gatewaysOnline:s.gateways_online, gatewaysOffline:s.gateways_offline})) document.getElementById(id).textContent = value;
    document.getElementById('updated').textContent = `Actualizado: ${date(data.generated_at)}${data.error ? ` · Error: ${data.error}` : ''}`;
    renderLiveMap(data.gateways);
    document.getElementById('gatewayRows').innerHTML = data.gateways.map(g => `<tr><td>${esc(g.gateway_id)}</td><td>${esc(g.display_name)}</td><td class="${g.online ? 'online' : 'offline'}">${g.online ? 'ONLINE' : 'OFFLINE'}</td><td>${date(g.last_seen_at)}</td><td>${hasLocation(g) ? `<a href="${googleMapsUrl(g)}" target="_blank" rel="noopener noreferrer">${Number(g.latitude).toFixed(5)}, ${Number(g.longitude).toFixed(5)}</a>` : '-'}</td><td><a href="${ttnConsoleUrl(g)}" target="_blank" rel="noopener noreferrer">Abrir TTN Cloud</a></td></tr>`).join('');
    const filteredSensors = visibleSensors();
    updateSensorSummary(filteredSensors);
    renderSensorMap(filteredSensors);
    renderSensorRows(filteredSensors);
  }

  refresh().catch(error => { document.getElementById('updated').textContent = `Error: ${error}`; });
  setInterval(() => refresh().catch(() => {}), 30000);
})();
