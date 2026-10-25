// Harness code-mode adapter. Supply `tools` and `options` as function arguments.
// No models, routing, PR classification, or provider subprocesses live here.
return (async () => {
  const allowed = new Set([
    'orchestrator_capabilities', 't3_thread_list', 'link_pull_request',
    'delegate_task', 'task_status', 'watch_pull_request'
  ]);
  if (!Array.isArray(options.argv) || options.argv.some(a => typeof a !== 'string' || !a)) {
    throw new Error('Bridge requires literal argv strings');
  }
  const quote = s => "'" + s.replace(/'/g, "'\\''") + "'";
  const start = Date.now();
  const deadline = options.deadlineMs ?? 900000;
  let pid = null, sessionId = null, buffer = '', requests = 0, result = null;
  let next = await tools.exec_command({
    cmd: options.argv.map(quote).join(' '), workdir: options.workdir,
    tty: true, yield_time_ms: 1000, max_output_tokens: 10000
  });
  try {
    for (let step = 0; step < 2000; step++) {
      sessionId = next.session_id ?? sessionId;
      buffer += next.output.replace(/\r\n/g, '\n');
      const lines = buffer.split('\n');
      buffer = lines.pop();
      let response = null;
      for (const line of lines) {
        if (line.startsWith('T3_READY ')) {
          const ready = JSON.parse(line.slice(9));
          if (!Number.isSafeInteger(ready.pid) || ready.pid <= 1) throw new Error('Invalid owned PID');
          pid = ready.pid;
        } else if (line.startsWith('T3_CALL ')) {
          if (response !== null || !pid) throw new Error('Invalid bridge request sequence');
          const request = JSON.parse(line.slice(8));
          if (!allowed.has(request.tool)) throw new Error('Tool outside the bridge allowlist');
          const fn = tools['mcp__t3_code__' + request.tool];
          if (typeof fn !== 'function') throw new Error('T3 tool unavailable: ' + request.tool);
          if (Date.now() - start > deadline) throw new Error('Bridge deadline');
          requests++;
          try {
            response = await fn(request.arguments);
          } catch (_) {
            response = {isError: true, content: [{type: 'text', text: 'host-tool-call-failed'}]};
          }
        } else if (line.startsWith('T3_RESULT ')) {
          result = JSON.parse(line.slice(10));
        } else if (line.trim()) {
          // Fail closed on truncated protocol output or accidental command noise.
          throw new Error('Unexpected bridge output');
        }
      }
      if (next.exit_code !== undefined) {
        if (buffer.trim() || result === null) throw new Error('Missing complete bridge result');
        return {exit_code: next.exit_code, tool_requests: requests, result};
      }
      // Always deliver an already-returned host receipt, even if that call crossed
      // the deadline. Python must retain its task ID before we stop new requests.
      if (!sessionId || (response === null && Date.now() - start > deadline)) {
        throw new Error('Bridge deadline or session gap');
      }
      next = await tools.write_stdin({
        session_id: sessionId, chars: response === null ? '' : JSON.stringify(response) + '\n',
        yield_time_ms: 1000, max_output_tokens: 10000
      });
    }
    throw new Error('Bridge step budget');
  } catch (error) {
    // The PID came from this exact helper's READY record. Writer reservations
    // survive interruption; a lost launch response never permits another writer.
    if (pid && next.exit_code === undefined) {
      await tools.exec_command({cmd: 'kill ' + pid, workdir: options.workdir, max_output_tokens: 1000});
    }
    throw error;
  }
})();
