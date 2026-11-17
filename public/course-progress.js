// Live sync steps for instructor course requests (create, edit, sync).
//
// CourseProgress.request() asks /api/instructor/courses to stream its progress
// (newline-delimited JSON) and resolves with the final response body, the same as
// a plain JSON request. CourseProgress.panel() shows each source's current step
// with a spinner, and a check once that source has finished.
(function () {
  const SOURCE_LABELS = {
    gradescope: 'Gradescope',
    website: 'Course Website',
    save: 'AutoRemind',
  };

  function errorFrom(status, body) {
    return new Error(body?.error || `Request failed (${status})`);
  }

  async function readJson(response) {
    const text = await response.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error('AutoRemind could not read the server response. Refresh the page and try again.');
    }
    if (!response.ok) throw errorFrom(response.status, data);
    return data;
  }

  async function request(url, init = {}, onProgress = () => {}) {
    const response = await fetch(url, {
      ...init,
      headers: { ...(init.headers || {}), 'X-Course-Progress': 'stream' },
    });
    const type = response.headers.get('Content-Type') || '';
    if (!type.includes('application/x-ndjson') || !response.body) return readJson(response);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffered = '';
    let result = null;
    const handleLine = line => {
      if (!line.trim()) return;
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        return;
      }
      if (event.type === 'progress') {
        try { onProgress(event); } catch (error) { console.error(error); }
      } else if (event.type === 'result') {
        result = event;
      }
    };
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffered += decoder.decode(value, { stream: true });
      const lines = buffered.split('\n');
      buffered = lines.pop();
      lines.forEach(handleLine);
    }
    handleLine(buffered + decoder.decode());

    if (!result) throw new Error('The connection closed before the course finished syncing. Refresh the page to check whether it was saved.');
    if (result.status >= 400) throw errorFrom(result.status, result.body);
    return result.body;
  }

  function panel(container) {
    const rows = new Map();

    function row(source) {
      if (rows.has(source)) return rows.get(source);
      const element = document.createElement('div');
      element.className = 'course-progress-row';
      element.innerHTML = '<span class="course-progress-icon" aria-hidden="true"></span>' +
        '<span class="course-progress-text"><strong></strong> <span></span></span>';
      element.querySelector('strong').textContent = SOURCE_LABELS[source] || source;
      container.appendChild(element);
      const entry = { element, message: element.querySelector('.course-progress-text > span'), timer: null };
      rows.set(source, entry);
      return entry;
    }

    // Every step reads as a sentence: "Loading the course website."
    const sentence = text => (/[.!?…]$/.test(text) ? text : `${text}.`);

    // A website step that runs long (reading, matching, or waiting on the model) gets a
    // reassurance after this long, so the row never looks stuck.
    const SLOW_STEP_MS = 10 * 1000;
    const SLOW_STEP_NOTE = 'This can take a minute.';

    function clearSlowNote(entry) {
      clearTimeout(entry.timer);
      entry.timer = null;
    }

    function clearAll() {
      rows.forEach(clearSlowNote);
      rows.clear();
      container.innerHTML = '';
    }

    function setMessage(source, message) {
      const entry = row(source);
      clearSlowNote(entry);
      const text = `· ${sentence(message)}`;
      entry.message.textContent = text;
      if (source === 'website') {
        entry.timer = setTimeout(() => {
          entry.timer = null;
          entry.message.textContent = `${text} ${SLOW_STEP_NOTE}`;
        }, SLOW_STEP_MS);
      }
    }

    return {
      // sources: the ones this request will sync, e.g. ['gradescope', 'website'].
      start(sources) {
        clearAll();
        container.innerHTML = '';
        container.hidden = !sources.length;
        sources.forEach(source => setMessage(source, 'Starting…'));
      },
      handle(event) {
        if (!event?.source) return;
        container.hidden = false;
        if (event.source === 'save') {
          // Saving starts only once every source has finished.
          rows.forEach(entry => { clearSlowNote(entry); entry.element.classList.add('is-done'); });
        }
        if (event.message) setMessage(event.source, event.message);
        if (event.done) {
          const entry = row(event.source);
          clearSlowNote(entry);
          entry.element.classList.add('is-done');
        }
      },
      stop() {
        clearAll();
        container.hidden = true;
      },
    };
  }

  window.CourseProgress = { request, panel };
})();
