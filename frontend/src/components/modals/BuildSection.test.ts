import { describe, expect, it } from 'vitest'
import { buildSummary, type BuildStatus } from './BuildSection'

const base: BuildStatus = { target: 'docker', state: 'running', tag: 'churn:latest', started: 100, finished: null, command: 'docker build -t churn:latest .', run_command: '', log: [] }

describe('buildSummary', () => {
  it('says when nothing was built', () => {
    expect(buildSummary(null)).toEqual({ tone: 'none', text: 'Not built yet.' })
  })
  it('describes each state', () => {
    expect(buildSummary(base).text).toBe('Building the Docker image…')
    expect(buildSummary({ ...base, state: 'succeeded', finished: 142.4 })).toEqual({ tone: 'ok', text: 'Built Docker image churn:latest in 42 s.' })
    expect(buildSummary({ ...base, target: 'bento', state: 'failed', tag: '', finished: 103 }).text).toBe('The Bento build failed in 3 s: see the log.')
    expect(buildSummary({ ...base, state: 'cancelled', finished: 101 }).tone).toBe('bad')
  })
})
