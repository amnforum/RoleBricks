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
  currentView: null
};

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
    const readiness = await api('/ready');
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
  try {
    const scenes = await api('/api/worlds?limit=6');
    const container = $('#recentScenes');
    const list = $('#recentSceneList');
    if (!container || !list || !scenes.length) return;
    list.innerHTML = scenes.map((scene) => `
      <button class="recent-scene" type="button" data-load-scene="${scene.id}">
        <strong>${escapeHtml(scene.manifest.title)}</strong>
        <span>${escapeHtml(scene.status.replace('_', ' '))}</span>
      </button>
    `).join('');
    container.classList.remove('is-hidden');
  } catch (_) {
    // A new workspace can legitimately have no scene tables until setup completes.
  }
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
  $('#castCount').textContent = `${selected} of 3 selected. Additional recommendations remain available.`;
}

function toggleCastSelection(input) {
  if (input.checked && $$('[data-cast-selected]:checked').length > 3) {
    input.checked = false;
    toast('This MVP supports up to three AI characters.');
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
  if (selectedCount < 1 || selectedCount > 3) {
    throw new Error('Select between one and three AI characters.');
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
    const opening = [...scene.turns].reverse().find((turn) => turn.speaker_type === 'agent' && turn.audio_url);
    if (opening) playWorldAudio(opening.audio_url, opening.speaker_key);
  } catch (error) {
    toast(error.message);
  } finally {
    setWorldBusy(button, false);
    refreshIcons();
  }
}

function renderLive(scene) {
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

  $('#sceneTranscript').innerHTML = scene.turns.map((turn) => `
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
  `).join('');
  const transcript = $('#sceneTranscript');
  requestAnimationFrame(() => { transcript.scrollTop = transcript.scrollHeight; });
  worldState.lastRenderedTurnId = scene.turns.at(-1)?.id || null;
  setWorldView('live');
}

async function submitWorldTurn(event) {
  event.preventDefault();
  const textInput = $('#turnText');
  const text = textInput.value.trim();
  if (!text) return;
  const button = event.currentTarget.querySelector('button[type="submit"]');
  setWorldBusy(button, true, '');
  textInput.disabled = true;
  try {
    const previousLastId = worldState.scene.turns.at(-1)?.id;
    const scene = await api(`/api/worlds/${worldState.scene.id}/turns`, {
      method: 'POST',
      body: JSON.stringify({ text })
    });
    worldState.scene = scene;
    textInput.value = '';
    renderLive(scene);
    const latest = scene.turns.at(-1);
    if (latest?.id !== previousLastId && latest?.audio_url) {
      playWorldAudio(latest.audio_url, latest.speaker_key);
    } else if (latest?.audio_data?.status === 'failed') {
      toast(`Voice was not generated: ${latest.audio_data.error}`);
    }
  } catch (error) {
    toast(error.message);
  } finally {
    textInput.disabled = worldState.scene?.status === 'paused';
    setWorldBusy(button, false);
    refreshIcons();
  }
}

async function togglePauseScene() {
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
  try {
    const scene = await api(`/api/worlds/${worldState.scene.id}/complete`, { method: 'POST' });
    worldState.scene = scene;
    stopWorldAudio();
    renderAfter(scene);
  } catch (error) {
    toast(error.message);
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
    list.innerHTML = '<p class="empty-evidence">This scene did not require fresh public sources. Canon and scene facts are stored separately from live research.</p>';
    return;
  }
  list.innerHTML = scene.sources.map((source) => `
    <a class="evidence-item" href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">
      <span>${escapeHtml(source.freshness)}</span>
      <strong>${escapeHtml(source.title)}</strong>
      <p>${escapeHtml(source.snippet)}</p>
    </a>
  `).join('');
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
  }, { once: true });
  audio.play().catch(() => toast('Press play again to hear the voice.'));
}

function stopWorldAudio() {
  if (worldState.audio) {
    worldState.audio.pause();
    worldState.audio.currentTime = 0;
    worldState.audio = null;
  }
}

function startSceneDictation() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    toast('Voice dictation is not available in this browser.');
    return;
  }
  const recognition = new Recognition();
  recognition.lang = navigator.language || 'en-IN';
  recognition.interimResults = true;
  const button = $('#dictateScene');
  button.classList.add('is-recording');
  recognition.onresult = (event) => {
    const text = Array.from(event.results).map((result) => result[0].transcript).join(' ');
    $('#scenePrompt').value = text;
    updatePromptCount();
  };
  recognition.onerror = () => toast('I could not hear that clearly.');
  recognition.onend = () => button.classList.remove('is-recording');
  recognition.start();
}

async function toggleTurnRecording() {
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
    $('#recordTurn').classList.add('is-recording');
    $('#voiceWave').classList.add('is-recording');
    worldState.recordingTimer = window.setTimeout(() => {
      if (recorder.state === 'recording') recorder.stop();
    }, 60000);
  } catch (error) {
    toast(error.message || 'Microphone permission was not granted.');
  }
}

async function transcribeTurnRecording() {
  window.clearTimeout(worldState.recordingTimer);
  $('#recordTurn').classList.remove('is-recording');
  $('#voiceWave').classList.remove('is-recording');
  worldState.mediaStream?.getTracks().forEach((track) => track.stop());
  const type = worldState.recorder?.mimeType || 'audio/webm';
  const blob = new Blob(worldState.recordingChunks, { type });
  const form = new FormData();
  form.append('source_audio', blob, type.includes('ogg') ? 'turn.ogg' : 'turn.webm');
  const button = $('#recordTurn');
  button.disabled = true;
  try {
    const result = await api('/api/transcribe', { method: 'POST', body: form });
    $('#turnText').value = result.text;
    $('#turnText').focus();
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    worldState.recorder = null;
    worldState.recordingChunks = [];
  }
}

function resetWorldComposer() {
  clearWorldPoll();
  stopWorldAudio();
  worldState.scene = null;
  setSceneHash(null);
  $('#scenePrompt').value = '';
  updatePromptCount();
  setWorldView('describe');
  loadRecentScenes();
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
  $('#pauseScene')?.addEventListener('click', togglePauseScene);
  $('#completeScene')?.addEventListener('click', completeWorldScene);
  $('#recordTurn')?.addEventListener('click', toggleTurnRecording);
  $('#newScene')?.addEventListener('click', resetWorldComposer);
  $('#resumeScene')?.addEventListener('click', resumeCompletedScene);
  $('#closeEvidence')?.addEventListener('click', () => $('#evidenceDrawer').close());

  document.addEventListener('click', (event) => {
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
