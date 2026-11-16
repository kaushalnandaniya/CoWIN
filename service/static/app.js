/* Dependency-free, same-origin lookup. No polling or administrative controls. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const form = $('search-form');
  let pending = false;
  let lastFilters = { district: '', pincode: '' };

  function text(tag, value, className) {
    const element = document.createElement(tag);
    element.textContent = value;
    if (className) element.className = className;
    return element;
  }

  function renderCenter(center) {
    const card = $('center-template').content.cloneNode(true);
    card.querySelector('.district-tag').textContent = center.district_name || 'District not listed';
    card.querySelector('.fee-tag').textContent = center.fee_type || 'Fee not listed';
    card.querySelector('h3').textContent = center.name || 'Unnamed center';
    card.querySelector('.address').textContent = center.address || 'Address not listed';
    card.querySelector('.location').textContent = [center.state_name, center.pincode].filter(Boolean).join(' / ');
    card.querySelector('.center-hours').textContent = `Hours: ${(center.from_time || '').slice(0, 5) || 'Not listed'} - ${(center.to_time || '').slice(0, 5) || 'Not listed'}`;
    const sessions = card.querySelector('.sessions');
    for (const session of Array.isArray(center.sessions) ? center.sessions : []) {
      const row = text('div', '', 'session');
      const top = text('div', '', 'session-top');
      top.append(text('span', session.vaccine || 'Vaccine not listed'), text('span', `${session.min_age_limit ?? '?'}+ years`));
      row.append(top, text('span', `${session.date || 'Date not listed'} · Sample capacity: ${session.available_capacity ?? 'Not listed'}`, 'session-detail'));
      sessions.append(row);
    }
    if (!sessions.childElementCount) sessions.append(text('p', 'No sample sessions listed.', 'session-detail'));
    return card;
  }

  function setBusy(busy) {
    pending = busy;
    $('results-section').setAttribute('aria-busy', String(busy));
    for (const id of ['search-button', 'reset-button', 'retry-button']) $(id).disabled = busy;
    $('search-button').firstChild.textContent = busy ? 'Searching... ' : 'Find centers ';
  }

  async function lookup(filters) {
    if (pending) return;
    lastFilters = { ...filters };
    setBusy(true);
    $('error').hidden = true;
    $('empty').hidden = true;
    $('centers').replaceChildren();
    $('result-count').textContent = 'Searching';
    $('status').textContent = 'Requesting sample centers from the API...';
    $('request-state').textContent = 'Lookup in progress';
    $('request-dot').style.background = '';
    $('zone').textContent = 'Waiting for response';
    $('instance').textContent = 'Waiting for response';
    $('timestamp').textContent = 'Waiting for response';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const params = new URLSearchParams();
      if (filters.district) params.set('district', filters.district);
      if (filters.pincode) params.set('pincode', filters.pincode);
      const response = await fetch(`/api/v1/centers${params.size ? `?${params}` : ''}`, { signal: controller.signal, cache: 'no-store' });
      if (!response.ok) {
        if (response.status === 429) throw new Error('Too many requests. Wait a moment, then try again.');
        throw new Error(`The API returned HTTP ${response.status}. Try again in a moment.`);
      }
      const data = await response.json();
      if (!Array.isArray(data.centers) || !data.centers.every(center => center && typeof center === 'object' && !Array.isArray(center))) throw new Error('The API returned an unexpected response. Please try again.');
      const fragment = document.createDocumentFragment();
      for (const center of data.centers) fragment.append(renderCenter(center));
      $('centers').append(fragment);
      $('empty').hidden = data.centers.length !== 0;
      $('result-count').textContent = `${data.centers.length} ${data.centers.length === 1 ? 'center' : 'centers'}`;
      const scope = [filters.district && `district "${filters.district}"`, filters.pincode && `pincode ${filters.pincode}`].filter(Boolean).join(' and ');
      const found = `${data.centers.length} sample ${data.centers.length === 1 ? 'center' : 'centers'}`;
      $('status').textContent = scope ? `${found} found for ${scope}.` : `Showing all ${data.centers.length} centers in the sample dataset.`;
      $('zone').textContent = data.served_by?.zone || 'Not reported';
      $('instance').textContent = data.served_by?.instance_id || 'Not reported';
      $('request-state').textContent = 'API responded';
      $('request-dot').style.background = '#126653';
      $('timestamp').textContent = new Date().toLocaleTimeString([], { hour12: false });
    } catch (error) {
      $('centers').replaceChildren();
      $('error').hidden = false;
      $('error-message').textContent = error.name === 'AbortError' ? 'The API took longer than 10 seconds to respond. Please try again.' : error instanceof TypeError ? 'Cannot reach the API. Check your connection, then try again.' : error instanceof SyntaxError ? 'The API returned an unreadable response. Please try again.' : error.message;
      $('result-count').textContent = 'Unavailable';
      $('status').textContent = 'No current results to display.';
      $('request-state').textContent = 'Lookup failed';
      $('zone').textContent = 'Unknown';
      $('instance').textContent = 'Unknown';
      $('timestamp').textContent = new Date().toLocaleTimeString([], { hour12: false });
    } finally {
      clearTimeout(timeout);
      setBusy(false);
    }
  }

  const PINCODE_RULE = /^[1-9][0-9]{5}$/;
  const PINCODE_MESSAGE = 'Enter a 6-digit pincode that starts with 1-9 (no leading zero), or leave the field blank.';

  function validatePincode(value) {
    const error = $('pincode-error');
    if (value === '' || PINCODE_RULE.test(value)) {
      error.hidden = true;
      error.textContent = '';
      $('pincode').removeAttribute('aria-invalid');
      return true;
    }
    error.textContent = PINCODE_MESSAGE;
    error.hidden = false;
    $('pincode').setAttribute('aria-invalid', 'true');
    $('pincode').focus();
    return false;
  }

  $('pincode').addEventListener('input', () => {
    if (!$('pincode-error').hidden) validatePincode($('pincode').value.trim());
  });

  form.addEventListener('submit', event => {
    event.preventDefault();
    const pincode = $('pincode').value.trim();
    if (!validatePincode(pincode)) return;
    lookup({ district: $('district').value.trim(), pincode });
  });
  $('reset-button').addEventListener('click', () => { form.reset(); lookup({ district: '', pincode: '' }); });
  $('retry-button').addEventListener('click', () => lookup(lastFilters));
  lookup(lastFilters);
})();
