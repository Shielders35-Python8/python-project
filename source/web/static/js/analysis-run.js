(() => {
  const script = document.querySelector('script[data-run-url]');
  if (!script) return;
  let state = JSON.parse(document.getElementById('analysis-state').textContent);
  const button = document.querySelector('[data-run-button]');
  const active = run => run && ['queued', 'running'].includes(run.status);
  const labels = {queued: '시작 대기', running: '분석 중', succeeded: '완료', failed: '실패'};
  const stages = {loading: 'Notion 조회 중', comparing: '버전 판정 중', saving: 'Notion 저장 중'};
  let submitting = false;
  let timer;
  let previous = state.current;
  const text = (selector, value) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = value;
  };
  const date = value => value ? new Date(value).toLocaleString('ko-KR') : '—';
  const render = () => {
    const run = state.current;
    if (button) button.disabled = submitting || active(run);
    text('[data-run-button-label]', submitting ? '시작 요청 중' : active(run) ? '분석 진행 중' : '분석 실행');
    text('[data-run-status]', run ? stages[run.stage] || labels[run.status] : '대기');
    text('[data-run-started]', run ? date(run.started_at) : '아직 실행 기록이 없습니다.');
    text('[data-run-message]', run ? run.message : '분석을 실행하면 진행 상태를 표시합니다.');
    text('[data-run-counts]', run && run.package_count !== null
      ? `공지 ${run.advisory_count}행 · 검사 ${run.package_count}개 · 취약 ${run.affected_count}개 · 알 수 없음 ${run.unknown_count}개 · 저장 ${run.updated_count}/${run.total_updates}개`
      : '');
    const link = document.querySelector('[data-run-results]');
    if (link) link.hidden = !run || active(run);
    const history = document.querySelector('[data-run-history]');
    if (history) {
      document.querySelector('[data-run-history-empty]').hidden = state.history.length > 0;
      document.querySelector('[data-run-history-table]').hidden = !state.history.length;
      history.replaceChildren(...state.history.map(item => {
        const row = document.createElement('tr');
        for (const value of [date(item.started_at), date(item.finished_at), labels[item.status],
          item.affected_count ?? '—', item.unknown_count ?? '—',
          `${item.updated_count}/${item.total_updates ?? '—'}`]) {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.append(cell);
        }
        return row;
      }));
    }
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
      const current = state.current;
      const finished = current && !active(current) &&
        (active(previous) || (previous && previous.id !== current.id) || !previous);
      previous = current;
      if (finished && script.dataset.refreshResults === 'true') {
        // Notion 저장 후 기존 조회 캐시도 갱신한다. 날짜/취약도/페이지 필터는 유지한다.
        const url = new URL(window.location.href);
        url.searchParams.set('refresh', '1');
        window.location.replace(url);
        return;
      }
    } catch {
      text('[data-run-message]', '실행 상태를 확인하지 못했습니다. 연결이 복구되면 다시 확인합니다.');
    }
    timer = window.setTimeout(poll, active(state.current) ? 1500 : 5000);
  };
  button?.addEventListener('click', async () => {
    if (submitting || active(state.current)) return;
    submitting = true;
    let startError;
    render();
    try {
      const {response, body} = await request(script.dataset.runUrl, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
      });
      if (response.status !== 202 && response.status !== 409) throw new Error(body.message || '분석 시작 요청에 실패했습니다.');
      state.current = body.run;
      state.history = [body.run, ...state.history.filter(item => item.id !== body.run.id)].slice(0, 20);
      previous = body.run;
    } catch (error) {
      // 응답을 놓쳤더라도 서버는 실행 중일 수 있으므로 POST를 자동으로 재전송하지 않는다.
      startError = `${error.message || '시작 응답을 확인하지 못했습니다.'} 실행 상태를 다시 확인합니다.`;
    } finally {
      submitting = false;
      render();
      if (startError) {
        text('[data-run-message]', startError);
        window.clearTimeout(timer);
        timer = window.setTimeout(poll, 1500);
      } else {
        poll();
      }
    }
  });
  render();
  timer = window.setTimeout(poll, active(state.current) ? 500 : 3000);
})();
