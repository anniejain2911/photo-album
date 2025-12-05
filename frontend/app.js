(() => {
  const cfg = window.APP_CONFIG || {};
  const $ = (id) => document.getElementById(id);

  let apigClient = null;
  try {
    if (window.apigClientFactory) {
      apigClient = apigClientFactory.newClient({ apiKey: cfg.API_KEY || undefined });
    }
  } catch {}

  const authHeaders = (extra = {}) => {
    const h = { ...extra };
    if (cfg.API_KEY) h["x-api-key"] = cfg.API_KEY;
    return h;
  };

  const setText = (id, val) => { const el = $(id); if (el) el.textContent = val; };
  setText('env-region', cfg.REGION || '—');
  setText('cfg-region', cfg.REGION || '—');
  setText('cfg-bucket', cfg.BUCKET || '—');
  setText('cfg-root', cfg.API_ROOT || '—');
  setText('foot-bucket', cfg.BUCKET || '—');
  setText('cfg-key', cfg.API_KEY ? (cfg.API_KEY.slice(0,4) + '…' + cfg.API_KEY.slice(-4)) : '—');

  const fileInput = $('file');
  const drop = $('dropzone');
  const pick = $('pick');
  const preview = $('preview');
  const labels = $('labels');
  const uploadBtn = $('uploadBtn');
  const prog = $('prog');
  const status = $('status');
  const results = $('results');
  const q = $('q');
  const searchBtn = $('searchBtn');

  let currentFile = null;

  const setFile = (f) => {
    if (!f) return;
    currentFile = f;
    preview.src = URL.createObjectURL(f);
    preview.style.display = 'block';
    uploadBtn.disabled = false;
    status.textContent = '';
    prog.style.display = 'none';
  };

  pick.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', e => setFile(e.target.files?.[0]));

  ['dragenter','dragover'].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('drag'); })
  );
  ['dragleave','drop'].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('drag'); })
  );
  drop.addEventListener('drop', e => {
    const f = e.dataTransfer?.files?.[0];
    setFile(f);
  });

  const toastWrap = $('toasts');
  const toast = (msg, kind) => {
    const t = document.createElement('div');
    t.className = `toast ${kind||''}`;
    t.textContent = msg;
    toastWrap.appendChild(t);
    setTimeout(()=>{ t.style.opacity='0'; setTimeout(()=>t.remove(), 300); }, 1800);
  };

  const truncateMiddle = (s, n) => (s && s.length>n) ? s.slice(0, Math.max(0,n-10))+'…'+s.slice(-9) : (s||'');

  uploadBtn.addEventListener('click', async () => {
    if (!currentFile) return;
    const name = currentFile.name;
    const meta = (labels.value || '').trim();

    prog.style.display = 'inline-block';
    prog.value = 0;
    status.className = 'status';
    status.textContent = 'Uploading…';

    try {
      if (apigClient) {
        const params = { name: encodeURIComponent(name) };
        const body = currentFile;
        const additionalParams = {
          headers: {
            'Content-Type': currentFile.type || 'application/octet-stream',
            ...(meta ? { 'x-amz-meta-customlabels': meta } : {}),
            ...(cfg.API_KEY ? { 'x-api-key': cfg.API_KEY } : {})
          }
        };
        await apigClient.photosPut(params, body, additionalParams);
        prog.value = 100;
      } else {
        const url = `${cfg.API_ROOT}/photos?name=${encodeURIComponent(name)}`;
        await new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open('PUT', url, true);
          if (cfg.API_KEY) xhr.setRequestHeader('x-api-key', cfg.API_KEY);
          xhr.setRequestHeader('Content-Type', currentFile.type || 'application/octet-stream');
          if (meta) xhr.setRequestHeader('x-amz-meta-customlabels', meta);
          xhr.upload.onprogress = (e) => { if (e.lengthComputable) prog.value = Math.round((e.loaded/e.total)*100); };
          xhr.onload = () => (xhr.status >= 200 && xhr.status < 300) ? resolve() : reject(new Error(`HTTP ${xhr.status}`));
          xhr.onerror = () => reject(new Error('Network error'));
          xhr.send(currentFile);
        });
      }
      toast('Upload complete ✅', 'ok');
      status.className = 'status ok';
      status.textContent = 'Uploaded successfully.';
    } catch (e) {
      status.className = 'status err';
      status.textContent = `Upload failed: ${e.message || e}`;
      toast('Upload failed', 'err');
    }
  });

  const renderCard = (r) => {
    const url = r.url || `https://${(r.bucket||cfg.BUCKET)}.s3.${cfg.REGION}.amazonaws.com/${encodeURIComponent(r.objectKey||'')}`;
    const key = r.objectKey || (r.key || '');
    const bucket = r.bucket || cfg.BUCKET;
    return `
      <div class="card-img">
        <img src="${url}" alt="">
        <div class="meta">
          <div class="left">
            <div title="${key}">${truncateMiddle(key, 26)}</div>
            <div class="muted" title="${bucket}">${truncateMiddle(bucket, 26)}</div>
          </div>
          <div class="right">
            <span class="copy" data-url="${url}">Copy link</span>
            <a class="copy" href="${url}" target="_blank" rel="noopener">Open</a>
          </div>
        </div>
      </div>
    `;
  };

  const wireCopyHandlers = () => {
    results.querySelectorAll('.copy[data-url]').forEach(el => {
      el.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(el.getAttribute('data-url'));
          toast('Link copied', 'ok');
        } catch {
          toast('Copy failed', 'err');
        }
      });
    });
  };

  const doSearch = async (term) => {
    const query = (term ?? q.value ?? '').trim();
    if (!query) { results.innerHTML = ''; return; }
    try {
      let items = [];
      if (apigClient) {
        const res = await apigClient.searchGet({ q: query }, undefined, { headers: cfg.API_KEY ? { 'x-api-key': cfg.API_KEY } : {} });
        const data = res && res.data;
        items = (data && (data.results || data)) || [];
      } else {
        const url = `${cfg.API_ROOT}/search?q=${encodeURIComponent(query)}`;
        const res = await fetch(url, { headers: authHeaders() });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        items = data.results || data || [];
      }
      if (!Array.isArray(items) || !items.length) {
        results.innerHTML = `<div class="muted">No results.</div>`;
        return;
      }
      results.innerHTML = items.map(renderCard).join('');
      wireCopyHandlers();
    } catch (e) {
      results.innerHTML = `<div class="status err">Search failed: ${e.message || e}</div>`;
    }
  };

  document.querySelectorAll('#chips .chip').forEach(c =>
    c.addEventListener('click', () => { q.value = c.dataset.q; doSearch(c.dataset.q); })
  );
  searchBtn.addEventListener('click', () => doSearch());
  q.addEventListener('keydown', (e)=>{ if(e.key==='Enter') doSearch(); });
})();