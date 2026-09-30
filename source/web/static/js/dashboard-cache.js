(() => {
  const notice = document.querySelector('[data-cache-status]');
  if (!notice) return;
  const timestamp = notice.querySelector('time');
  if (timestamp) {
    timestamp.textContent = new Date(timestamp.dateTime).toLocaleString('ko-KR');
  }
  // 새로고침 표식은 한 번만 사용한다. 자동 재표시 때 다시 갱신하지 않는다.
  const currentUrl = new URL(window.location.href);
  if (currentUrl.searchParams.has('refresh')) {
    currentUrl.searchParams.delete('refresh');
    window.history.replaceState(null, '', currentUrl);
  }
  if (notice.dataset.refreshing !== 'true') return;
  let failures = 0;
  const poll = async () => {
    if (document.hidden) {
      window.setTimeout(poll, 2000);
      return;
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(notice.dataset.statusUrl, {
        cache: 'no-store', signal: controller.signal,
      });
      if (!response.ok) throw new Error('상태 조회 실패');
      const state = await response.json();
      failures = 0;
      if (!state.refreshing) {
        window.location.reload();
        return;
      }
    } catch {
      if (++failures >= 5) {
        notice.querySelector('[data-cache-message]').textContent =
          '갱신 상태를 확인하지 못했습니다. 잠시 후 새로고침해 주세요.';
        return;
      }
    } finally {
      window.clearTimeout(timeout);
    }
    window.setTimeout(poll, 2000);
  };
  window.setTimeout(poll, 2000);
})();
