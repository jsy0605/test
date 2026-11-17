export function bindLogReset({request, writeOptions, onReset, root = document}) {
  const dialog = root.querySelector('#log-reset-dialog');
  const form = root.querySelector('#log-reset-form');
  const open = root.querySelector('#open-log-reset');
  const cancel = root.querySelector('#cancel-log-reset');
  const confirm = root.querySelector('#confirm-log-reset');
  const description = root.querySelector('#log-reset-description');
  const message = root.querySelector('#log-reset-message');
  const result = root.querySelector('#log-reset-result');
  let expectedCount = null, generation = 0, deleting = false, preview = null;
  open.addEventListener('click', async () => {
    if (dialog.open) return;
    const current = ++generation;
    expectedCount = null;
    confirm.disabled = true;
    confirm.textContent = '전체 기록 삭제';
    message.textContent = ''; result.textContent = '';
    description.textContent = '전체 로그 건수를 확인하고 있습니다…';
    dialog.showModal();
    preview = new AbortController();
    try {
      // 필터와 페이지를 제외하고 전체 DB 로그 건수를 조회합니다.
      const data = await request('/api/logs?limit=1', {signal:preview.signal});
      if (!dialog.open || current !== generation) return;
      expectedCount = data.total;
      description.textContent = `DB의 전체 로봇 로그 ${expectedCount}건을 삭제합니다. 검색 결과뿐 아니라 모든 로봇 로그이 대상입니다.`;
      confirm.textContent = `${expectedCount}건 전체 삭제`;
      confirm.disabled = expectedCount === 0;
      if (!expectedCount) message.textContent = 'DB 로그가 이미 비어 있습니다.';
    } catch (error) {
      if (dialog.open && current === generation) message.textContent = error.message || '로그 건수를 확인하지 못했습니다.';
    }
  });
  cancel.addEventListener('click', () => {if (!deleting) dialog.close();});
  dialog.addEventListener('cancel', event => {if (deleting) event.preventDefault();});
  dialog.addEventListener('close', () => {generation++; preview?.abort(); expectedCount = null;});
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (deleting || expectedCount === null || expectedCount === 0) return;
    deleting = true; open.disabled = confirm.disabled = cancel.disabled = true;
    message.textContent = 'DB 로그를 초기화하고 있습니다…';
    try {
      const data = await request('/api/logs', writeOptions('DELETE', {confirm:'RESET_LOGS', expected_count:expectedCount}));
      dialog.close();
      result.textContent = `DB 로봇 로그 ${data.deleted}건을 삭제했습니다.`;
      await onReset();
    } catch (error) {
      message.textContent = error.message || '초기화하지 못했습니다. 창을 닫고 다시 확인해 주세요.';
      // 실패 뒤에는 대상을 다시 조회한 후에만 삭제할 수 있습니다.
      expectedCount = null;
    } finally {
      deleting = false; open.disabled = cancel.disabled = false; confirm.disabled = true;
    }
  });
}
