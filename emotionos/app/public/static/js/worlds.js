const worldState = {
  scene: null,
  readiness: null,
  pollTimer: null,
  audio: null,
  recorder: null,
  mediaStream: null,
  recordingChunks: [],
  recordingTimer: null,
  lastRenderedTurnId: null,
  currentView: null,
  voiceMode: false,
  turnSubmitting: false,
  autoListenTimer: null,
  recognition: null,
  sceneRecognition: null,
  sceneDictationTimer: null,
  speechVoiceBySpeaker: {},
  voiceInputTimer: null,
  suppressRecognitionEndSubmit: false,
  lastVoiceSubmittedText: '',
  lastVoiceSubmittedAt: 0
};

const recentSceneStorageKey = 'rolebricks.recent-scenes.v1';
const featuredSceneIds = ['a4d3a306-7624-458d-b8dd-4ec1ad70a281'];
const voiceSilenceMs = 1300;
const voiceFastSilenceMs = 760;
const sceneDictationSilenceMs = 2200;
const voiceNoiseTokens = new Set(['h', 'hi', 'hii', 'hiii', 'hello', 'uh', 'um', 'umm', 'mmm', 'a', 'aa', 'aaa']);

const worldViews = {
  describe: '#sceneStart',
  blueprint: '#blueprintView',
  preparing: '#preparationView',
  ready: '#readyView',
  live: '#liveView',
  completed: '#afterView'
};

const preparationOrder = [
  'resolving_scene',
  'compiling_personas',
  'preparing_voices',
  'initializing_memory',
  'ready'
];

function refreshIcons() {
  window.lucide?.createIcons({ attrs: { 'aria-hidden': 'true' } });
}

function updateVoiceModeUi() {
  const button = $('#voiceModeToggle');
  if (!button) return;
  button.classList.toggle('is-active', worldState.voiceMode);
  button.setAttribute('aria-pressed', worldState.voiceMode ? 'true' : 'false');
  button.setAttribute('aria-label', worldState.voiceMode ? 'Turn off voice mode' : 'Turn on voice mode');
  button.title = worldState.voiceMode ? 'Voice mode on' : 'Voice mode';
  const icon = button.querySelector('i');
  if (icon) icon.dataset.lucide = worldState.voiceMode ? 'radio-tower' : 'radio';
  const label = button.querySelector('span');
  if (label) label.textContent = worldState.voiceMode ? 'Voice on' : 'Voice mode';
  refreshIcons();
}

function clearAutoListen() {
  if (worldState.autoListenTimer) {
    window.clearTimeout(worldState.autoListenTimer);
    worldState.autoListenTimer = null;
  }
}

function scheduleAutoListen() {
  clearAutoListen();
  if (worldState.audio && 'speechSynthesis' in window && !speechSynthesis.speaking) worldState.audio = null;
  if (worldState.audio?.ended) worldState.audio = null;
  if (!worldState.voiceMode || worldState.scene?.status !== 'live') return;
  if (worldState.recognition || worldState.recorder?.state === 'recording' || worldState.turnSubmitting || worldState.audio) return;
  worldState.autoListenTimer = window.setTimeout(() => {
    if (worldState.voiceMode && worldState.scene?.status === 'live' && !worldState.audio) {
      startAutoVoiceTurn();
    }
  }, 120);
}

function setWorldView(view) {
  const changed = worldState.currentView !== view;
  worldState.currentView = view;
  Object.entries(worldViews).forEach(([name, selector]) => {
    $(selector)?.classList.toggle('is-hidden', name !== view);
  });
  const stepForView = {
    describe: 'describe',
    blueprint: 'blueprint',
    preparing: 'preparing',
    ready: 'live',
    live: 'live',
    completed: 'live'
  }[view];
  const steps = ['describe', 'blueprint', 'preparing', 'live'];
  const activeIndex = steps.indexOf(stepForView);
  $$('[data-scene-step]').forEach((element, index) => {
    element.classList.toggle('is-active', index === activeIndex);
    element.classList.toggle('is-complete', index < activeIndex);
  });
  if (changed) window.scrollTo({ top: 0, behavior: 'smooth' });
  refreshIcons();
  updateVoiceModeUi();
}

function setWorldBusy(button, busy, label = 'Working...') {
  if (!button) return;
  if (busy) {
    button.dataset.originalMarkup = button.innerHTML;
    button.textContent = label;
    button.disabled = true;
  } else {
    if (button.dataset.originalMarkup !== undefined) button.innerHTML = button.dataset.originalMarkup;
    button.disabled = false;
  }
  refreshIcons();
}

function setSceneHash(sceneId) {
  history.replaceState(null, '', sceneId ? `#scene=${sceneId}` : location.pathname);
  if (sceneId) rememberScene(sceneId);
}

function sceneIdFromHash() {
  const match = location.hash.match(/^#scene=([0-9a-f-]{36})$/i);
  return match?.[1] || null;
}

async function initializeWorlds() {
  bindWorldEvents();
  updatePromptCount();
  await loadWorldReadiness();
  const sceneId = sceneIdFromHash();
  if (sceneId) {
    try {
      await loadWorldScene(sceneId);
      return;
    } catch (error) {
      toast(error.message);
      setSceneHash(null);
    }
  }
  setWorldView('describe');
  await loadRecentScenes();
}

async function loadWorldReadiness() {
  const statusElement = $('#providerStatus');
  try {
    const readiness = await api('/api/ready');
    worldState.readiness = readiness;
    const sceneReady = Boolean(
      readiness.scene_compiler_ready &&
      readiness.scene_research_ready &&
      readiness.scene_retrieval_ready &&
      readiness.scene_indexing_ready &&
      readiness.scene_telemetry_ready &&
      readiness.lakebase_ready &&
      readiness.ready
    );
    statusElement?.classList.toggle('ready', sceneReady);
    statusElement?.classList.toggle('not-ready', !sceneReady);
    const label = statusElement?.querySelector('span');
    if (label) label.textContent = sceneReady ? 'Scene engine ready' : 'Setup required';

    const missing = [];
    if (!readiness.scene_compiler_ready) missing.push('Databricks model endpoint');
    if (!readiness.scene_research_ready) missing.push('research API');
    if (!readiness.scene_retrieval_ready) missing.push('AI Search memory');
    if (!readiness.scene_indexing_ready) missing.push('Delta memory writer');
    if (!readiness.scene_telemetry_ready) missing.push('MLflow tracing');
    if (!readiness.lakebase_ready) missing.push('Lakebase');
    if (!readiness.ready) missing.push('voice provider');
    const notice = $('#runtimeNotice');
    notice?.classList.toggle('is-hidden', missing.length === 0);
    if (notice && missing.length) {
      notice.textContent = `Configuration needed: ${missing.join(', ')}. The app will not switch to a fallback provider.`;
    }
  } catch (error) {
    statusElement?.classList.add('not-ready');
    const label = statusElement?.querySelector('span');
    if (label) label.textContent = 'Engine unavailable';
  }
}

async function loadRecentScenes() {
  const container = $('#recentScenes');
  const list = $('#recentSceneList');
  if (!container || !list) return;
  const ids = [...featuredSceneIds, ...recentSceneIds().filter((sceneId) => !featuredSceneIds.includes(sceneId))];
  if (!ids.length) return;

  const scenes = (await Promise.all(ids.map(async (sceneId) => {
    try {
      const scene = await api(`/api/worlds/${sceneId}`);
      return { scene, featured: featuredSceneIds.includes(sceneId) };
    } catch (_) {
      if (!featuredSceneIds.includes(sceneId)) forgetScene(sceneId);
      return null;
    }
  }))).filter(Boolean);

  if (!scenes.length) {
    container.classList.add('is-hidden');
    return;
  }
  list.innerHTML = scenes.map(({ scene, featured }) => `
    <article class="recent-scene${featured ? ' is-featured' : ''}" data-scene-card="${scene.id}">
      <button class="recent-scene-main" type="button" data-load-scene="${scene.id}" aria-label="Open ${escapeHtml(scene.manifest.title)}">
        <strong>${escapeHtml(scene.manifest.title)}</strong>
        <span>${featured ? 'Featured demo' : escapeHtml(scene.status.replace('_', ' '))}</span>
      </button>
      <button class="recent-scene-action" type="button" data-load-scene="${scene.id}">Open</button>
      ${featured ? '' : `<button class="recent-scene-action danger-action" type="button" data-delete-recent-scene="${scene.id}">Delete</button>`}
    </article>
  `).join('');
  container.classList.remove('is-hidden');
}

function recentSceneIds() {
  try {
    const stored = JSON.parse(localStorage.getItem(recentSceneStorageKey) || '[]');
    return Array.isArray(stored)
      ? stored.filter((value) => /^[0-9a-f-]{36}$/i.test(value)).slice(0, 6)
      : [];
  } catch (_) {
    return [];
  }
}

function rememberScene(sceneId) {
  const next = [sceneId, ...recentSceneIds().filter((value) => value !== sceneId)].slice(0, 6);
  localStorage.setItem(recentSceneStorageKey, JSON.stringify(next));
}

function forgetScene(sceneId) {
  const next = recentSceneIds().filter((value) => value !== sceneId);
  localStorage.setItem(recentSceneStorageKey, JSON.stringify(next));
}

async function deleteRecentScene(sceneId) {
  if (!sceneId || !confirm('Delete this scene and its generated audio? This cannot be undone.')) return;
  try {
    await api(`/api/worlds/${sceneId}`, { method: 'DELETE' });
    forgetScene(sceneId);
    if (worldState.scene?.id === sceneId) resetWorldComposer();
    await loadRecentScenes();
    toast('Scene deleted.');
  } catch (error) { toast(error.message); }
}
async function loadWorldScene(sceneId) {
  const scene = await api(`/api/worlds/${sceneId}`);
  worldState.scene = scene;
  setSceneHash(scene.id);
  renderWorldScene(scene);
}

function renderWorldScene(scene) {
  clearWorldPoll();
  worldState.scene = scene;
  renderEvidence(scene);
  if (scene.status === 'draft' || scene.status === 'blueprint') {
    const failed = scene.preparation_job?.status === 'failed';
    if (failed) {
      renderPreparation(scene);
    } else {
      renderBlueprint(scene);
    }
    return;
  }
  if (scene.status === 'confirmed' || scene.status === 'preparing') {
    renderPreparation(scene);
    beginWorldPoll(scene.id);
    return;
  }
  if (scene.status === 'ready') {
    renderReady(scene);
    return;
  }
  if (scene.status === 'live' || scene.status === 'paused') {
    renderLive(scene);
    return;
  }
  if (scene.status === 'completed') {
    renderAfter(scene);
  }
}

function updatePromptCount() {
  const input = $('#scenePrompt');
  const counter = $('#promptCount');
  if (input && counter) counter.textContent = `${input.value.length} / 5000`;
}

async function createWorldScene(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const prompt = $('#scenePrompt').value.trim();
  if (prompt.length < 20) {
    toast('Describe the situation in a little more detail.');
    return;
  }
  setWorldBusy(button, true, 'Compiling...');
  try {
    const scene = await api('/api/worlds/draft', {
      method: 'POST',
      body: JSON.stringify({
        prompt,
        locale: navigator.language || 'en-IN'
      })
    });
    worldState.scene = scene;
    setSceneHash(scene.id);
    renderBlueprint(scene);
  } catch (error) {
    toast(error.message);
  } finally {
    setWorldBusy(button, false);
    refreshIcons();
  }
}

function renderBlueprint(scene) {
  const manifest = scene.manifest;
  $('#blueprintTitle').textContent = manifest.title;
  $('#blueprintSummary').textContent = manifest.scenario_summary;
  $('#userRoleName').value = manifest.user_role.name;
  $('#userRole').value = manifest.user_role.role;
  $('#userObjective').value = manifest.user_role.objective;
  $('#sceneSetting').value = manifest.setting;
  $('#sceneStakes').value = manifest.stakes;
  const pressure = $(`input[name="pressure"][value="${manifest.pressure}"]`);
  if (pressure) pressure.checked = true;
  $('#blueprintSaveState').textContent = `Version ${scene.active_manifest_version} - no preparation started`;

  const versionSelect = $('#versionSelect');
  versionSelect.innerHTML = scene.versions
    .slice()
    .reverse()
    .map((version) => `
      <option value="${version.version_number}" ${version.version_number === scene.active_manifest_version ? 'selected' : ''}>
        Version ${version.version_number}
      </option>
    `).join('');

  $('#castList').innerHTML = manifest.ai_characters.map((character, index) => castRow(character, index)).join('');
  updateCastCount();
  setWorldView('blueprint');
}

function castRow(character, index) {
  const speech = character.speech || {};
  const voice = character.voice || {};
  return `
    <article class="cast-row ${character.selected ? 'is-selected' : ''}" data-character-index="${index}">
      <div class="cast-row-head">
        <label class="cast-check" title="Include ${escapeHtml(character.name)}">
          <input type="checkbox" data-cast-selected ${character.selected ? 'checked' : ''} aria-label="Include ${escapeHtml(character.name)}">
        </label>
        <input type="text" data-cast-name value="${escapeHtml(character.name)}" maxlength="120" aria-label="Character name">
        <div class="cast-role">
          <input type="text" data-cast-role value="${escapeHtml(character.role)}" maxlength="240" aria-label="Character role">
        </div>
        <button class="cast-edit" type="button" data-edit-cast aria-label="Edit ${escapeHtml(character.name)}" title="Edit character">
          <i data-lucide="sliders-horizontal"></i>
        </button>
      </div>
      <div class="cast-details">
        <label class="cast-summary-field">Persona
          <textarea data-cast-summary rows="3" maxlength="1000">${escapeHtml(character.summary)}</textarea>
        </label>
        <label>Language
          <select data-speech-language>
            ${optionList(['English', 'Hindi', 'Hinglish'], speech.language || 'English')}
          </select>
        </label>
        <label>Region
          <select data-speech-region>
            ${optionList(['India', 'United Kingdom', 'Global'], speech.region || 'India')}
          </select>
        </label>
        <label>Accent
          <select data-speech-accent>
            ${optionList(['Indian', 'British', 'Neutral'], speech.accent || 'Indian')}
          </select>
        </label>
        <label>Voice
          <select data-voice-presentation>
            ${optionList(['feminine', 'masculine', 'androgynous'], voice.presentation || 'androgynous', true)}
          </select>
        </label>
        <label>Dialect
          <input data-speech-dialect value="${escapeHtml(speech.dialect || '')}" maxlength="120" placeholder="Optional">
        </label>
        <label>Code-mixing
          <input data-speech-code-mixing value="${escapeHtml(speech.code_mixing || 'natural')}" maxlength="160">
        </label>
        <p class="cast-selection-note">${escapeHtml(character.selection_reason || '')}</p>
        ${character.portrayal_notice ? `<p class="simulation-notice">${escapeHtml(character.portrayal_notice)}</p>` : ''}
      </div>
    </article>
  `;
}

function optionList(options, selected, titleCase = false) {
  return options.map((value) => {
    const label = titleCase ? value.charAt(0).toUpperCase() + value.slice(1) : value;
    return `<option value="${escapeHtml(value)}" ${value === selected ? 'selected' : ''}>${escapeHtml(label)}</option>`;
  }).join('');
}

function updateCastCount() {
  const selected = $$('[data-cast-selected]:checked').length;
  $('#castCount').textContent = `${selected} of 5 AI respondents selected. Human user is separate.`;
}

function toggleCastSelection(input) {
  if (input.checked && $$('[data-cast-selected]:checked').length > 5) {
    input.checked = false;
    toast('This MVP supports up to five AI respondents plus the human user.');
  }
  input.closest('.cast-row')?.classList.toggle('is-selected', input.checked);
  updateCastCount();
}

function collectBlueprint() {
  const scene = worldState.scene;
  const characters = $$('.cast-row').map((row) => {
    const index = Number(row.dataset.characterIndex);
    const character = structuredClone(scene.manifest.ai_characters[index]);
    character.selected = row.querySelector('[data-cast-selected]').checked;
    character.name = row.querySelector('[data-cast-name]').value.trim();
    character.role = row.querySelector('[data-cast-role]').value.trim();
    character.summary = row.querySelector('[data-cast-summary]').value.trim();
    character.speech.language = row.querySelector('[data-speech-language]').value;
    character.speech.region = row.querySelector('[data-speech-region]').value;
    character.speech.accent = row.querySelector('[data-speech-accent]').value;
    character.speech.dialect = row.querySelector('[data-speech-dialect]').value.trim();
    character.speech.code_mixing = row.querySelector('[data-speech-code-mixing]').value.trim() || 'natural';
    character.voice.presentation = row.querySelector('[data-voice-presentation]').value;
    return character;
  });
  const selectedCount = characters.filter((character) => character.selected).length;
  if (selectedCount < 1 || selectedCount > 5) {
    throw new Error('Select between one and five AI respondents. The human user is separate.');
  }
  return {
    expected_version: scene.active_manifest_version,
    user_role: {
      ...scene.manifest.user_role,
      name: $('#userRoleName').value.trim() || 'You',
      role: $('#userRole').value.trim(),
      objective: $('#userObjective').value.trim()
    },
    ai_characters: characters,
    setting: $('#sceneSetting').value.trim(),
    stakes: $('#sceneStakes').value.trim(),
    pressure: $('input[name="pressure"]:checked')?.value || 'realistic',
    change_reason: 'Scene setup reviewed'
  };
}

async function saveBlueprint(reason = 'Scene setup reviewed') {
  const payload = collectBlueprint();
  payload.change_reason = reason;
  const scene = await api(`/api/worlds/${worldState.scene.id}/blueprint`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  });
  worldState.scene = scene;
  renderEvidence(scene);
  return scene;
}

async function handleSaveBlueprint() {
  const button = $('#saveBlueprint');
  setWorldBusy(button, true, 'Saving...');
  try {
    const scene = await saveBlueprint('Blueprint saved by user');
    renderBlueprint(scene);
    toast('Blueprint saved.');
  } catch (error) {
    toast(error.message);
  } finally {
    setWorldBusy(button, false);
  }
}

async function handleBuildScene() {
  const button = $('#buildScene');
  setWorldBusy(button, true, 'Confirming...');
  try {
    const scene = await saveBlueprint('Confirmed scene setup');
    await api(`/api/worlds/${scene.id}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ expected_version: scene.active_manifest_version })
    });
    await loadWorldScene(scene.id);
  } catch (error) {
    toast(error.message);
  } finally {
    setWorldBusy(button, false);
    refreshIcons();
  }
}

async function handleRevertVersion() {
  const targetVersion = Number($('#versionSelect').value);
  const scene = worldState.scene;
  if (targetVersion === scene.active_manifest_version) {
    toast('That is already the active blueprint.');
    return;
  }
  try {
    const reverted = await api(`/api/worlds/${scene.id}/revert`, {
      method: 'POST',
      body: JSON.stringify({
        expected_version: scene.active_manifest_version,
        target_version: targetVersion
      })
    });
    worldState.scene = reverted;
    renderBlueprint(reverted);
    toast(`Restored blueprint ${targetVersion} as a new version.`);
  } catch (error) {
    toast(error.message);
  }
}

function renderPreparation(scene) {
  const job = scene.preparation_job;
  const stage = job?.stage || 'queued';
  const progress = job?.progress || 0;
  $('#preparationStage').textContent = stage.replaceAll('_', ' ');
  $('#preparationPercent').textContent = `${progress}%`;
  $('#preparationBar').style.width = `${progress}%`;
  $('#preparationMessage').textContent = scene.preparation?.message || 'Preparing the confirmed scene.';

  const activeIndex = Math.max(0, preparationOrder.indexOf(stage));
  $$('#pipelineStages li').forEach((item, index) => {
    item.classList.toggle('is-active', index === activeIndex && job?.status !== 'failed');
    item.classList.toggle('is-complete', index < activeIndex || stage === 'ready');
  });

  const failed = job?.status === 'failed';
  $('#preparationError').classList.toggle('is-hidden', !failed);
  $('#preparationErrorText').textContent = failed
    ? job.error_message || 'Preparation stopped before any fallback provider was used.'
    : '';
  setWorldView('preparing');
}

function beginWorldPoll(sceneId) {
  clearWorldPoll();
  worldState.pollTimer = window.setInterval(async () => {
    try {
      const scene = await api(`/api/worlds/${sceneId}`);
      worldState.scene = scene;
      renderEvidence(scene);
      if (scene.status === 'ready') {
        clearWorldPoll();
        renderReady(scene);
        return;
      }
      if (scene.preparation_job?.status === 'failed') {
        clearWorldPoll();
      }
      renderPreparation(scene);
    } catch (error) {
      clearWorldPoll();
      toast(error.message);
    }
  }, 900);
}

function clearWorldPoll() {
  if (worldState.pollTimer) {
    window.clearInterval(worldState.pollTimer);
    worldState.pollTimer = null;
  }
}

function renderReady(scene) {
  $('#readyTitle').textContent = scene.manifest.title;
  $('#readySummary').textContent = scene.manifest.scenario_summary;
  $('#readyUserRole').textContent = `${scene.manifest.user_role.name} - ${scene.manifest.user_role.role}`;
  $('#readyCast').innerHTML = scene.agents.map((agent, index) => {
    const speech = agent.voice_profile.speech || {};
    const profile = agent.profile || {};
    const portrayalNotice = profile.portrayal_notice || '';
    return `
      <article class="ready-character">
        <span class="character-index">0${index + 1}</span>
        <h2>${escapeHtml(agent.name)}</h2>
        <p>${escapeHtml(agent.role)}</p>
        ${portrayalNotice ? `<p class="simulation-notice">${escapeHtml(portrayalNotice)}</p>` : ''}
        <div class="character-voice">
          <button type="button" data-play-audio="${escapeHtml(agent.voice_profile.sample_audio_url || '')}" aria-label="Play ${escapeHtml(agent.name)} voice" title="Play voice sample">
            <i data-lucide="play"></i>
          </button>
          <span>${escapeHtml([speech.language, speech.accent].filter(Boolean).join(' - '))}</span>
        </div>
      </article>
    `;
  }).join('');
  setWorldView('ready');
}

async function enterWorldScene() {
  const button = $('#enterScene');
  setWorldBusy(button, true, 'Entering...');
  try {
    const scene = await api(`/api/worlds/${worldState.scene.id}/enter`, { method: 'POST' });
    worldState.scene = scene;
    renderLive(scene);
  } catch (error) {
    toast(error.message);
  } finally {
    setWorldBusy(button, false);
    refreshIcons();
  }
}

function renderLive(scene) {
  updateVoiceModeUi();
  const paused = scene.status === 'paused';
  $('#liveStatus').textContent = paused ? 'Scene paused' : 'Live scene';
  $('#liveTitle').textContent = scene.manifest.title;
  $('#turnText').disabled = paused;
  $('#turnForm button[type="submit"]').disabled = paused;
  $('#recordTurn').disabled = paused;
  const pauseIcon = $('#pauseScene i');
  if (pauseIcon) pauseIcon.dataset.lucide = paused ? 'play' : 'pause';
  $('#pauseScene').setAttribute('aria-label', paused ? 'Resume scene' : 'Pause scene');
  $('#pauseScene').title = paused ? 'Resume scene' : 'Pause scene';

  const latestAgentKey = [...scene.turns].reverse().find((turn) => turn.speaker_type === 'agent')?.speaker_key;
  $('#liveCast').innerHTML = scene.agents.map((agent) => `
    <div class="live-cast-person ${agent.key === latestAgentKey ? 'is-speaking' : ''}" data-live-agent="${escapeHtml(agent.key)}">
      <strong>${escapeHtml(agent.name)}</strong>
      <span>${escapeHtml(agent.role + (agent.profile?.identity_kind === 'public_figure' ? ' - Public-info simulation' : ''))}</span>
    </div>
  `).join('');

  const transcript = $('#sceneTranscript');
  const shouldStickToBottom = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 96;
  transcript.innerHTML = scene.turns.length ? scene.turns.map((turn) => `
    <article class="turn ${turn.speaker_type === 'user' ? 'is-user' : 'is-agent'}" data-turn-id="${turn.id}">
      <div class="turn-meta">
        <strong>${escapeHtml(turn.speaker_name)}</strong>
        <span>${escapeHtml(turn.action.replaceAll('_', ' '))}</span>
      </div>
      <p>${escapeHtml(turn.text)}</p>
      ${turn.audio_url ? `
        <button class="turn-audio" type="button" data-play-audio="${escapeHtml(turn.audio_url)}" data-speaker-key="${escapeHtml(turn.speaker_key || '')}" aria-label="Play response" title="Play response">
          <i data-lucide="volume-2"></i>
        </button>
      ` : ''}
    </article>
  `).join('') : '<div class="empty-transcript">Speak or type first. The AI respondents will wait for you.</div>';
  if (shouldStickToBottom) requestAnimationFrame(() => { transcript.scrollTop = transcript.scrollHeight; });
  worldState.lastRenderedTurnId = scene.turns.at(-1)?.id || null;
  setWorldView('live');
}

function renderPendingUserTurn(text) {
  const transcript = $('#sceneTranscript');
  if (!transcript || !text) return;
  const empty = transcript.querySelector('.empty-transcript');
  if (empty) transcript.innerHTML = '';
  const pending = document.createElement('article');
  pending.className = 'turn is-user is-pending';
  pending.innerHTML = `
    <div class="turn-meta"><strong>You</strong><span>sending</span></div>
    <p>${escapeHtml(text)}</p>
  `;
  transcript.appendChild(pending);
  transcript.scrollTop = transcript.scrollHeight;
}

async function submitWorldTurn(event) {
  event.preventDefault();
  const textInput = $('#turnText');
  const text = textInput.value.trim();
  if (!text) return;
  const button = event.currentTarget.querySelector('button[type="submit"]');
  setWorldBusy(button, true, '');
  textInput.disabled = true;
  worldState.turnSubmitting = true;
  clearAutoListen();
  clearVoiceInputTimer();
  renderPendingUserTurn(text);
  try {
    const previousLastId = worldState.scene.turns.at(-1)?.id;
    const scene = await api(`/api/worlds/${worldState.scene.id}/turns`, {
      method: 'POST',
      body: JSON.stringify({ text, voice_mode: worldState.voiceMode })
    });
    worldState.scene = scene;
    textInput.value = '';
    renderLive(scene);
    const latest = scene.turns.at(-1);
    if (latest?.id !== previousLastId && latest?.audio_url) {
      playWorldAudio(latest.audio_url, latest.speaker_key);
    } else if (latest?.id !== previousLastId && worldState.voiceMode) {
      speakWorldText(latest.text, latest.speaker_key);
    } else if (latest?.audio_data?.status === 'failed') {
      toast(`Voice was not generated: ${latest.audio_data.error}`);
    }
  } catch (error) {
    toast(error.message);
  } finally {
    textInput.disabled = worldState.scene?.status === 'paused';
    worldState.turnSubmitting = false;
    setWorldBusy(button, false);
    if (worldState.recorder?.state !== 'recording') setTurnRecordingUi('idle');
    refreshIcons();
    if (worldState.voiceMode && !worldState.audio && !worldState.turnSubmitting) scheduleAutoListen();
  }
}

async function togglePauseScene() {
  clearAutoListen();
  const scene = worldState.scene;
  try {
    if (scene.status === 'paused') {
      await api(`/api/worlds/${scene.id}/resume`, { method: 'POST' });
      const active = await api(`/api/worlds/${scene.id}/enter`, { method: 'POST' });
      worldState.scene = active;
      renderLive(active);
    } else {
      const paused = await api(`/api/worlds/${scene.id}/pause`, { method: 'POST' });
      worldState.scene = paused;
      stopWorldAudio();
      renderLive(paused);
    }
  } catch (error) {
    toast(error.message);
  }
}

async function completeWorldScene() {
  if (!worldState.scene) return;
  const button = $('#completeScene');
  button.disabled = true;
  worldState.voiceMode = false;
  updateVoiceModeUi();
  clearAutoListen();
  try {
    const scene = await api(`/api/worlds/${worldState.scene.id}/complete`, { method: 'POST' });
    worldState.scene = scene;
    stopWorldAudio();
    renderAfter(scene);
    toast('Scene saved.');
  } catch (error) {
    const localScene = { ...worldState.scene, status: 'completed' };
    worldState.scene = localScene;
    stopWorldAudio();
    renderAfter(localScene);
    toast(`Scene closed locally. Server memory sync: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

function renderAfter(scene) {
  const userTurns = scene.turns.filter((turn) => turn.speaker_type === 'user').length;
  $('#afterSummary').textContent = `${scene.agents.length} characters shared ${scene.turns.length} turns with you. Their episodic memory and scene reflections remain attached to this world.`;
  $('#rememberedCast').innerHTML = scene.agents.map((agent) => `
    <article class="remembered-person">
      <h2>${escapeHtml(agent.name)}</h2>
      <p>${escapeHtml(agent.role)}</p>
      <span>${Number(agent.runtime_state.turn_count || 0)} responses - ${escapeHtml(agent.runtime_state.mood || 'focused')}</span>
    </article>
  `).join('');
  $('#afterTitle').textContent = userTurns ? 'This world remembers.' : 'The scene is saved.';
  setWorldView('completed');
}

async function resumeCompletedScene() {
  try {
    await api(`/api/worlds/${worldState.scene.id}/resume`, { method: 'POST' });
    const scene = await api(`/api/worlds/${worldState.scene.id}/enter`, { method: 'POST' });
    worldState.scene = scene;
    renderLive(scene);
  } catch (error) {
    toast(error.message);
  }
}

function renderEvidence(scene) {
  const list = $('#evidenceList');
  if (!list) return;
  if (!scene.sources.length) {
    list.innerHTML = '<p class="empty-evidence">This scene did not require fresh public sources. Persona and user-provided facts remain separate from respondent evidence.</p>';
    return;
  }
  list.innerHTML = scene.sources.map((source) => `
    <a class="evidence-item" href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">
      <span>${escapeHtml([source.agent_key ? `For ${source.agent_key}` : 'Scene', source.freshness].join(' - '))}</span>
      <strong>${escapeHtml(source.title)}</strong>
      <p>${escapeHtml(source.snippet)}</p>
    </a>
  `).join('');
}

function speakWorldText(text, speakerKey = '') {
  if (!text || !('speechSynthesis' in window)) {
    scheduleAutoListen();
    return;
  }
  stopWorldAudio();
  const utterance = new SpeechSynthesisUtterance(text);
  const stableVoice = pickSpeechVoice(speakerKey);
  if (stableVoice) {
    utterance.voice = stableVoice;
    utterance.lang = stableVoice.lang || 'en-IN';
  } else {
    utterance.lang = navigator.language || 'en-IN';
  }
  utterance.rate = 1.08;
  utterance.pitch = 1;
  worldState.audio = { pause: () => speechSynthesis.cancel(), currentTime: 0 };
  if (speakerKey) {
    $$('[data-live-agent]').forEach((element) => {
      element.classList.toggle('is-speaking', element.dataset.liveAgent === speakerKey);
    });
  }
  utterance.onend = utterance.onerror = () => {
    worldState.audio = null;
    $$('[data-live-agent]').forEach((element) => element.classList.remove('is-speaking'));
    scheduleAutoListen();
  };
  speechSynthesis.cancel();
  speechSynthesis.speak(utterance);
  window.setTimeout(() => {
    if (worldState.voiceMode && worldState.audio) {
      worldState.audio = null;
      $$('[data-live-agent]').forEach((element) => element.classList.remove('is-speaking'));
      scheduleAutoListen();
    }
  }, Math.max(1800, text.length * 62));
}
function stableHash(value) {
  return String(value || 'rolebricks').split('').reduce((hash, char) => {
    return ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  }, 0);
}

function pickSpeechVoice(speakerKey = 'default') {
  if (!('speechSynthesis' in window)) return null;
  const voices = speechSynthesis.getVoices();
  if (!voices.length) return null;
  const cacheKey = speakerKey || 'default';
  const cached = voices.find((voice) => voice.voiceURI === worldState.speechVoiceBySpeaker[cacheKey]);
  if (cached) return cached;
  const preferred = voices.filter((voice) => /^(en-IN|hi-IN|en-GB|en-US)/i.test(voice.lang));
  const pool = preferred.length ? preferred : voices;
  const selected = pool[Math.abs(stableHash(cacheKey)) % pool.length];
  worldState.speechVoiceBySpeaker[cacheKey] = selected.voiceURI;
  return selected;
}
function playWorldAudio(url, speakerKey = '') {
  if (!url) return;
  stopWorldAudio();
  const audio = new Audio(url);
  worldState.audio = audio;
  if (speakerKey) {
    $$('[data-live-agent]').forEach((element) => {
      element.classList.toggle('is-speaking', element.dataset.liveAgent === speakerKey);
    });
  }
  audio.addEventListener('ended', () => {
    worldState.audio = null;
    $$('[data-live-agent]').forEach((element) => element.classList.remove('is-speaking'));
    scheduleAutoListen();
  }, { once: true });
  audio.play().catch(() => {
    worldState.audio = null;
    $$('[data-live-agent]').forEach((element) => element.classList.remove('is-speaking'));
    toast('Press play again to hear the voice.');
    scheduleAutoListen();
  });
}

function stopWorldAudio() {
  clearAutoListen();
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  stopAutoVoiceTurn();
  if (worldState.audio) {
    worldState.audio.pause();
    worldState.audio.currentTime = 0;
    worldState.audio = null;
  }
}

function setSceneDictationUi(recording) {
  const button = $('#dictateScene');
  if (!button) return;
  button.classList.toggle('is-recording', recording);
  button.setAttribute('aria-label', recording ? 'Stop describing' : 'Describe by voice');
  button.title = recording ? 'Stop describing' : 'Describe by voice';
  button.innerHTML = `<i data-lucide="${recording ? 'square' : 'mic'}"></i>`;
  refreshIcons();
}

function normalizeSceneTranscript(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/[^a-z0-9\u0900-\u097f\s']/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function transcriptSimilarity(left, right) {
  const leftTokens = new Set(normalizeSceneTranscript(left).split(' ').filter(Boolean));
  const rightTokens = new Set(normalizeSceneTranscript(right).split(' ').filter(Boolean));
  if (!leftTokens.size || !rightTokens.size) return 0;
  let overlap = 0;
  for (const token of leftTokens) {
    if (rightTokens.has(token)) overlap += 1;
  }
  return overlap / Math.max(leftTokens.size, rightTokens.size);
}

function isUsefulSceneTranscript(text) {
  const tokens = normalizeSceneTranscript(text).split(' ').filter(Boolean);
  const useful = tokens.filter((token) => !voiceNoiseTokens.has(token) && token.length > 1);
  return useful.length >= 3 || useful.join('').length >= 16;
}

function renderSceneDictation(prompt, baseText, finalSegments, interim = '') {
  const cleanInterim = isUsefulSceneTranscript(interim) ? interim : '';
  prompt.value = [baseText, ...finalSegments, cleanInterim]
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
  updatePromptCount();
}

function stopSceneDictation() {
  if (worldState.sceneDictationTimer) {
    window.clearTimeout(worldState.sceneDictationTimer);
    worldState.sceneDictationTimer = null;
  }
  if (!worldState.sceneRecognition) return;
  const recognition = worldState.sceneRecognition;
  worldState.sceneRecognition = null;
  try { recognition.stop(); } catch (_) {}
  setSceneDictationUi(false);
}

function startSceneDictation() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    toast('Voice dictation is not available in this browser.');
    return;
  }
  if (worldState.sceneRecognition) {
    stopSceneDictation();
    return;
  }
  const recognition = new Recognition();
  worldState.sceneRecognition = recognition;
  recognition.lang = navigator.language || 'en-IN';
  recognition.interimResults = true;
  recognition.continuous = true;
  const prompt = $('#scenePrompt');
  const baseText = prompt.value.trim();
  const finalSegments = [];
  const seenSegments = new Set();

  const appendFinalSegment = (transcript) => {
    const segment = String(transcript || '').replace(/\s+/g, ' ').trim();
    const normalized = normalizeSceneTranscript(segment);
    if (!normalized || seenSegments.has(normalized) || !isUsefulSceneTranscript(segment)) return;
    const recentSegments = finalSegments.slice(-6);
    const repeated = recentSegments.some((existing) => {
      const existingNormalized = normalizeSceneTranscript(existing);
      if (existingNormalized === normalized) return true;
      if (normalized.length > 30 && existingNormalized.includes(normalized)) return true;
      if (existingNormalized.length > 30 && normalized.includes(existingNormalized)) return true;
      return transcriptSimilarity(existing, segment) >= 0.86;
    });
    if (repeated) return;
    seenSegments.add(normalized);
    finalSegments.push(segment);
  };

  const resetSilenceTimer = () => {
    if (worldState.sceneDictationTimer) window.clearTimeout(worldState.sceneDictationTimer);
    worldState.sceneDictationTimer = window.setTimeout(() => {
      toast('Voice captured. Tap mic again to add more.');
      stopSceneDictation();
    }, sceneDictationSilenceMs);
  };

  setSceneDictationUi(true);
  resetSilenceTimer();
  recognition.onresult = (event) => {
    let interim = '';
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      const transcript = result[0]?.transcript || '';
      if (result.isFinal) appendFinalSegment(transcript);
      else interim = transcript;
    }
    renderSceneDictation(prompt, baseText, finalSegments, interim);
    resetSilenceTimer();
  };
  recognition.onerror = (event) => {
    if (event.error !== 'no-speech') toast('I could not hear that clearly.');
    stopSceneDictation();
  };
  recognition.onend = () => {
    if (worldState.sceneDictationTimer) {
      window.clearTimeout(worldState.sceneDictationTimer);
      worldState.sceneDictationTimer = null;
    }
    worldState.sceneRecognition = null;
    renderSceneDictation(prompt, baseText, finalSegments);
    setSceneDictationUi(false);
    prompt.focus();
  };
  recognition.start();
}
function normalizedVoiceTokens(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/[^a-z0-9\u0900-\u097f\s']/g, ' ')
    .split(/\s+/)
    .filter(Boolean);
}

function isMeaningfulVoiceText(text) {
  const tokens = normalizedVoiceTokens(text);
  if (!tokens.length) return false;
  const useful = tokens.filter((token) => !voiceNoiseTokens.has(token) && token.length > 1);
  if (useful.length >= 2) return true;
  if (useful.length === 1 && useful[0].length >= 5) return true;
  return false;
}
function voiceSubmitDelay(text) {
  const useful = normalizedVoiceTokens(text).filter((token) => !voiceNoiseTokens.has(token) && token.length > 1);
  if (useful.length >= 4 || /[.?!?]$/.test(String(text || '').trim())) return voiceFastSilenceMs;
  return voiceSilenceMs;
}

function clearNoiseTurnText(finalText, interimText) {
  if (isMeaningfulVoiceText(finalText)) return false;
  const visible = [finalText, interimText].filter(Boolean).join(' ').trim();
  if (visible && !isMeaningfulVoiceText(visible)) {
    $('#turnText').value = '';
    return true;
  }
  return false;
}
function clearVoiceInputTimer() {
  if (worldState.voiceInputTimer) {
    window.clearTimeout(worldState.voiceInputTimer);
    worldState.voiceInputTimer = null;
  }
}

function submitVoiceTextNow(text) {
  const cleanText = String(text || '').replace(/\s+/g, ' ').trim();
  if (!worldState.voiceMode || worldState.turnSubmitting || !isMeaningfulVoiceText(cleanText)) return false;
  const now = Date.now();
  if (worldState.lastVoiceSubmittedText === cleanText && now - worldState.lastVoiceSubmittedAt < 6000) return false;
  worldState.lastVoiceSubmittedText = cleanText;
  worldState.lastVoiceSubmittedAt = now;
  worldState.suppressRecognitionEndSubmit = true;
  if (worldState.recognition) {
    try { worldState.recognition.stop(); } catch (_) {}
    worldState.recognition = null;
  }
  $('#turnText').value = cleanText;
  setTurnRecordingUi('idle');
  $('#turnForm').requestSubmit();
  return true;
}

function queueVoiceTextSubmit(text) {
  clearVoiceInputTimer();
  const cleanText = String(text || '').replace(/\s+/g, ' ').trim();
  if (!isMeaningfulVoiceText(cleanText)) return;
  worldState.voiceInputTimer = window.setTimeout(() => {
    submitVoiceTextNow($('#turnText').value.trim() || cleanText);
  }, voiceSubmitDelay(cleanText));
}
function startAutoVoiceTurn() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    toggleTurnRecording(true);
    return;
  }
  if (worldState.recognition || worldState.turnSubmitting || worldState.audio) return;
  const recognition = new Recognition();
  worldState.recognition = recognition;
  recognition.lang = navigator.language || 'en-IN';
  recognition.interimResults = true;
  recognition.continuous = true;
  let finalText = '';
  let interimText = '';
  let submitTimer = null;
  let shouldSubmit = false;
  setTurnRecordingUi('recording');
  toast('Listening. Speak naturally; RoleBricks sends after a clear pause.');
  const currentVoiceText = () => [finalText, interimText]
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
  const queueSubmit = () => {
    window.clearTimeout(submitTimer);
    const delayText = currentVoiceText() || $('#turnText').value.trim();
    submitTimer = window.setTimeout(() => {
      const text = currentVoiceText() || $('#turnText').value.trim();
      if (!isMeaningfulVoiceText(text)) {
        clearNoiseTurnText(finalText, interimText);
        return;
      }
      shouldSubmit = true;
      submitVoiceTextNow(text);
    }, voiceSubmitDelay(delayText));
  };
  recognition.onresult = (event) => {
    interimText = '';
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      const transcript = result[0].transcript || '';
      if (result.isFinal) finalText += transcript + ' ';
      else interimText += transcript;
    }
    const visibleText = currentVoiceText();
    $('#turnText').value = visibleText;
    if (isMeaningfulVoiceText(visibleText)) {
      queueSubmit();
      queueVoiceTextSubmit(visibleText);
    }
    else clearNoiseTurnText(finalText, interimText);
  };
  recognition.onerror = () => {
    window.clearTimeout(submitTimer);
    worldState.recognition = null;
    setTurnRecordingUi('idle');
    const text = $('#turnText').value.trim();
    if (!submitVoiceTextNow(text)) scheduleAutoListen();
  };
  recognition.onend = () => {
    window.clearTimeout(submitTimer);
    worldState.recognition = null;
    const text = $('#turnText').value.trim();
    const suppressed = worldState.suppressRecognitionEndSubmit;
    worldState.suppressRecognitionEndSubmit = false;
    setTurnRecordingUi('idle');
    if (!suppressed && (shouldSubmit || isMeaningfulVoiceText(text)) && submitVoiceTextNow(text)) return;
    if (!isMeaningfulVoiceText(text)) $('#turnText').value = '';
    if (worldState.voiceMode && !worldState.turnSubmitting && !worldState.audio) scheduleAutoListen();
  };
  recognition.start();
}

function stopAutoVoiceTurn() {
  if (worldState.recognition) {
    const recognition = worldState.recognition;
    worldState.recognition = null;
    recognition.stop();
  }
}

function setTurnRecordingUi(state) {
  const button = $('#recordTurn');
  const recording = state === 'recording';
  const processing = state === 'processing';
  button.classList.toggle('is-recording', recording);
  button.disabled = processing || worldState.turnSubmitting;
  button.setAttribute('aria-label', recording ? 'Stop recording' : processing ? 'Processing recording' : 'Speak');
  button.setAttribute('title', recording ? 'Stop recording' : processing ? 'Processing recording' : 'Speak');
  button.innerHTML = `<i data-lucide="${recording ? 'square' : processing ? 'loader-circle' : 'mic'}"></i>`;
  $('#voiceWave').classList.toggle('is-recording', recording);
  refreshIcons();
}

async function toggleTurnRecording(autoStarted = false) {
  if (worldState.audio) stopWorldAudio();
  if (worldState.recognition) {
    stopAutoVoiceTurn();
    return;
  }
  if (worldState.recorder?.state === 'recording') {
    worldState.recorder.stop();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    toast('Microphone recording is not available in this browser.');
    return;
  }
  try {
    worldState.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(worldState.mediaStream);
    worldState.recorder = recorder;
    worldState.recordingChunks = [];
    recorder.addEventListener('dataavailable', (event) => {
      if (event.data.size) worldState.recordingChunks.push(event.data);
    });
    recorder.addEventListener('stop', transcribeTurnRecording, { once: true });
    recorder.start();
    setTurnRecordingUi('recording');
    toast(autoStarted ? 'Listening. Tap the square when you are done.' : 'Recording. Tap the square when you are done.');
    worldState.recordingTimer = window.setTimeout(() => {
      if (recorder.state === 'recording') recorder.stop();
    }, 60000);
  } catch (error) {
    toast(error.message || 'Microphone permission was not granted.');
  }
}

async function transcribeTurnRecording() {
  window.clearTimeout(worldState.recordingTimer);
  setTurnRecordingUi('processing');
  worldState.mediaStream?.getTracks().forEach((track) => track.stop());
  const type = worldState.recorder?.mimeType || 'audio/webm';
  const blob = new Blob(worldState.recordingChunks, { type });
  const form = new FormData();
  form.append('source_audio', blob, type.includes('ogg') ? 'turn.ogg' : 'turn.webm');
  try {
    const result = await api('/api/transcribe', { method: 'POST', body: form });
    $('#turnText').value = result.text;
    if (worldState.voiceMode && result.text.trim()) {
      $('#turnForm').requestSubmit();
    } else {
      $('#turnText').focus();
    }
  } catch (error) {
    toast(error.message);
  } finally {
    setTurnRecordingUi('idle');
    worldState.recorder = null;
    worldState.recordingChunks = [];
  }
}

function resetWorldComposer() {
  worldState.voiceMode = false;
  clearAutoListen();
  clearWorldPoll();
  stopWorldAudio();
  worldState.scene = null;
  setSceneHash(null);
  $('#scenePrompt').value = '';
  updatePromptCount();
  setWorldView('describe');
  loadRecentScenes();
}

function toggleVoiceMode() {
  if (worldState.scene?.status !== 'live') {
    toast('Enter a live scene before turning on voice mode.');
    return;
  }
  worldState.voiceMode = !worldState.voiceMode;
  updateVoiceModeUi();
  if (worldState.voiceMode) {
    toast('Voice mode is on. Speak naturally; it sends when you pause.');
    if (!worldState.audio) scheduleAutoListen();
  } else {
    clearAutoListen();
    stopAutoVoiceTurn();
    toast('Voice mode is off.');
  }
}

async function clearSceneHistory() {
  if (!worldState.scene || !confirm('Clear conversation history for this scene? Respondents and evidence stay.')) return;
  try {
    const scene = await api(`/api/worlds/${worldState.scene.id}/history`, { method: 'DELETE' });
    worldState.scene = scene;
    renderWorldScene(scene);
    $('#sceneManageDrawer')?.close();
    toast('Conversation history cleared.');
  } catch (error) { toast(error.message); }
}

async function clearSceneMemories() {
  if (!worldState.scene || !confirm('Clear learned respondent memories? Persona and evidence stay.')) return;
  try {
    const scene = await api(`/api/worlds/${worldState.scene.id}/memories`, { method: 'DELETE' });
    worldState.scene = scene;
    renderWorldScene(scene);
    $('#sceneManageDrawer')?.close();
    toast('Respondent memories cleared.');
  } catch (error) { toast(error.message); }
}

async function deleteCurrentScene() {
  if (!worldState.scene || !confirm('Delete this scene and its generated audio? This cannot be undone.')) return;
  const sceneId = worldState.scene.id;
  try {
    await api(`/api/worlds/${sceneId}`, { method: 'DELETE' });
    forgetScene(sceneId);
    $('#sceneManageDrawer')?.close();
    resetWorldComposer();
    toast('Scene deleted.');
  } catch (error) { toast(error.message); }
}

function bindWorldEvents() {
  $('#scenePromptForm')?.addEventListener('submit', createWorldScene);
  $('#scenePrompt')?.addEventListener('input', updatePromptCount);
  $('#dictateScene')?.addEventListener('click', startSceneDictation);
  $('#saveBlueprint')?.addEventListener('click', handleSaveBlueprint);
  $('#buildScene')?.addEventListener('click', handleBuildScene);
  $('#revertVersion')?.addEventListener('click', handleRevertVersion);
  $('#discardBlueprint')?.addEventListener('click', resetWorldComposer);
  $('#returnToBlueprint')?.addEventListener('click', () => renderBlueprint(worldState.scene));
  $('#enterScene')?.addEventListener('click', enterWorldScene);
  $('#turnForm')?.addEventListener('submit', submitWorldTurn);
  $('#turnText')?.addEventListener('input', (event) => {
    if (worldState.voiceMode) queueVoiceTextSubmit(event.target.value);
  });
  $('#pauseScene')?.addEventListener('click', togglePauseScene);
  $('#completeScene')?.addEventListener('click', completeWorldScene);
  $('#stopAudio')?.addEventListener('click', () => { stopWorldAudio(); toast('Voice stopped.'); });
  $('#recordTurn')?.addEventListener('click', () => toggleTurnRecording(false));
  $('#voiceModeToggle')?.addEventListener('click', toggleVoiceMode);
  $('#newScene')?.addEventListener('click', resetWorldComposer);
  $('#resumeScene')?.addEventListener('click', resumeCompletedScene);
  $('#closeEvidence')?.addEventListener('click', () => $('#evidenceDrawer').close());
  $('#manageScene')?.addEventListener('click', () => $('#sceneManageDrawer')?.showModal());
  $('#closeSceneManage')?.addEventListener('click', () => $('#sceneManageDrawer')?.close());
  $('#clearSceneHistory')?.addEventListener('click', clearSceneHistory);
  $('#clearSceneMemories')?.addEventListener('click', clearSceneMemories);
  $('#deleteScene')?.addEventListener('click', deleteCurrentScene);

  document.addEventListener('click', (event) => {
    const deleteRecentButton = event.target.closest('[data-delete-recent-scene]');
    if (deleteRecentButton) {
      deleteRecentScene(deleteRecentButton.dataset.deleteRecentScene);
      return;
    }

    const loadButton = event.target.closest('[data-load-scene]');
    if (loadButton) loadWorldScene(loadButton.dataset.loadScene).catch((error) => toast(error.message));

    const editButton = event.target.closest('[data-edit-cast]');
    if (editButton) {
      editButton.closest('.cast-row')?.classList.toggle('is-open');
      refreshIcons();
    }

    const audioButton = event.target.closest('[data-play-audio]');
    if (audioButton) playWorldAudio(audioButton.dataset.playAudio, audioButton.dataset.speakerKey);

    if (event.target.closest('[data-open-evidence]')) $('#evidenceDrawer').showModal();
  });

  document.addEventListener('change', (event) => {
    if (event.target.matches('[data-cast-selected]')) toggleCastSelection(event.target);
  });
}

if (page === 'worlds') {
  initializeWorlds().catch((error) => {
    toast(error.message);
    setWorldView('describe');
  });
}






