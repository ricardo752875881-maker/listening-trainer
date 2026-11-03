export async function request(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(body.detail || `request failed: ${res.status}`)
  }
  return body
}

export function get(path) {
  return request(path)
}

export function put(path, data) {
  return request(path, { method: 'PUT', body: JSON.stringify(data) })
}

export function patch(path, data) {
  return request(path, { method: 'PATCH', body: JSON.stringify(data) })
}

export function post(path, data) {
  return request(path, { method: 'POST', body: JSON.stringify(data) })
}

export function del(path, data) {
  return request(path, { method: 'DELETE', body: JSON.stringify(data) })
}

// 导入进度轮询：轮询直至任务进入终态（done/cancelled/error）
export async function pollJob(jobId, { intervalMs = 1000, signal } = {}) {
  const path = `/api/import/jobs/${jobId}`
  for (;;) {
    const job = await get(path)
    if (['done', 'cancelled', 'error'].includes(job.stage)) {
      return job
    }
    if (signal?.aborted) {
      return job
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}
