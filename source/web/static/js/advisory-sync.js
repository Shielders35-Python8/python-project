(() => {
  const script = document.querySelector('script[data-sync-url]');
  if (!script) return;
  let state = JSON.parse(document.getElementById('sync-state').textContent);
  const form = document.querySelector('[data-sync-form]');
  const button = document.querySelector('[data-sync-button]');
  const start = form?.elements.started_at;
  const end = form?.elements.ended_at;
  const active = run => run && ['queued', 'running'].includes(run.status);
  const labels = {queued: '시작 대기', running: '수집 중', succeeded: '완료', partial: '일부 저장 실패', failed: '실패'};
  const stages = {fetching: 'GitHub 수집 중', deduplicating: '중복 확인 중', saving: 'Notion 저장 중'};
  let submitting = false;
  let previous = state.current;
  let timer;
  const text = (selector, value) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = value;
  };
  const showError = message => {
    const element = document.querySelector('[data-sync-error]');
    if (element) {
      element.textContent = message;
      element.hidden = !message;
    }
  };
  const render = () => {
    const run = state.current;
    const busy = submitting || Boolean(active(run));
    if (form) {
      for (const element of form.elements) element.disabled = busy;
      form.setAttribute('aria-busy', String(busy));
    }
    if (button) button.textContent = submitting ? '시작 요청 중' : active(run) ? '공지 수집 중' : '신규 공지 가져오기';
    text('[data-sync-status]', run ? stages[run.stage] || labels[run.status] : '대기');
    text('[data-sync-message]', run ? run.message : '기간을 선택해 신규 공지를 가져오세요.');
    text('[data-sync-period]', run ? `최근 수집 기간 ${run.period_start} ~ ${run.period_end} (UTC)` : '');
    text('[data-sync-counts]', run && run.fetched !== null
      ? `수집 ${run.fetched}건 · 중복 등 제외 ${run.skipped ?? '—'}건 · 저장 ${run.inserted}/${run.total ?? '—'}건 · 실패 ${run.failed_count}건`
      : '');
    const link = document.querySelector('[data-sync-results]');
    if (link) link.hidden = !run || Boolean(active(run));
  };
  const request = async (url, options = {}) => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(url, {...options, cache: 'no-store', signal: controller.signal});
      return {response, body: await response.json()};
    } finally {
      window.clearTimeout(timeout);
    }
  };
  const poll = async () => {
    window.clearTimeout(timer);
    try {
      const {response, body} = await request(script.dataset.statusUrl);
      if (!response.ok) throw new Error();
      state = body;
      render();
      const run = state.current;
      const finished = run && !active(run) && (!previous || previous.id !== run.id || active(previous));
      previous = run;
      if (finished && script.dataset.refreshAdvisories === 'true') {
        const url = new URL(window.location.href);
        url.searchParams.set('refresh', '1');
        window.location.replace(url);
        return;
      }
    } catch {
      text('[data-sync-message]', '수집 상태를 확인하지 못했습니다. 연결이 복구되면 다시 확인합니다.');
    }
    timer = window.setTimeout(poll, active(state.current) ? 1500 : 5000);
  };
  const validate = () => {
    end.setCustomValidity(start.value && end.value && start.value > end.value
      ? '시작일은 종료일보다 늦을 수 없습니다.' : '');
  };
  start?.addEventListener('input', validate);
  end?.addEventListener('input', validate);
  form?.addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting || active(state.current)) return;
    validate();
    if (!form.reportValidity()) return;
    const period = {started_at: start.value, ended_at: end.value};
    submitting = true;
    showError('');
    render();
    try {
      const {response, body} = await request(script.dataset.syncUrl, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(period),
      });
      if (![202, 409].includes(response.status)) throw new Error(body.message || '수집 시작 요청에 실패했습니다.');
      state.current = body.run;
      previous = body.run;
      start.value = body.run.period_start;
      end.value = body.run.period_end;
    } catch (error) {
      // 응답을 놓쳐도 수집은 실행 중일 수 있어 POST를 자동으로 재시도하지 않는다.
      showError(`${error.message || '시작 응답을 확인하지 못했습니다.'} 수집 상태를 다시 확인합니다.`);
    } finally {
      submitting = false;
      render();
      poll();
    }
  });
  render();
  timer = window.setTimeout(poll, active(state.current) ? 500 : 3000);
})();
