const opsState = { timer: null };

function formatOpsNumber(value) {
  return new Intl.NumberFormat().format(Number(value || 0));
}

function formatOpsSeconds(value) {
  return value === null || value === undefined ? 'No data' : `${Number(value).toFixed(value < 10 ? 2 : 1)} s`;
}

function renderOpsProvider(provider) {
  return `
    <div class="provider-row ${provider.ready ? 'is-active' : 'is-down'}">
      <span class="provider-light" aria-hidden="true"></span>
      <div>
        <strong>${escapeHtml(provider.label)}</strong>
        <span>${provider.ready ? 'Active' : provider.configured ? 'Unavailable' : 'Needs setup'}</span>
      </div>
      <em>${provider.required ? 'Required' : 'Standby'}</em>
    </div>
  `;
}

function renderOps(data) {
  const healthy = data.overall === 'healthy';
  const overall = $('#opsOverall');
  overall.classList.toggle('is-healthy', healthy);
  overall.querySelector('strong').textContent = healthy ? 'All required systems active' : 'Attention required';
  $('#opsTimestamp').textContent = `Updated ${new Date(data.generated_at).toLocaleTimeString()} - ${escapeHtml(data.viewer)}`;

  const status = $('#providerStatus');
  status.classList.toggle('ready', healthy);
  status.classList.toggle('not-ready', !healthy);
  status.querySelector('span').textContent = healthy ? 'Operations healthy' : 'Operations degraded';

  $('#metricScenes').textContent = formatOpsNumber(data.usage.scenes_total);
  $('#metricScenesDay').textContent = `${formatOpsNumber(data.usage.scenes_24h)} today`;
  $('#metricAgents').textContent = formatOpsNumber(data.usage.agents_total);
  $('#metricTurns').textContent = formatOpsNumber(data.usage.turns_24h);
  $('#metricTokens').textContent = formatOpsNumber(data.usage.tokens_recorded.total_tokens);
  $('#providerList').innerHTML = data.providers.map(renderOpsProvider).join('');

  $('#sceneMedian').textContent = formatOpsSeconds(data.latency.scene_prepare_median_seconds);
  $('#sceneP95').textContent = formatOpsSeconds(data.latency.scene_prepare_p95_seconds);
  $('#turnMedian').textContent = formatOpsSeconds(data.latency.turn_median_seconds);
  $('#turnP95').textContent = formatOpsSeconds(data.latency.turn_p95_seconds);
  $('#queueDepth').textContent = formatOpsNumber(data.queue.depth);
  $('#queueWorkers').textContent = formatOpsNumber(data.queue.workers);
  $('#queueRunning').textContent = formatOpsNumber(data.queue.running_jobs);
  $('#cacheRate').textContent = `${Number(data.cache.hit_rate_percent || 0).toFixed(1)}%`;

  $('#voiceBalance').innerHTML = data.voice_balance.length
    ? data.voice_balance.map((item) => `
        <div class="balance-row">
          <strong>${escapeHtml(item.engine)}</strong>
          <span>${formatOpsNumber(item.calls_24h)} calls</span>
          <span>${Number(item.audio_seconds_24h).toFixed(1)} s</span>
        </div>
      `).join('')
    : '<div class="ops-empty">No voice calls recorded in the last 24 hours.</div>';

  $('#failureList').innerHTML = data.failures.recent_builds.length
    ? data.failures.recent_builds.map((item) => `
        <div class="failure-row">
          <strong>${escapeHtml(item.reason)}</strong>
          <span>${escapeHtml(item.stage.replaceAll('_', ' '))} - ${new Date(item.time).toLocaleString()}</span>
        </div>
      `).join('')
    : '<div class="ops-empty">No recent scene build exceptions.</div>';
  window.lucide?.createIcons();
}

async function loadOps() {
  const refresh = $('#refreshOps');
  refresh.disabled = true;
  refresh.classList.add('is-loading');
  try {
    renderOps(await api('/api/admin/overview'));
  } catch (error) {
    const overall = $('#opsOverall');
    overall.classList.remove('is-healthy');
    overall.querySelector('strong').textContent = 'Observability unavailable';
    $('#opsTimestamp').textContent = error.message;
    toast(error.message);
  } finally {
    refresh.disabled = false;
    refresh.classList.remove('is-loading');
  }
}

$('#refreshOps')?.addEventListener('click', loadOps);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) loadOps();
});

if (page === 'admin') {
  window.lucide?.createIcons();
  loadOps();
  opsState.timer = window.setInterval(() => {
    if (!document.hidden) loadOps();
  }, 15000);
}
