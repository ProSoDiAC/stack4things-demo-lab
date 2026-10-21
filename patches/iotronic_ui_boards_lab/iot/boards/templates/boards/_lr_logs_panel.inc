{% load i18n %}

<div class="detail lr-log-view{% if single_board %} lr-log-view-single{% endif %}">
  {% if help_text %}
  <p class="text-muted">{{ help_text }}</p>
  {% else %}
  <p class="text-muted">
    {% trans "Lightning-Rod container logs (auto-detected). New boards appear after LR registration (~45s cache)." %}
  </p>
  {% endif %}
  <div class="btn-toolbar" style="margin-bottom: 12px;">
    <button type="button" class="btn btn-default btn-sm fl-lr-logs-refresh">
      <span class="fa fa-refresh"></span> {% trans "Refresh" %}
    </button>
    <label class="checkbox-inline" style="margin-left: 12px;">
      <input type="checkbox" class="fl-lr-logs-autorefresh" checked>
      {% trans "Auto-refresh (10s)" %}
    </label>
    <span class="text-muted fl-lr-logs-status" style="margin-left: 8px;"></span>
  </div>

  {% if log_panels %}
    {% for panel in log_panels %}
    <div class="panel panel-default fl-lr-log-panel">
      <div class="panel-heading fl-lr-log-heading">
        <strong>{{ panel.board_name }}</strong>
        {% if panel.container %}
          <span class="text-muted"> — {{ panel.container }}</span>
        {% endif %}
      </div>
      <pre class="fl-lr-log-pre" data-board="{{ panel.board_name }}" data-uuid="{{ panel.board_uuid|default:'' }}">{{ panel.text }}</pre>
    </div>
    {% endfor %}
  {% else %}
  <p class="text-warning">{% trans "No log data." %}</p>
  {% endif %}
</div>

<script>
(function() {
  var root = document.querySelector('.lr-log-view');
  if (!root) return;
  var ajaxUrl = "{{ logs_ajax_url|escapejs }}";
  var tail = {{ log_tail|default:40 }};
  var timer = null;
  function setStatus(msg) {
    var el = root.querySelector('.fl-lr-logs-status');
    if (el) el.textContent = msg || '';
  }
  function renderLogs(data) {
    var boards = (data && data.boards) ? data.boards : {};
    root.querySelectorAll('.fl-lr-log-pre').forEach(function(pre) {
      var name = pre.getAttribute('data-board');
      var uid = pre.getAttribute('data-uuid');
      var entry = boards[name] || boards[uid];
      if (!entry) return;
      pre.textContent = (entry.lines || []).join('\n');
    });
  }
  function refreshLogs() {
    if (!ajaxUrl) return;
    var url = ajaxUrl + '?tail=' + encodeURIComponent(tail) + '&refresh=1';
    setStatus('{% trans "Loading..." %}');
    var xhr = new XMLHttpRequest();
    xhr.open('GET', url, true);
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.onload = function() {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { renderLogs(JSON.parse(xhr.responseText)); setStatus(new Date().toLocaleTimeString()); }
        catch (e) { setStatus('{% trans "Parse error" %}'); }
      } else { setStatus('HTTP ' + xhr.status); }
    };
    xhr.onerror = function() { setStatus('{% trans "Network error" %}'); };
    xhr.send();
  }
  function setupAutoRefresh() {
    if (timer) { clearInterval(timer); timer = null; }
    var chk = root.querySelector('.fl-lr-logs-autorefresh');
    if (chk && chk.checked) timer = setInterval(refreshLogs, 10000);
  }
  var btn = root.querySelector('.fl-lr-logs-refresh');
  if (btn) btn.addEventListener('click', refreshLogs);
  var auto = root.querySelector('.fl-lr-logs-autorefresh');
  if (auto) auto.addEventListener('change', setupAutoRefresh);
  setupAutoRefresh();
})();
</script>

<style>
  .lr-log-view .fl-lr-log-pre {
    margin: 0; padding: 10px 12px; max-height: 360px; overflow: auto;
    background: #0b1220; color: #cbd5e1; border: 0;
    font-family: "DejaVu Sans Mono", "Consolas", monospace;
    font-size: 11px; line-height: 1.45; white-space: pre-wrap; word-break: break-word;
  }
  .lr-log-view-single .fl-lr-log-pre { max-height: 520px; }
  .lr-log-view .fl-lr-log-panel { margin-bottom: 12px; }
  .lr-log-view .fl-lr-log-heading {
    background: #1e293b; color: #e2e8f0; border-color: #334155; font-family: monospace; font-size: 12px;
  }
</style>
