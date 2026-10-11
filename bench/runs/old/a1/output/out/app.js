/* Map, sorting and chart tooltip for index.html. Reads window.FUEL_DATA from data.js.
   Classic script (not a module) so the page works when opened from disk. */
(function () {
  'use strict';

  var data = window.FUEL_DATA;
  var DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var markers = {};
  var map = null;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function cpl(value) {
    return value === null || value === undefined ? 'no price' : value.toFixed(1);
  }

  // A recorded_at timestamp as written, without converting time zones.
  function when(text) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(text);
    if (!m) return text;
    var year = +m[1], month = +m[2], day = +m[3], hour = +m[4];
    var weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
    return DAYS[weekday] + ' ' + day + ' ' + MONTHS[month - 1] + ', ' +
      (hour % 12 || 12) + ':' + m[5] + ' ' + (hour < 12 ? 'am' : 'pm');
  }

  function popup(station, isBest) {
    var box = el('div', 'popup');
    if (isBest) box.appendChild(el('p', 'popup-badge', 'Cheapest listed E10'));
    box.appendChild(el('p', 'popup-name', station.name));
    box.appendChild(el('p', 'popup-meta', station.brand + ' · ' + station.address));
    box.appendChild(el('p', 'popup-price', cpl(station.listed_price_cpl) + ' c/L · ' +
      station.distance_km.toFixed(2) + ' km'));
    var last = station.history[station.history.length - 1];
    if (last) box.appendChild(el('p', 'popup-meta', 'Listed ' + when(last.recorded_at)));
    var link = el('a', 'popup-link', 'Price history');
    link.href = '#station-' + station.id;
    box.appendChild(link);
    return box;
  }

  function initMap() {
    var node = document.getElementById('map');
    if (!node) return;
    if (!window.L || !data) {
      node.classList.add('map-unavailable');
      node.textContent = 'The map could not load. The station list below has every station.';
      return;
    }
    var centre = [parseFloat(node.getAttribute('data-centre-lat')), parseFloat(node.getAttribute('data-centre-lon'))];
    var radiusKm = parseFloat(node.getAttribute('data-radius-km'));
    var best = data.recommendation ? data.recommendation.station_id : null;

    // Fractional zoom lets fitBounds get closer, which spreads the price pins out.
    map = L.map(node, { scrollWheelZoom: false, zoomSnap: 0.25 });
    L.tileLayer(node.getAttribute('data-tile-url'), {
      maxZoom: 19,
      attribution: node.getAttribute('data-attribution')
    }).addTo(map);

    L.circle(centre, {
      radius: radiusKm * 1000, color: '#52514e', weight: 1, dashArray: '4 4', fill: false, interactive: false
    }).addTo(map);
    L.circleMarker(centre, {
      radius: 5, color: '#fcfcfb', weight: 2, fillColor: '#0b0b0b', fillOpacity: 1
    }).bindTooltip('Search centre: Greenwich').addTo(map);

    var bounds = [centre];
    data.stations.forEach(function (station) {
      var isBest = station.id === best;
      var label = (isBest ? 'Cheapest ' : '') + cpl(station.listed_price_cpl);
      var icon = L.divIcon({
        className: 'pin' + (isBest ? ' pin-best' : ''),
        html: '<span class="pin-label">' + label + '</span>',
        iconSize: null
      });
      var marker = L.marker([station.lat, station.lon], {
        icon: icon,
        title: station.name + ', ' + cpl(station.listed_price_cpl) + ' c/L',
        alt: station.name,
        riseOnHover: true,
        zIndexOffset: isBest ? 1000 : 0
      }).bindPopup(popup(station, isBest)).addTo(map);
      markers[station.id] = marker;
      bounds.push([station.lat, station.lon]);
    });
    map.fitBounds(L.latLngBounds(bounds).pad(0.06));
  }

  function initLocate() {
    var list = document.getElementById('station-list');
    if (!list || !map) return;
    Array.prototype.forEach.call(list.querySelectorAll('.st-locate'), function (button) {
      button.hidden = false;
    });
    list.addEventListener('click', function (event) {
      var button = event.target.closest('.st-locate');
      if (!button) return;
      var marker = markers[button.getAttribute('data-station-id')];
      if (!marker) return;
      document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });
      map.setView(marker.getLatLng(), Math.max(map.getZoom(), 14));
      marker.openPopup();
    });
  }

  function initSort() {
    var group = document.querySelector('.sort');
    var list = document.getElementById('station-list');
    if (!group || !list) return;
    group.hidden = false;
    group.addEventListener('click', function (event) {
      var button = event.target.closest('button[data-sort]');
      if (!button) return;
      var key = button.getAttribute('data-sort');
      var items = Array.prototype.slice.call(list.children);
      function value(item, name) {
        var raw = item.getAttribute('data-' + name);
        return raw === '' ? Infinity : parseFloat(raw);
      }
      items.sort(function (a, b) {
        var primary = key === 'price' ? ['price', 'distance'] : ['distance', 'price'];
        for (var i = 0; i < primary.length; i++) {
          var diff = value(a, primary[i]) - value(b, primary[i]);
          if (diff) return diff;
        }
        return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
      });
      items.forEach(function (item) { list.appendChild(item); });
      Array.prototype.forEach.call(group.querySelectorAll('button'), function (other) {
        other.setAttribute('aria-pressed', other === button ? 'true' : 'false');
      });
    });
  }

  function initChartTooltip() {
    var svg = document.getElementById('overall-chart');
    var tip = document.getElementById('overall-tooltip');
    var line = document.getElementById('overall-crosshair');
    if (!svg || !tip || !line || !svg.createSVGPoint) return;
    var points = Array.prototype.slice.call(svg.querySelectorAll('.series-point'));
    if (!points.length) return;

    function show(event) {
      var ctm = svg.getScreenCTM();
      if (!ctm) return;
      var pt = svg.createSVGPoint();
      pt.x = event.clientX;
      pt.y = event.clientY;
      var local = pt.matrixTransform(ctm.inverse());
      var nearest = points[0];
      points.forEach(function (p) {
        if (Math.abs(p.cx.baseVal.value - local.x) < Math.abs(nearest.cx.baseVal.value - local.x)) nearest = p;
      });
      points.forEach(function (p) { p.classList.toggle('is-active', p === nearest); });
      var x = nearest.cx.baseVal.value;
      line.setAttribute('x1', x);
      line.setAttribute('x2', x);
      line.setAttribute('visibility', 'visible');
      tip.textContent = '';
      tip.appendChild(el('span', 'tip-label', nearest.getAttribute('data-label')));
      tip.appendChild(el('span', 'tip-value', nearest.getAttribute('data-value') + ' c/L'));
      tip.hidden = false;
      var box = svg.getBoundingClientRect();
      var scale = box.width / svg.viewBox.baseVal.width;
      var left = x * scale;
      var maxLeft = box.width - tip.offsetWidth;
      tip.style.left = Math.max(0, Math.min(maxLeft, left - tip.offsetWidth / 2)) + 'px';
      tip.style.top = Math.max(0, nearest.cy.baseVal.value * scale - tip.offsetHeight - 12) + 'px';
    }

    function hide() {
      tip.hidden = true;
      line.setAttribute('visibility', 'hidden');
      points.forEach(function (p) { p.classList.remove('is-active'); });
    }

    svg.addEventListener('pointermove', show);
    svg.addEventListener('pointerleave', hide);
  }

  initMap();
  initLocate();
  initSort();
  initChartTooltip();
})();
