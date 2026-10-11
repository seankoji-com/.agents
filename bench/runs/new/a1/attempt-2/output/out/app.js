(function () {
  'use strict';
  var D = window.E10_DATA;
  if (!D) { return; }
  var byId = {};
  D.stations.forEach(function (s) { byId[s.id] = s; });

  function fmt(v, digits) { return v === null || v === undefined ? '—' : Number(v).toFixed(digits); }
  function dayLabel(iso) {
    var m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return parseInt(iso.slice(8, 10), 10) + ' ' + m[parseInt(iso.slice(5, 7), 10) - 1];
  }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  // ---- map ----
  var markers = {};
  var map = null;
  var mapEl = document.getElementById('map');
  if (mapEl && window.L) {
    map = L.map(mapEl, { scrollWheelZoom: false });
    L.tileLayer(mapEl.getAttribute('data-tile-url'), {
      maxZoom: 19,
      attribution: mapEl.getAttribute('data-attribution')
    }).addTo(map);
    var centre = L.latLng(D.centre.lat, D.centre.lon);
    // Fit before adding layers: a circle's getBounds() needs a map that already has a view.
    map.fitBounds(centre.toBounds(D.radius_km * 2000), { padding: [4, 4] });
    L.circle(centre, {
      radius: D.radius_km * 1000, color: '#2a78d6', weight: 1.5, fillOpacity: 0.04, interactive: false
    }).addTo(map);
    L.circleMarker(centre, {
      radius: 5, color: '#ffffff', weight: 2, fillColor: '#0b0b0b', fillOpacity: 1
    }).bindTooltip('Greenwich (search centre)').addTo(map);

    D.stations.forEach(function (s) {
      var best = s.id === D.recommendation.station_id;
      var label = fmt(s.listed_price_cpl, 1);
      var icon = L.divIcon({
        className: 'price-pin' + (best ? ' is-best' : ''),
        html: '<span>' + (best ? '★ ' : '') + label + '</span>',
        // The icon box is the visible label (sitting just above the point), so focus outlines wrap it.
        iconSize: best ? [70, 24] : [52, 22], iconAnchor: best ? [35, 30] : [26, 28], popupAnchor: [0, -30]
      });
      var popup = el('div');
      popup.appendChild(el('p', null, '')).appendChild(el('strong', null, s.name));
      popup.appendChild(el('p', null, s.brand + ' · ' + s.address));
      popup.appendChild(el('p', null, 'E10 ' + label + ' c/L · ' + fmt(s.distance_km, 2) + ' km'));
      if (best) { popup.appendChild(el('p', null, 'Cheapest E10 in range')); }
      var marker = L.marker([s.lat, s.lon], {
        icon: icon, title: s.name + ': ' + label + ' c/L', alt: s.name,
        keyboard: true, riseOnHover: true, zIndexOffset: best ? 1000 : 0
      }).bindPopup(popup).addTo(map);
      marker.on('popupopen', function () { setActive(s.id); });
      markers[s.id] = marker;
    });
  }

  function setActive(id) {
    var items = document.querySelectorAll('#station-list > li');
    for (var i = 0; i < items.length; i++) {
      items[i].classList.toggle('is-active', items[i].getAttribute('data-station-id') === id);
    }
  }

  document.addEventListener('click', function (event) {
    var target = event.target.closest ? event.target.closest('[data-show]') : null;
    if (!target) { return; }
    var id = target.getAttribute('data-show');
    setActive(id);
    if (map && markers[id]) {
      mapEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      map.setView(markers[id].getLatLng(), 15);
      markers[id].openPopup();
    }
  });

  // ---- sorting ----
  var list = document.getElementById('station-list');
  var sortButtons = document.querySelectorAll('[data-sort]');
  function sortBy(key) {
    var items = Array.prototype.slice.call(list.children);
    items.sort(function (a, b) {
      var pa = parseFloat(a.getAttribute('data-price')), pb = parseFloat(b.getAttribute('data-price'));
      var da = parseFloat(a.getAttribute('data-distance')), db = parseFloat(b.getAttribute('data-distance'));
      if (isNaN(pa)) { pa = Infinity; }
      if (isNaN(pb)) { pb = Infinity; }
      return key === 'distance' ? (da - db) || (pa - pb) : (pa - pb) || (da - db);
    });
    items.forEach(function (item, i) {
      item.querySelector('.rank').textContent = String(i + 1);
      list.appendChild(item);
    });
    for (var i = 0; i < sortButtons.length; i++) {
      sortButtons[i].setAttribute('aria-pressed', String(sortButtons[i].getAttribute('data-sort') === key));
    }
  }
  for (var i = 0; i < sortButtons.length; i++) {
    sortButtons[i].addEventListener('click', function () { sortBy(this.getAttribute('data-sort')); });
  }

  // ---- overall chart crosshair + tooltip ----
  var wrap = document.getElementById('overall-chart');
  if (wrap) {
    var svg = wrap.querySelector('svg');
    var hit = svg.querySelector('.hit');
    var cross = svg.querySelector('.crosshair');
    var tip = wrap.querySelector('.tooltip');
    var readout = document.getElementById('overall-readout');
    var points = D.overall_history;
    var left = parseFloat(hit.getAttribute('data-left'));
    var width = parseFloat(hit.getAttribute('data-width'));
    var circles = svg.querySelectorAll('.point');
    var current = points.length - 1;
    function xAt(i) { return points.length > 1 ? left + width * i / (points.length - 1) : left + width / 2; }
    function show(i, announce) {
      current = Math.max(0, Math.min(points.length - 1, i));
      var p = points[current];
      var x = xAt(current);
      cross.setAttribute('x1', x);
      cross.setAttribute('x2', x);
      cross.removeAttribute('hidden');
      tip.textContent = '';
      tip.appendChild(el('strong', null, fmt(p.mean_price_cpl, 2) + ' c/L'));
      tip.appendChild(el('span', null, 'Mean on ' + dayLabel(p.date)));
      var box = svg.getBoundingClientRect();
      var scale = box.width / svg.viewBox.baseVal.width;
      var cy = circles[current] ? parseFloat(circles[current].getAttribute('cy')) : 40;
      tip.style.left = (x * scale) + 'px';
      tip.style.top = (cy * scale - 8) + 'px';
      tip.hidden = false;
      if (announce && readout) {
        readout.textContent = 'Mean on ' + dayLabel(p.date) + ': ' + fmt(p.mean_price_cpl, 2) + ' cents per litre';
      }
    }
    function hide() { cross.setAttribute('hidden', ''); tip.hidden = true; }
    hit.addEventListener('pointermove', function (event) {
      var box = svg.getBoundingClientRect();
      var x = (event.clientX - box.left) / (box.width / svg.viewBox.baseVal.width);
      show(Math.round((x - left) / width * (points.length - 1)));
    });
    hit.addEventListener('pointerleave', hide);
    wrap.addEventListener('focus', function () { show(current, true); });
    wrap.addEventListener('blur', hide);
    wrap.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowLeft') { show(current - 1, true); event.preventDefault(); }
      if (event.key === 'ArrowRight') { show(current + 1, true); event.preventDefault(); }
      if (event.key === 'Escape') { hide(); }
    });
  }
})();
