/* Photo search lifecycle, crop geometry, and explicit confirmation. No photo storage. */
(() => {
  const $ = (id) => document.getElementById(id);
  const workspace = window.ArbiWorkspace;
  const dialog = $('lensDialog');
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g,(c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let photoURL = null, identity = null, active = null, upload = null;
  let crop = null, drag = null, mode = 'product', origin = 'search', busy = false;
  let controller = null, revision = 0, closingTimer = null;
  let lastReferenceThumb = null;

  function open(from = 'search') {
    if (workspace.isBusy()) { workspace.showToast('Wait for the current search or message to finish.'); return; }
    origin = from;
    if (upload && Date.now() > upload.expiresAt) { upload=null;identity=null;showView('welcome');$('lensIdentify').hidden=!photoURL;error('The temporary reference expired. Identify the photo again to continue.'); }
    clearTimeout(closingTimer); dialog.classList.remove('is-closing');
    if (!dialog.open) dialog.showModal();
    $('closeLens').focus();
  }
  function close() {
    if (!dialog.open) return;
    // Closing stops client work; an already-sent provider call can still finish.
    controller?.abort(); controller = null; revision++;
    if (busy) { busy = false; showView('welcome'); $('lensIdentify').hidden = !photoURL; setBusy(false); }
    dialog.classList.add('is-closing');
    closingTimer = setTimeout(() => { dialog.close(); dialog.classList.remove('is-closing'); }, matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 200);
  }
  function error(message) { $('lensError').textContent = message; $('lensError').hidden = !message; }
  function showView(view) {
    ['welcome','scanning','review'].forEach((name) => { $(`lens${name[0].toUpperCase()+name.slice(1)}`).hidden = name !== view; });
    dialog.classList.toggle('is-scanning',view === 'scanning');
    document.querySelectorAll('[data-lens-step]').forEach((item) => item.classList.toggle('active',Number(item.dataset.lensStep) <= ({welcome:0,scanning:1,review:2})[view]));
  }
  function setBusy(value) {
    busy = value;
    ['lensIdentify','lensSearch','lensReplace','lensResetCrop'].forEach((id) => { $(id).disabled = value; });
    $('lensCropStage').setAttribute('aria-busy',String(value));
  }
  async function loadFile(file) {
    if (!file || busy) return;
    if (!['image/jpeg','image/png','image/webp'].includes(file.type)) { error('Choose a JPG, PNG or WebP. Export an iPhone HEIC photo as JPG first.'); return; }
    if (file.size > 6000000) { error('That photo is too large. Choose an image under 6 MB.'); return; }
    controller?.abort(); revision++;
    if (photoURL) URL.revokeObjectURL(photoURL);
    photoURL = URL.createObjectURL(file); identity = null; upload = null; crop = null;
    $('lensPreview').src = photoURL;
    $('lensPreview').onerror = () => { error('This photo could not be opened. Try another image.'); $('lensIdentify').hidden = true; };
    $('lensDropzone').hidden = true; $('lensPhotoWorkspace').hidden = false;
    $('lensObjectChoices').replaceChildren(); $('lensCropBox').hidden = true;
    $('lensIdentify').hidden = false; $('lensIdentify').innerHTML = 'Identify this photo <span>✦</span>';
    showView('welcome'); error('');
  }
  function paintedBounds() {
    const image = $('lensPreview');
    const rect = image.getBoundingClientRect();
    const scale = Math.min(rect.width / image.naturalWidth, rect.height / image.naturalHeight);
    const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
    return {left:rect.left+(rect.width-width)/2,top:rect.top+(rect.height-height)/2,width,height};
  }
  function point(event) {
    const rect = paintedBounds();
    return {x:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y:Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))};
  }
  function paintCrop() {
    const box = $('lensCropBox'); box.hidden = !crop;
    document.querySelectorAll('[data-crop-side]').forEach((input)=>{input.value=Math.round((crop || [0,0,1,1])[Number(input.dataset.cropSide)]*100);});
    if (!crop) { $('lensCropHint').textContent = 'Drag over the product to focus your search.'; return; }
    const bounds = paintedBounds(), stage = $('lensCropStage').getBoundingClientRect();
    box.style.left = `${bounds.left-stage.left+crop[0]*bounds.width}px`;
    box.style.top = `${bounds.top-stage.top+crop[1]*bounds.height}px`;
    box.style.width = `${(crop[2]-crop[0])*bounds.width}px`; box.style.height = `${(crop[3]-crop[1])*bounds.height}px`;
    $('lensCropHint').textContent = 'Only the selected area will be sent for recognition.';
  }
  function invalidateIdentity() {
    identity = null; upload = null; showView('welcome'); $('lensIdentify').hidden = false;
    $('lensIdentify').innerHTML = crop ? 'Identify selected area <span>✦</span>' : 'Identify this photo <span>✦</span>';
    error('');
  }
  $('lensCropStage').addEventListener('pointerdown',(event) => {
    if (busy || !photoURL || !event.isPrimary || event.button !== 0 || !$('lensPreview').naturalWidth) return;
    drag = point(event); $('lensCropStage').setPointerCapture(event.pointerId);
  });
  $('lensCropStage').addEventListener('pointermove',(event) => {
    if (!drag) return;
    const to = point(event); crop = [Math.min(drag.x,to.x),Math.min(drag.y,to.y),Math.max(drag.x,to.x),Math.max(drag.y,to.y)]; paintCrop();
  });
  function finishCrop() {
    if (!drag) return;
    drag = null;
    if (!crop || crop[2]-crop[0] < .05 || crop[3]-crop[1] < .05) crop = null;
    paintCrop(); invalidateIdentity();
  }
  $('lensCropStage').addEventListener('pointerup',finishCrop);
  $('lensCropStage').addEventListener('pointercancel',finishCrop);
  $('lensResetCrop').addEventListener('click',() => { crop = null; paintCrop(); invalidateIdentity(); });
  document.querySelectorAll('[data-crop-side]').forEach((input)=>input.addEventListener('input',()=>{
    if (busy) return;
    const side=Number(input.dataset.cropSide);crop=crop || [0,0,1,1];
    const value=Number(input.value)/100;
    crop[side]=side<2 ? Math.min(value,crop[side+2]-.05) : Math.max(value,crop[side-2]+.05);
    paintCrop();invalidateIdentity();
  }));
  window.addEventListener('resize',() => { if (dialog.open && crop) paintCrop(); });

  function encodeSelection() {
    const image = $('lensPreview');
    if (!image.naturalWidth) throw new Error('Wait for the photo to load, then try again.');
    if (image.naturalWidth * image.naturalHeight > 24000000) throw new Error('Use a photo below 24 megapixels.');
    const [l,t,r,b] = crop || [0,0,1,1];
    const width = (r-l)*image.naturalWidth, height = (b-t)*image.naturalHeight;
    const scale = Math.min(1,1024/Math.max(width,height));
    const canvas = document.createElement('canvas'); canvas.width = Math.max(1,Math.round(width*scale)); canvas.height = Math.max(1,Math.round(height*scale));
    const context = canvas.getContext('2d'); context.fillStyle = '#fff'; context.fillRect(0,0,canvas.width,canvas.height);
    context.drawImage(image,l*image.naturalWidth,t*image.naturalHeight,width,height,0,0,canvas.width,canvas.height);
    const encoded = canvas.toDataURL('image/jpeg',.85);
    const thumb = document.createElement('canvas'); thumb.width=160; thumb.height=160;
    const ctx = thumb.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,160,160);
    const ratio = Math.min(160/canvas.width,160/canvas.height); ctx.drawImage(canvas,(160-canvas.width*ratio)/2,(160-canvas.height*ratio)/2,canvas.width*ratio,canvas.height*ratio);
    return {base64:encoded.split(',')[1],thumb:thumb.toDataURL('image/jpeg',.8)};
  }
  async function identify() {
    if (busy) return;
    let selected;
    try { selected = encodeSelection(); } catch (err) { error(err.message); return; }
    const myRevision = ++revision;
    controller = new AbortController(); setBusy(true); error(''); showView('scanning'); $('lensIdentify').hidden = true;
    try {
      const response = await fetch('/api/lens/identify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64:selected.base64}),signal:controller.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail?.message || 'Photo recognition is unavailable. Try again shortly.');
      if (myRevision !== revision) { forget(data.reference_id); return; }
      if (upload && upload.reference_id !== active?.reference_id) forget(upload.reference_id);
      upload = {...data,thumb:selected.thumb,expiresAt:Date.now()+data.expires_in_seconds*1000}; identity = data.identity; mode='product';
      $('lensIdentityName').textContent = identity.name;
      $('lensConfidence').textContent = `${identity.confidence} confidence`;
      $('lensObservations').replaceChildren(...identity.observations.map((text) => { const item = document.createElement('span'); item.textContent=text;return item; }));
      $('lensUncertainty').textContent = [...identity.uncertainties,identity.clarification].filter(Boolean).join(' ');
      $('lensQuery').value = identity.query;
      $('lensObjectChoices').replaceChildren();
      // Object boxes are relative to the scanned crop, map them back to the photo.
      const scannedCrop = crop || [0,0,1,1];
      identity.objects.forEach((object) => {
        const button=document.createElement('button');button.type='button';button.textContent=`Focus: ${object.label}`;
        button.addEventListener('click',() => {
          const [l,t,r,b]=object.box, [sl,st,sr,sb]=scannedCrop;
          crop=[sl+l*(sr-sl),st+t*(sb-st),sl+r*(sr-sl),st+b*(sb-st)];paintCrop();invalidateIdentity();
        }); $('lensObjectChoices').append(button);
      });
      const tokens = data.usage?.total_token_count;
      $('lensUsage').textContent = data.cached ? 'Recognition reused · no new Gemini call. Up to 6 listing photos checked next.' : `${Number.isFinite(tokens) ? `${tokens.toLocaleString()} recognition tokens · ` : ''}Up to 6 listing photos checked next. No automatic full-board scan.`;
      setMode('product');showView('review');
    } catch (err) {
      if (myRevision === revision) { showView('welcome'); $('lensIdentify').hidden = false; error(err.name === 'AbortError' ? 'Recognition cancelled.' : err.message); }
    } finally { if (myRevision === revision) { setBusy(false); controller=null; } }
  }
  function setMode(next) {
    mode=next;
    document.querySelectorAll('[data-lens-mode]').forEach((button)=>button.setAttribute('aria-pressed',String(button.dataset.lensMode===mode)));
    if (identity) $('lensQuery').value = mode==='similar' ? identity.similar_query : identity.query;
    $('lensModeHint').textContent = mode==='similar' ? 'Broader category search. Similar-looking products remain distinct, not interchangeable.' : 'Prefer the identified product. Exact model and variant still need evidence.';
  }
  async function confirmSearch() {
    if (!upload || !identity || busy || workspace.isBusy()) return;
    if (Date.now()>upload.expiresAt) {open(origin);return;}
    const query = $('lensQuery').value.trim();
    if (query.length<2) { $('lensQuery').focus();error('Give your search a name of at least two characters.');return; }
    const request=workspace.buildRequest();
    if (!request.marketplaces.length) { error('Select at least one marketplace on the search panel first.');return; }
    if (active && active.reference_id !== upload.reference_id) forget(active.reference_id);
    active={...upload,query,mode}; lastReferenceThumb={id:active.reference_id,thumb:active.thumb};
    Object.assign(request,{query,source_mode:'live',pricing_mode:'auto',resale_estimate:null,lens_reference_id:active.reference_id,lens_mode:mode,match_mode:mode==='similar' ? 'related' : 'exact'});
    workspace.restoreForm(request,{}); renderActive();close();
    let bubble;
    if (origin==='chat') {
      const message=workspace.message(`Find ${query} using this photo.`,'user');
      const image=document.createElement('img');image.src=active.thumb;image.alt='Your reference photo';image.className='lens-chat-image';message.prepend(image);
      bubble=workspace.message('Photo identified. Searching your selected markets and checking a six-photo shortlist.','assistant');
    }
    const data=await workspace.executeSearch(request,{save:true});
    if (bubble) { bubble.textContent=data ? `${data.decisions.length} offers found. ${data.lens_context?.checked || 0} visually compared; the rest are explicitly unverified. Your reference stays attached to this board.` : 'The search did not complete. Your photo reference is still selected; check the error on the board.';bubble.arbiSnapshot=data; }
    workspace.updateChatContext();
  }
  function forget(id) { if (id) fetch(`/api/lens/references/${encodeURIComponent(id)}`,{method:'DELETE'}).catch(()=>{}); }
  function removeActive() {
    if (workspace.isBusy()) {workspace.showToast('Wait for the current operation to finish.');return;}
    if (active) {
      forget(active.reference_id);
      if (upload?.reference_id===active.reference_id) {upload=null;invalidateIdentity();}
    }
    active=null;renderActive();workspace.updateChatContext();
    workspace.showToast('Reference removed for the next search. Current results remain unchanged.');
  }
  function renderActive() {
    const box=$('lensSearchReference');box.hidden=!active;
    if (active) {
      box.innerHTML=`<img src="${active.thumb}" alt="Your reference"><div><small>ARBI LENS · ${active.mode==='similar'?'SIMILAR PRODUCTS':'PRODUCT SEARCH'}</small><strong>${escape(active.query)}</strong></div><button type="button">Remove photo ×</button>`;
      box.querySelector('button').addEventListener('click',removeActive);
    } else box.replaceChildren();
  }
  function renderBoard(data) {
    const context=data?.lens_context, board=$('lensBoardReference'),chat=$('lensChatReference');
    board.hidden=!context;chat.hidden=!context;
    if (!context) {board.replaceChildren();chat.replaceChildren();return;}
    const thumb=lastReferenceThumb?.id===context.reference_id ? lastReferenceThumb.thumb : null;
    const identity=context.identity;
    const tokens=context.usage?.total_token_count;
    const photo=thumb ? `<img class="lens-reference-thumb" src="${thumb}" alt="Your photo reference">` : '<span class="lens-reference-thumb lens-reference-placeholder" aria-hidden="true">⌖</span>';
    board.innerHTML=`<section class="lens-reference-card">${photo}<div class="lens-reference-copy"><small>ARBI LENS · ${context.mode==='similar'?'EXPLORING SIMILAR':'REFERENCE PRODUCT'}</small><h3>${escape(identity.name)}</h3><p>${context.checked} photos visually compared · ${context.cached?'cached comparisons':tokens ? `${tokens.toLocaleString()} comparison tokens`:'bounded shortlist'} · ${thumb?'photo expires after 30 minutes':'photo not retained in this snapshot'}. Appearance does not establish authenticity.</p></div><div class="lens-reference-actions"><button type="button" data-lens-board-action="chat">Ask about matches ✦</button><button type="button" data-lens-board-action="photo">${thumb?'Change reference':'Upload reference'} ↗</button></div></section>`;
    board.querySelector('[data-lens-board-action=chat]').addEventListener('click',()=>{workspace.openCopilot();$('copilotInput').value='Which results match my reference, and what differences should I check?';$('copilotInput').dispatchEvent(new Event('input'));});
    board.querySelector('[data-lens-board-action=photo]').addEventListener('click',()=>open('search'));
    chat.innerHTML=`${thumb ? `<img src="${thumb}" alt="Current reference photo">` : '<span aria-hidden="true">⌖</span>'}<div><small>PHOTO REFERENCE · ${context.checked} VISUAL CHECKS</small><b>${escape(identity.name)}</b></div><button type="button">Change ↗</button>`;
    chat.querySelector('button').addEventListener('click',()=>open('chat'));
  }
  window.ArbiLens={
    searchFields:()=>active ? {lens_reference_id:active.reference_id,lens_mode:active.mode} : {},
    syncRequest:(request)=>{ if (active && request.lens_reference_id!==active.reference_id) {active=null;renderActive();} },
    renderBoard,
    chatContext:(data)=>({lens_summary:data?.lens_context ? JSON.stringify({identity:data.lens_context.identity,mode:data.lens_context.mode,note:data.lens_context.note}).slice(0,1800) : '',lens_reference_available:!!active && Date.now()<active.expiresAt && active.reference_id===data?.lens_context?.reference_id}),
  };
  ['openLens','lensInvite'].forEach((id)=>$(id).addEventListener('click',()=>open('search')));
  $('chatOpenLens').addEventListener('click',()=>open('chat'));
  $('closeLens').addEventListener('click',close);
  dialog.addEventListener('cancel',(event)=>{event.preventDefault();close();});
  dialog.addEventListener('click',(event)=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)close();}});
  $('lensDropzone').addEventListener('click',()=>$('lensFile').click());
  $('lensDropzone').addEventListener('keydown',(event)=>{if(['Enter',' '].includes(event.key)){event.preventDefault();$('lensFile').click();}});
  $('lensReplace').addEventListener('click',()=>$('lensFile').click());
  $('lensFile').addEventListener('change',(event)=>{loadFile(event.target.files[0]);event.target.value='';});
  const dropzone=$('lensVisual') || dialog.querySelector('.lens-visual');
  dropzone.addEventListener('dragover',(event)=>{event.preventDefault();$('lensDropzone').classList.add('is-dragging');});
  dropzone.addEventListener('dragleave',()=>$('lensDropzone').classList.remove('is-dragging'));
  dropzone.addEventListener('drop',(event)=>{event.preventDefault();$('lensDropzone').classList.remove('is-dragging');loadFile(event.dataTransfer.files[0]);});
  $('lensIdentify').addEventListener('click',identify);
  $('lensSearch').addEventListener('click',confirmSearch);
  document.querySelectorAll('[data-lens-mode]').forEach((button)=>button.addEventListener('click',()=>setMode(button.dataset.lensMode)));
})();
