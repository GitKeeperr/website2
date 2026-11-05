/* Konzei Clips — private accounts with official Google Identity Services. */
const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
const main = $('#main');
const state = {
  view: 'home', tab: 'discover', projectId: null, project: null,
  projects: [], presets: [], system: {}, auth: null, csrf: '', authConfig: null, siteNotice: '',
  analysis: { count: 6, length: 45, prompt: '', transcribe: true },
  editor: {}, selectedHighlight: -1
};
const defaultEditor = (duration = 45) => ({
  start: 0, end: Math.min(duration, 45), ratio: '9:16', crop_mode: 'crop', focus_x: .5, focus_y: .5,
  smart_crop: true, captions: true, manual_captions: '', caption_style: 'bold', overlay_title: '',
  censor_captions: false, enhance_audio: false, remove_silence: false, fade: false, crf: 23, label: ''
});

function esc(text) { return String(text == null ? '' : text).replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x])); }
function fmt(s) { s = Number(s)||0; return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(Math.floor(s%60)).padStart(2,'0')}`; }
function bytes(n) { return n>1e9 ? (n/1e9).toFixed(2)+' GB' : (n/1e6).toFixed(1)+' MB'; }
function dateLabel(value) { try { return new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}); } catch { return ''; } }
function toast(message, kind='') {
  const node = document.createElement('div'); node.className = `toast ${kind}`; node.textContent = message;
  $('#toast-area').append(node); setTimeout(()=>node.remove(), 5500);
}
async function api(path, options={}) {
  let response;
  try {
    const method = (options.method || 'GET').toUpperCase();
    if (!['GET','HEAD','OPTIONS'].includes(method)) { options.headers = {...(options.headers || {}), 'X-Konzei-CSRF': state.csrf}; }
    response = await fetch(path, {...options, credentials: 'same-origin'});
  } catch { throw new Error('Cannot connect to the local studio. Is the Konzei server running?'); }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { const err = await response.json(); message = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail); } catch {}
    if (response.status === 401 && !path.startsWith('/api/auth/')) { lockStudio(); }
    throw new Error(message);
  }
  return response.json();
}
const post = (path, data) => api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
async function refresh() {
  const [projects, presets, system, account] = await Promise.all([api('/api/projects'), api('/api/presets'), api('/api/system'), api('/api/auth/me')]);
  state.projects = projects; state.presets = presets; state.system = system; state.siteNotice = account.site_notice || ''; 
  $('#project-count').textContent = projects.length;
  const badge = $('#engine-status'); badge.classList.toggle('unavailable', !system.ffmpeg);
  badge.innerHTML = `<i></i>${system.ffmpeg ? ' Local engine ready' : ' FFmpeg missing'}`;
}
function setView(view) {
  state.view = view;
  $$('.nav-link').forEach(btn => btn.classList.toggle('active', btn.dataset.view === (view==='studio'?'projects':view)));
  $('#breadcrumb').textContent = ({home:'Overview',projects:'My projects',recipes:'My recipes',settings:'Preferences',studio:'Clip editor',owner:'Owner dashboard'})[view] || view;
  if (view === 'home' || view === 'projects') renderHome(view==='projects');
  if (view === 'studio') renderStudio();
  if (view === 'recipes') renderRecipes();
  if (view === 'settings') renderSettings();
  if (view === 'owner' && state.auth?.role === 'owner') renderOwner();
  window.scrollTo({top:0,behavior:'instant'});
}
function projectCard(p) {
  return `<article class="project-card">
    <div class="project-thumb" data-action="open-project" data-id="${p.id}">
      <img src="/media/${p.id}/thumbnail" alt="" loading="lazy" onerror="this.style.display='none'" />
      <span class="play-round">▶</span><span class="thumb-duration">${fmt(p.info.duration)}</span>
    </div>
    <div class="project-details"><strong title="${esc(p.title)}">${esc(p.title)}</strong>
      <small>${dateLabel(p.created)} · ${p.info.width}×${p.info.height}</small>
      <div class="project-meta"><span class="tag">${p.highlights ? p.highlights+' moments' : 'Ready to edit'}</span><small>${bytes(p.info.size)}</small></div>
      <div class="project-actions"><button class="btn btn-sm" data-action="open-project" data-id="${p.id}">Open studio →</button><button class="btn btn-quiet" data-action="delete-project" data-id="${p.id}" title="Delete project">✕</button></div>
    </div>
  </article>`;
}
function renderHome(projectsOnly=false) {
  const projects = state.projects;
  const totalExports = projects.reduce((n,p)=>n+p.exports,0);
  main.innerHTML = `${state.siteNotice ? `<div class="member-notice"><strong>✦ KONZEI UPDATE</strong><span>${esc(state.siteNotice)}</span></div>` : ''}${projectsOnly ? `<div class="page-heading"><div><span class="overline">YOUR LIBRARY</span><h1>My projects</h1><p>Everything you've been creating, all in one place.</p></div><button class="btn btn-primary" data-action="upload">＋ New video</button></div>` : `
    <div class="page-heading"><div><span class="overline">WELCOME BACK TO YOUR STUDIO</span><h1>Good things start with a great clip ✦</h1><p>Your personal creative workspace. Your projects stay private to your account.</p></div><span class="eyebrow-pill"><i></i> PRIVATE CREATOR MODE</span></div>
    <section class="hero">
      <div class="hero-intro"><span class="eyebrow-pill"><i></i> THE VIDEO STUDIO BUILT BY KONZEI</span><h2>One long video.<br/><span class="gradient-ink">Endless great moments.</span></h2><p>Find your highlights, reframe for every platform, add captions, and create scroll-stopping shorts — in your own workspace.</p><div class="feature-badges"><span>✦ Smart highlights</span><span>◎ Animated captions</span><span>◫ Every aspect ratio</span><span>↧ Direct MP4 export</span></div></div>
      <div class="hero-upload"><div class="drop-zone" id="drop-zone" data-action="upload"><span class="upload-glyph">⇧</span><strong>Drop your video here, or click to browse</strong><small>MP4, MOV, MKV, WebM · Processed by your Konzei server</small></div><div class="tiny-divider">or paste a video link</div><div class="url-import"><input class="input" id="url-input" type="url" placeholder="https://youtube.com/watch?v=…" aria-label="Video URL"/><button class="btn btn-primary" data-action="import-url">Import →</button></div><div class="browser-auth" ${state.system.browser_cookie_import?'':'hidden'}><label for="cookie-browser">YouTube login (optional)</label><select class="select" id="cookie-browser" aria-label="Use YouTube login from browser"><option value="none">No browser login</option><option value="chrome">Chrome</option><option value="edge">Edge</option><option value="firefox">Firefox</option><option value="brave">Brave</option><option value="vivaldi">Vivaldi</option></select></div><input class="input cookie-profile" ${state.system.browser_cookie_import?'':'hidden'} id="cookie-profile" placeholder="Browser profile folder (optional, e.g. Profile 1)" aria-label="Optional browser profile folder"/><small class="auth-note" ${state.system.browser_cookie_import?'':'hidden'}>If YouTube asks to confirm you’re not a bot, choose the browser you use for YouTube. Available only when Konzei is installed locally; never share browser cookies.</small></div>
    </section>
    <div class="metric-row"><div class="metric"><span class="metric-icon">◫</span><div><strong>${projects.length}</strong><small>Projects created</small></div></div><div class="metric"><span class="metric-icon">✂</span><div><strong>${totalExports}</strong><small>Videos exported</small></div></div><div class="metric"><span class="metric-icon">∞</span><div><strong>Unlimited</strong><small>Clips, always</small></div></div></div>`}
    <section><div class="section-header"><div><h3>${projectsOnly?'All projects':'Recent projects'}</h3><p>${projects.length ? 'Pick up right where you left off.' : 'Your video library is ready for its first project.'}</p></div>${!projectsOnly?'<button class="link-btn" data-view="projects">View all →</button>':''}</div>
      ${projects.length ? `<div class="project-grid">${(projectsOnly?projects:projects.slice(0,8)).map(projectCard).join('')}</div>` : `<div class="empty-state"><div class="empty-icon">✧</div><h3>Your next great clip starts here</h3><p>Upload a video to find and export your first highlight.</p><button class="btn btn-primary" data-action="upload">＋ Import a video</button></div>`}
    </section>`;
  const drop = $('#drop-zone');
  if (drop) {
    drop.addEventListener('dragover', e => {e.preventDefault();drop.classList.add('dragging');});
    drop.addEventListener('dragleave', () => drop.classList.remove('dragging'));
    drop.addEventListener('drop', e => { e.preventDefault();drop.classList.remove('dragging');if(e.dataTransfer.files.length) uploadVideo(e.dataTransfer.files[0]); });
  }
}
async function uploadVideo(file) {
  if (!file) return;
  const form = new FormData(); form.append('file',file);
  showJob('IMPORTING VIDEO','Adding your video to Konzei','Copying video to your local workspace…',.1);
  try {
    const project = await api('/api/projects/upload',{method:'POST',body:form});
    hideJob(); await refresh(); await openProject(project.id); toast('Video imported successfully.','good');
  } catch(err) { hideJob();toast(err.message,'error'); }
  $('#file-picker').value='';
}
async function importUrl() {
  const url = $('#url-input')?.value.trim(); if (!url) return toast('Paste a supported HTTPS video URL.','error');
  const cookie_browser = $('#cookie-browser')?.value || 'none';
  const cookie_profile = $('#cookie-profile')?.value.trim() || '';
  try { const job = await post('/api/projects/import-url',{url, cookie_browser, cookie_profile}); await watchJob(job,'IMPORTING VIDEO','Downloading your video', async result => { await refresh(); await openProject(result.project_id);toast('Video downloaded and imported.','good'); }); }
  catch(err){toast(err.message,'error');}
}
async function openProject(id) {
  try {
    const project = await api(`/api/projects/${id}`);
    state.project=project;state.projectId=id;state.editor=defaultEditor(project.info.duration);
    if (project.transcript?.length) state.editor.captions=true;
    else state.editor.captions=false;
    state.selectedHighlight=-1;state.tab='discover';setView('studio');
  } catch(err) {toast(err.message,'error');}
}
function option(name,val) {
  state.editor[name]=val;
  if (name==='start'||name==='end') {
    state.selectedHighlight=-1;
    const video=$('#source-video');if(video && name==='start') video.currentTime=Number(val);
    const trim=$('#trim-display');if(trim)trim.textContent=`${fmt(state.editor.start)} – ${fmt(state.editor.end)}`;
  }
}
function editorOptions() {return {...state.editor,start:Number(state.editor.start),end:Number(state.editor.end),focus_x:Number(state.editor.focus_x),focus_y:Number(state.editor.focus_y),crf:Number(state.editor.crf)};}
function numberInput(key, label, step=1) {
  return `<div class="control-group"><label for="opt-${key}">${label}</label><input class="input" id="opt-${key}" type="number" data-opt="${key}" step="${step}" min="0" max="${state.project?.info.duration}" value="${esc(state.editor[key])}" /></div>`;
}
function switchRow(key,label,helper=''){
  return `<label class="toggle-row"><span class="toggle-copy"><strong>${label}</strong>${helper?`<small>${helper}</small>`:''}</span><input class="toggle" type="checkbox" data-opt="${key}" ${state.editor[key]?'checked':''}></label>`;
}
function renderStudio() {
  const p=state.project; if(!p){setView('projects');return;}
  const e=state.editor;
  const segmentList=(p.highlights||[]).length ? p.highlights.map((c,i)=>`<button class="segment-card ${state.selectedHighlight===i?'selected':''}" data-action="pick-highlight" data-index="${i}"><span class="segment-num">${String(i+1).padStart(2,'0')}</span><span class="segment-copy"><strong>${esc(c.title)}</strong><small>${fmt(c.start)} – ${fmt(c.end)} · ${esc(c.reason)}</small></span><span class="score-pill" title="Heuristic score, not a predicted view count">${c.score}</span></button>`).join('') : `<div class="segment-hint">No highlights selected yet. Use <b>Find highlights</b> to analyze the video, or edit your own time range.</div>`;
  main.innerHTML = `<div class="studio-top"><div class="studio-heading"><span class="overline">PROJECT / EDITOR</span><h1>${esc(p.title)}</h1><p>${fmt(p.info.duration)} runtime &nbsp;·&nbsp; ${p.info.width} × ${p.info.height} &nbsp;·&nbsp; ${bytes(p.info.size)} &nbsp;·&nbsp; ${dateLabel(p.created)}</p></div><button class="btn btn-subtle" data-action="back-projects">← Projects</button></div>
    <div class="studio-layout"><div class="studio-left">
      <section class="panel"><div class="panel-head"><h3>Source preview</h3><span class="sub">ORIGINAL VIDEO · ${p.info.has_audio?'WITH AUDIO':'NO AUDIO'}</span></div>
        <div class="video-shell"><video controls playsinline id="source-video" preload="metadata" src="/media/${p.id}/original"></video></div>
        <div class="video-footer"><div class="time-stats"><span>Source timeline</span><span id="playback-time">00:00 / ${fmt(p.info.duration)}</span></div><input type="range" class="seek-track" id="source-seek" min="0" max="${p.info.duration}" step="0.1" value="0" aria-label="Seek video"/><div class="trim-labels"><span>Selected clip: <b id="trim-display">${fmt(e.start)} – ${fmt(e.end)}</b></span><span>${fmt(p.info.duration)} total</span></div></div>
      </section>
      <section class="panel" style="margin-top:19px"><div class="panel-head"><h3>✦ Suggested highlights</h3><span class="sub">${(p.highlights||[]).length} MOMENTS FOUND</span></div><div class="segment-list">${segmentList}</div></section>
      <section class="panel" style="margin-top:19px"><div class="panel-head"><h3>Exported clips</h3><span class="sub">${(p.exports||[]).length} READY TO SHARE</span></div><div class="segment-list">${(p.exports||[]).length ? p.exports.slice(0,12).map(exportCard).join(''):'<div class="segment-hint">Your completed MP4 exports will appear here.</div>'}</div></section>
    </div><div class="studio-right"><section class="panel"><div class="editor-tabs"><button class="editor-tab ${state.tab==='discover'?'active':''}" data-tab="discover">✦ Discover</button><button class="editor-tab ${state.tab==='edit'?'active':''}" data-tab="edit">☷ Editor</button><button class="editor-tab ${state.tab==='exports'?'active':''}" data-tab="exports">⇩ Exports</button></div>
       <div class="editor-content" id="editor-content">${studioTabHTML()}</div><div class="editor-bottom" id="studio-footer">${studioFootHTML()}</div>
    </section></div></div>`;
  const video=$('#source-video'); const seek=$('#source-seek');
  if(video) { video.addEventListener('timeupdate',()=>{ if(seek && !seek.matches(':active')) seek.value=video.currentTime; const label=$('#playback-time');if(label) label.textContent=`${fmt(video.currentTime)} / ${fmt(p.info.duration)}`;}); }
  if(seek)seek.addEventListener('input',()=>{if(video)video.currentTime=Number(seek.value);});
}
function exportCard(x){return `<div class="export-card"><div class="export-icon">▶</div><div class="export-copy"><strong>${esc(x.label)}</strong><small>${esc(x.ratio)} · ${fmt(x.info.duration)} · ${bytes(x.info.size)} · ${dateLabel(x.created)}</small><div class="export-actions"><a class="btn btn-sm" target="_blank" rel="noopener" href="/media/${state.projectId}/exports/${x.id}">▶ Watch</a><a class="btn btn-sm btn-primary" href="/media/${state.projectId}/exports/${x.id}?download=true">⇩ Download</a></div></div></div>`;}
function studioTabHTML(){
 const e=state.editor,p=state.project;
 if(state.tab==='discover')return `<span class="overline">MOMENT FINDER</span><h3 style="font-size:20px;margin:7px 0 9px;letter-spacing:-.6px">Find the good stuff.</h3><p class="helper" style="font-size:11px;margin-bottom:23px">Analyze scenes and audio to identify candidate moments. Local Whisper adds speech transcription when installed.</p>
  <div class="control-group"><label>What are you looking for? <span class="label-tip">optional</span></label><textarea class="textarea" data-analysis="prompt" placeholder="e.g. best advice about content creation, funny moments…">${esc(state.analysis.prompt)}</textarea><p class="helper">Text prompts match spoken words when transcription is available.</p></div>
  <div class="control-row"><div class="control-group"><label>Number of clips</label><select class="select" data-analysis="count">${[3,4,6,8,10,12,16,20].map(v=>`<option ${Number(state.analysis.count)===v?'selected':''}>${v}</option>`).join('')}</select></div><div class="control-group"><label>Clip length</label><select class="select" data-analysis="length">${[15,30,45,60,90,120,180,300,600,900].map(v=>`<option value="${v}" ${Number(state.analysis.length)===v?'selected':''}>${v<60?v+' sec':v%60===0?v/60+' min':v+' sec'}</option>`).join('')}</select></div></div>
  <label class="toggle-row" style="margin:9px 0 18px"><span class="toggle-copy"><strong>Transcribe spoken audio</strong><small>${state.system.whisper?'Local Whisper engine detected':'Optional: install faster-whisper to enable'}</small></span><input class="toggle" type="checkbox" data-analysis="transcribe" ${state.analysis.transcribe?'checked':''}></label>
  <div class="hint-box">✦ <b>About scores:</b> Suggestions use local speech, visual-cut, and sound activity signals. Scores are ranking estimates, not OpusClip's proprietary virality predictions.</div>
  <button class="btn btn-primary btn-large btn-full" data-action="analyze">✦ Find highlights</button>
  ${(p.highlights||[]).length?`<button class="btn btn-subtle btn-full" style="margin-top:10px" data-action="export-all">⇩ Export all ${p.highlights.length} highlights</button><p class="helper">Bulk export uses your current Editor settings for every suggested clip.</p>`:''}
  ${(p.transcript||[]).length?`<p class="helper good">✓ ${p.transcript.length} speech tokens transcribed and available for captions. <a href="/api/projects/${p.id}/subtitles.srt" style="color:#c1a2ff;text-decoration:underline">Download SRT</a></p>`:''}
  ${p.analysis_note?`<p class="helper">${esc(p.analysis_note)}</p>`:''}`;
 if(state.tab==='exports') return `<span class="overline">YOUR CREATIONS</span><h3 style="font-size:20px;margin:8px 0 17px">Ready to share.</h3>${(p.exports||[]).length?p.exports.map(exportCard).join(''):'<div class="segment-hint">You haven’t exported any clips yet.<p>Choose a highlight, open the Editor tab, and export an MP4.</p></div>'}`;
 return `<span class="overline">CLIP EDITOR</span><h3 style="font-size:20px;margin:8px 0 20px;letter-spacing:-.6px">Make it yours.</h3>
  <div class="control-row">${numberInput('start','Start (seconds)',.1)}${numberInput('end','End (seconds)',.1)}</div><p class="helper" style="margin:6px 0 19px">Set exact start/end times or select a suggested highlight.</p>
  <div class="control-group"><label>Video format <span class="label-tip">platform ready</span></label><div class="format-picker">${['9:16','1:1','4:5','16:9'].map(r=>`<button class="format-button ${e.ratio===r?'active':''}" data-action="ratio" data-ratio="${r}"><span class="format-pict"></span>${r}</button>`).join('')}</div></div>
  <div class="control-group"><label>Reframe mode</label><select class="select" data-opt="crop_mode"><option value="crop" ${e.crop_mode==='crop'?'selected':''}>Fill frame / crop edges</option><option value="blur" ${e.crop_mode==='blur'?'selected':''}>Blurred background</option><option value="fit" ${e.crop_mode==='fit'?'selected':''}>Fit inside / black bars</option></select></div>
  <div class="control-group"><label>Horizontal focus <span class="label-tip">${Math.round(e.focus_x*100)}%</span></label><input class="seek-track" type="range" min="0" max="1" step="0.05" value="${e.focus_x}" data-opt="focus_x"/></div>
  ${switchRow('smart_crop','Smart face focus','Keeps a detected speaker closer to center')}
  <div class="divider"></div>
  <div class="control-group"><label>Caption style</label><select class="select" data-opt="caption_style">${['bold','classic','karaoke','neon','minimal'].map(x=>`<option ${e.caption_style===x?'selected':''} value="${x}">${({bold:'Big bold',classic:'Classic white',karaoke:'Karaoke highlight',neon:'Neon glow',minimal:'Clean minimal'})[x]}</option>`).join('')}</select></div>
  ${switchRow('captions','Burn captions into video','Rendered permanently in the output MP4')}
  <div class="control-group"><label>Manual captions <span class="label-tip">if no transcript</span></label><textarea class="textarea" data-opt="manual_captions" placeholder="Type spoken words here if Whisper is not installed…">${esc(e.manual_captions)}</textarea><p class="helper">${(p.transcript||[]).length?`${p.transcript.length} transcribed words are available. Manual text is used only when no transcript exists.`:'Optional manual text. Words are timed evenly unless Whisper provides timestamps.'}</p></div>
  <div class="control-group"><label>Intro title <span class="label-tip">optional · first 3.5 seconds</span></label><input class="input" type="text" maxlength="110" data-opt="overlay_title" placeholder="An intro viewers can't skip…" value="${esc(e.overlay_title)}"></div>
  ${switchRow('censor_captions','Censor caption profanity','Replaces selected words with asterisks')}
  <div class="divider"></div>
  ${switchRow('enhance_audio','Enhance audio','Local denoise, compression and loudness match')}
  ${switchRow('remove_silence','Cut long silences','Removes detected quiet gaps from audio and video')}
  ${switchRow('fade','Soft fade in and out','Adds a short video and audio fade')}
  <div class="divider"></div>
  <div class="control-group"><label>Export quality</label><select class="select" data-opt="crf"><option value="18" ${e.crf===18?'selected':''}>Best quality · larger files</option><option value="23" ${e.crf===23?'selected':''}>Balanced · recommended</option><option value="28" ${e.crf===28?'selected':''}>Smaller file</option><option value="32" ${e.crf===32?'selected':''}>Smallest file</option></select></div>
  <div class="control-group"><label>Export name</label><input class="input" type="text" maxlength="90" placeholder="e.g. My best highlight" data-opt="label" value="${esc(e.label)}"></div>
  <div class="hint-box green">✓ No watermark or credits. Every export is processed locally and saved as an MP4.</div>`;
}
function studioFootHTML(){
 if(state.tab==='edit')return `<button class="btn btn-subtle" data-action="save-recipe" title="Save these edit settings">◇ Save recipe</button><button class="btn btn-primary" data-action="export">⇩ Export clip</button>`;
 if(state.tab==='exports')return `<button class="btn btn-primary btn-full" data-action="show-edit">✎ Create another clip</button>`;
 return `<button class="btn btn-primary btn-full" data-action="show-edit">☷ Go to clip editor →</button>`;
}
function changeStudioTab(tab){state.tab=tab;renderStudio();}
async function analyzeVideo(){
  if(!state.project) return;
  try {
    const job=await post(`/api/projects/${state.projectId}/analyze`,state.analysis);
    await watchJob(job,'ANALYZING VIDEO','Finding the best moments',async()=>{
      state.project=await api(`/api/projects/${state.projectId}`);renderStudio();toast(`${state.project.highlights.length} candidate highlights found.`, 'good');
    });
  } catch(err){toast(err.message,'error');}
}
function selectHighlight(index){
  const item=state.project.highlights[index]; if(!item)return;
  state.selectedHighlight=index;
  state.editor.start=item.start;state.editor.end=item.end;state.editor.label=item.title.slice(0,80);
  state.tab='edit';renderStudio();
  const video=$('#source-video'); if(video)video.currentTime=item.start;
  toast(`Selected highlight ${index+1}. Adjust settings and export.`,'good');
}
async function exportAll(){
 if(!state.project?.highlights?.length)return toast('Analyze the video to find highlights first.','error');
 const options=editorOptions();
 if(options.captions && !state.project.transcript?.length && !options.manual_captions.trim())return toast('Turn off captions in the Editor, enter manual captions, or run Whisper transcription first.','error');
 if(!confirm(`Render ${state.project.highlights.length} MP4 clips using your current Editor settings?`))return;
 try{
  const job=await post(`/api/projects/${state.projectId}/export-all`,options);
  await watchJob(job,'BATCH EXPORT','Rendering your highlight collection',async(result)=>{
   state.project=await api(`/api/projects/${state.projectId}`);await refresh();state.tab='exports';renderStudio();toast(`${result.clips.length} clips exported successfully!`,'good');
  });
 }catch(err){toast(err.message,'error');}
}
async function exportClip(){
 const e=editorOptions();
 if(e.start<0||e.end<=e.start+.49||e.end>state.project.info.duration+.15) return toast('Choose a valid start and end time.','error');
 if(e.end-e.start>900) return toast('Maximum clip length is 15 minutes.','error');
 if(e.captions && !state.project.transcript?.length && !e.manual_captions.trim()) return toast('Either add manual captions, run Whisper analysis, or turn captions off.','error');
 try {
   const job=await post(`/api/projects/${state.projectId}/export`,e);
   await watchJob(job,'EXPORTING MP4','Your new clip is rendering',async()=>{
     state.project=await api(`/api/projects/${state.projectId}`);await refresh();state.tab='exports';renderStudio();toast('Your MP4 is ready to download!','good');
   });
 }catch(err){toast(err.message,'error');}
}
function showJob(kind,label,message,progress=0){$('#job-overlay').classList.remove('hidden');$('#job-kind').textContent=kind;$('#job-label').textContent=label;updateJob({message,progress});}
function updateJob(job){$('#job-message').textContent=job.message||'Processing…';$('#job-bar').style.width=`${Math.max(1,Math.min(100,Number(job.progress||0)*100))}%`;$('#job-percent').textContent=Math.round((job.progress||0)*100)+'%';}
function hideJob(){$('#job-overlay').classList.add('hidden');}
async function watchJob(job,kind,label,onDone){
 showJob(kind,label,job.message,job.progress);
 let done=false;
 try {
   while(!done){
     await new Promise(resolve=>setTimeout(resolve,1250));
     const current=await api(`/api/jobs/${job.id}`);updateJob(current);
     if(current.status==='error') throw new Error(current.message || 'Processing failed');
     if(current.status==='done'){done=true;hideJob();await onDone(current.result);}
   }
 } catch(err){hideJob();toast(err.message,'error');}
}
async function saveRecipe(){
 const name=prompt('Name this recipe (reusable export settings):');if(!name||!name.trim())return;
 try {await post('/api/presets',{name:name.trim(),options:editorOptions()});await refresh();toast('Recipe saved. Find it under My recipes.','good');}
 catch(err){toast(err.message,'error');}
}
function renderRecipes(){
 main.innerHTML=`<div class="page-heading"><div><span class="overline">YOUR SAVED WORKFLOWS</span><h1>My recipes</h1><p>Save an edit once, reuse your settings any time.</p></div><button class="btn btn-primary" data-action="upload">＋ New project</button></div>
 ${state.presets.length?`<div class="recipe-grid">${state.presets.map(r=>`<article class="recipe-card"><div class="recipe-card-top"><span class="recipe-icon">◈</span><div><strong>${esc(r.name)}</strong><small>Saved ${dateLabel(r.created)}</small></div></div><div class="recipe-properties">${esc(r.options.ratio)} &nbsp;·&nbsp; ${esc(r.options.caption_style)} captions &nbsp;·&nbsp; ${r.options.enhance_audio?'Audio enhanced':'Original audio'}</div><div class="recipe-buttons"><button class="btn btn-primary btn-sm" data-action="apply-recipe" data-id="${r.id}">Apply recipe</button><button class="btn btn-danger btn-sm" data-action="delete-recipe" data-id="${r.id}">Delete</button></div></article>`).join('')}</div>`:`<div class="empty-state"><div class="empty-icon">◈</div><h3>Every great edit deserves a repeat.</h3><p>Open a project, customize your editor, and click “Save recipe.”</p><button class="btn btn-primary" data-action="upload">Create a project</button></div>`}`;
}
async function applyRecipe(id){const r=state.presets.find(x=>x.id===id);if(!r)return;
 if(!state.project){ if(!state.projects.length)return toast('Import a video before applying a recipe.','error');await openProject(state.projects[0].id); }
 const d=state.project.info.duration;
 state.editor={...defaultEditor(d),...r.options,start:0,end:Math.min(d,Number(r.options.end)||45)};
 state.tab='edit';setView('studio');toast(`Recipe "${r.name}" applied.`, 'good');
}
function renderSettings(){const s=state.system;
 main.innerHTML=`<div class="page-heading"><div><span class="overline">KONZEI / SETTINGS</span><h1>Preferences & tools</h1><p>Everything your video studio runs on.</p></div></div>
 <div class="preference-card"><h3>🔒 Your private account</h3><p>Signed in securely as <strong>${esc(state.auth?.display_name||'Creator')}</strong> (${esc(state.auth?.email||'')}).</p><p>Your access: <strong>${state.auth?.role==='owner'?'Verified site owner':'Creator member'}</strong>. Your email and profile information aren't listed publicly. Only the owner can view a private member directory.</p><button class="btn btn-sm" data-action="signout">Sign out of Konzei</button></div>
 <div class="preference-card"><h3>◈ Processing environment</h3><p>${s.local_only?'This installation runs on your own computer. Uploaded video files stay on this machine.':'This Konzei server processes and stores uploaded videos on its host. Files are private to your account; contact the host administrator about retention and backups.'}</p><div class="sys-grid">
 <div class="sys-item"><strong>FFmpeg video engine</strong><small class="${s.ffmpeg?'ok':'no'}">${s.ffmpeg?'● Ready':'● Missing — install FFmpeg'}</small></div>
 <div class="sys-item"><strong>Whisper auto captions</strong><small class="${s.whisper?'ok':'no'}">${s.whisper?'● Available':'● Optional — install faster-whisper'}</small></div>
 <div class="sys-item"><strong>Link downloading</strong><small class="${s.yt_dlp?'ok':'no'}">${s.yt_dlp?'● Available':'● Optional — install yt-dlp'}</small></div>
 <div class="sys-item"><strong>Processing credits</strong><small class="ok">● Unlimited local processing</small></div></div></div>
 <div class="preference-card"><h3>✦ Add automatic AI transcription</h3><p>Install optional open-source Whisper support in the environment running Konzei, then restart the server. The first transcription downloads a small speech model. This improves clip selection and enables word-synced captions.</p><code style="display:block;overflow:auto;padding:13px;border:1px solid #343648;border-radius:9px;background:#090c15;color:#cbb4ff">pip install faster-whisper</code></div>
 <div class="preference-card"><h3>⇩ Enable link imports</h3><p>To import videos you have permission to use from supported video sites, install yt-dlp. Some sites may block downloading or require credentials.</p><code style="display:block;overflow:auto;padding:13px;border:1px solid #343648;border-radius:9px;background:#090c15;color:#cbb4ff">pip install yt-dlp</code></div>
 <div class="preference-card"><h3>About this project</h3><p><b>Konzei Clips v${esc(s.version||'1.0')}</b> is an independent local video-editing studio. It does not connect to OpusClip, mimic your account, unlock OpusClip paid APIs, or claim to reproduce their proprietary algorithms. Cloud social publishing, advanced multimodal AI, generated B-roll, and proprietary virality scoring are not included.</p></div>`;
}
async function deleteProject(id){if(!confirm('Delete this project, source video and all its exported clips?'))return;
 try {await api(`/api/projects/${id}`,{method:'DELETE'});if(state.projectId===id){state.project=null;state.projectId=null;}await refresh();setView('projects');toast('Project deleted.','good');}catch(err){toast(err.message,'error');}
}
async function deleteRecipe(id){if(!confirm('Delete this saved recipe?'))return;try{await api(`/api/presets/${id}`,{method:'DELETE'});await refresh();renderRecipes();toast('Recipe deleted.');}catch(err){toast(err.message,'error');}}

function setAccount(account) {
  state.auth = account;
  document.querySelector('.app-shell').classList.remove('auth-locked');
  $('#auth-screen').classList.add('hidden');
  $('#owner-nav').hidden = account.role !== 'owner';
  const initial = (account.display_name || 'K').charAt(0).toUpperCase();
  $('#profile-initial').textContent = initial;
  $('#top-avatar').textContent = initial;
  $('#profile-name').textContent = account.display_name || 'Creator';
  $('#profile-role').textContent = account.role === 'owner' ? '✦ Verified Owner' : 'Creator account';
}
function lockStudio() {
  state.auth = null;
  state.project=null;state.projectId=null;state.projects=[];state.presets=[];
  document.querySelector('.app-shell').classList.add('auth-locked');
  $('#auth-screen').classList.remove('hidden');
  $('#owner-nav').hidden=true;
  $('#job-overlay').classList.add('hidden');
}
async function signOut() {
  try { await post('/api/auth/logout', {}); } catch (e) { toast(e.message, 'error'); }
  if (window.google?.accounts?.id) window.google.accounts.id.disableAutoSelect();
  lockStudio();$('#signin-status').textContent='Sign in with your Google account to continue.';
}
async function googleCallback(response) {
  $('#signin-status').textContent='Verifying your Google account…';
  try {
    const result = await post('/api/auth/google', {credential:response.credential});
    setAccount(result.user);
    await refresh();setView('home');
    toast(`Welcome, ${result.user.display_name}!`,'good');
  } catch (error) {
    $('#signin-status').textContent=error.message;
  }
}
async function renderGoogleButton(clientId) {
  const status=$('#signin-status');
  if (!clientId) { status.textContent='Setup required: add KONZEI_GOOGLE_CLIENT_ID to the server .env and restart Konzei.'; return; }
  for (let i=0;i<50&&!window.google?.accounts?.id;i++) await new Promise(resolve=>setTimeout(resolve,120));
  if (!window.google?.accounts?.id) {status.textContent='Google sign-in could not load. Check your internet connection or browser extensions.';return;}
  window.google.accounts.id.initialize({client_id:clientId,callback:googleCallback,ux_mode:'popup',auto_select:false});
  window.google.accounts.id.renderButton($('#google-signin-button'),{type:'standard',theme:'filled_black',size:'large',shape:'pill',text:'continue_with',width:280});
  status.textContent='Use your Google account to continue securely.';
}
async function boot() {
  lockStudio();
  try {
    state.authConfig=await api('/api/auth/config');state.csrf=state.authConfig.csrf_token;
    const account=await api('/api/auth/me');
    if (account.user) {setAccount(account.user);await refresh();setView('home');}
    await renderGoogleButton(state.authConfig.configured ? state.authConfig.google_client_id : '');
  } catch (error) { $('#signin-status').textContent=error.message; }
}
async function renderOwner() {
  if (state.auth?.role !== 'owner') return setView('home');
  main.innerHTML='<div class="loading"><span class="spinner"></span> Loading private owner dashboard…</div>';
  try {
    const [overview,users]=await Promise.all([api('/api/owner/overview'),api('/api/owner/users')]);
    if (state.view!=='owner') return;
    main.innerHTML=`<div class="page-heading"><div><span class="overline">✦ PRIVATE / OWNER ONLY</span><h1>Konzei command center</h1><p>These controls and account records are not available to standard members.</p></div><span class="eyebrow-pill">♛ VERIFIED OWNER</span></div>
      <div class="metric-row"><div class="metric"><span class="metric-icon">♙</span><div><strong>${overview.users}</strong><small>Registered accounts</small></div></div><div class="metric"><span class="metric-icon">◉</span><div><strong>${overview.active_sessions}</strong><small>Active sessions</small></div></div><div class="metric"><span class="metric-icon">⊘</span><div><strong>${overview.disabled_users}</strong><small>Disabled accounts</small></div></div></div>
      <section class="owner-panel"><div class="section-header"><div><h3>Secret site controls</h3><p>Owner-only options, validated on the server.</p></div></div>
      <label class="owner-switch"><span><strong>Allow new Google registrations</strong><small>Turn this off to lock registrations to existing accounts.</small></span><input id="owner-signups" type="checkbox" ${overview.allow_signups?'checked':''}></label>
      <label for="owner-notice" class="owner-label">Announcement to signed-in members (optional)</label><textarea class="input owner-textarea" id="owner-notice" maxlength="300" placeholder="Welcome to Konzei Clips">${esc(overview.site_notice||'')}</textarea><button class="btn btn-primary" data-action="save-owner-settings">Save site controls</button></section>
      <section class="owner-panel"><div class="section-header"><div><h3>Private member directory</h3><p>Visible only to you. Disable accounts to revoke their sessions.</p></div></div>
      <div class="owner-table"><div class="owner-user owner-user-heading"><span>Google account</span><span>Role</span><span>Joined</span><span>Access</span></div>${users.map(u=>`<div class="owner-user"><div class="owner-user-primary"><strong>${esc(u.display_name)}</strong><small>${esc(u.email)}</small></div><span class="tag">${u.role==='owner'?'♛ Owner':'Member'}</span><span>${dateLabel(u.created_at)}</span><div>${u.role==='owner'?'<span class="tag">Protected</span>':`<button class="btn btn-sm ${u.disabled?'btn-primary':'btn-danger'}" data-action="toggle-account" data-sub="${esc(u.google_sub)}" data-disabled="${u.disabled?'0':'1'}">${u.disabled?'Enable':'Disable'}</button>`}</div></div>`).join('')}</div></section>`;
  } catch (error) {main.innerHTML=`<div class="empty-state"><h3>Cannot open owner dashboard</h3><p>${esc(error.message)}</p></div>`;}
}
async function saveOwnerSettings() {
  try {
    await api('/api/owner/settings',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({allow_signups:$('#owner-signups').checked,site_notice:$('#owner-notice').value})});
    toast('Owner settings saved.','good');await renderOwner();
  }catch(err){toast(err.message,'error');}
}
async function toggleAccount(sub,disabled) {
  if (!confirm(`${disabled?'Disable':'Enable'} this Konzei account?`)) return;
  try {await api(`/api/owner/users/${encodeURIComponent(sub)}/access`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({disabled})});toast('Account access updated.','good');await renderOwner();}
  catch(err){toast(err.message,'error');}
}

// Single delegated action handler keeps every visible button functional after re-render.
document.addEventListener('click',async event=>{
 const nav=event.target.closest('[data-view]');
 if(nav){setView(nav.dataset.view);return;}
 const tab=event.target.closest('[data-tab]');if(tab){changeStudioTab(tab.dataset.tab);return;}
 const btn=event.target.closest('[data-action]');if(!btn)return;
 const action=btn.dataset.action;
 if(action==='upload') $('#file-picker').click();
 else if(action==='import-url') await importUrl();
 else if(action==='open-project') await openProject(btn.dataset.id);
 else if(action==='delete-project') await deleteProject(btn.dataset.id);
 else if(action==='back-projects') setView('projects');
 else if(action==='analyze') await analyzeVideo();
 else if(action==='pick-highlight') selectHighlight(Number(btn.dataset.index));
 else if(action==='ratio'){option('ratio',btn.dataset.ratio);changeStudioTab('edit');}
 else if(action==='show-edit') changeStudioTab('edit');
 else if(action==='export') await exportClip();
 else if(action==='export-all') await exportAll();
 else if(action==='save-recipe') await saveRecipe();
 else if(action==='apply-recipe') await applyRecipe(btn.dataset.id);
 else if(action==='delete-recipe') await deleteRecipe(btn.dataset.id);
 else if(action==='save-owner-settings') await saveOwnerSettings();
 else if(action==='toggle-account') await toggleAccount(btn.dataset.sub,btn.dataset.disabled==='1');
 else if(action==='signout') await signOut();
});
$('#new-project').addEventListener('click',()=>$('#file-picker').click());
$('#sign-out').addEventListener('click',signOut);
$('#file-picker').addEventListener('change',event=>uploadVideo(event.target.files[0]));
document.addEventListener('change',event=>{
 const input=event.target;
 if(input.matches('[data-opt]')){
  const type=input.type,val=type==='checkbox'?input.checked:type==='number'||type==='range'||input.tagName==='SELECT'&&['crf'].includes(input.dataset.opt)?Number(input.value):input.value;
  option(input.dataset.opt,val);
  if(input.dataset.opt==='crop_mode'||input.dataset.opt==='caption_style') return;
 }
 if(input.matches('[data-analysis]')){const key=input.dataset.analysis;state.analysis[key]=input.type==='checkbox'?input.checked:input.tagName==='SELECT'?Number(input.value):input.value;}
});
document.addEventListener('input',event=>{
 const input=event.target;
 if(input.matches('textarea[data-analysis]'))state.analysis[input.dataset.analysis]=input.value;
 if(input.matches('[data-opt]')&&(input.type==='range'||input.type==='text'||input.tagName==='TEXTAREA')){
   option(input.dataset.opt,input.type==='range'?Number(input.value):input.value);
   if(input.dataset.opt==='focus_x'){const label=input.closest('.control-group')?.querySelector('.label-tip');if(label)label.textContent=`${Math.round(Number(input.value)*100)}%`;}
 }
});
document.addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.id==='url-input')importUrl();});
boot();
