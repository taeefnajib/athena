import { describe, expect, it } from 'vitest'
import { looksLocal } from './KServeSection'

describe('looksLocal', () => {
  it('flags images a cluster cannot pull', () => {
    expect(looksLocal('churn-model:latest')).toBe(true)
    expect(looksLocal('me/churn-model:1')).toBe(false)  // Docker Hub
    expect(looksLocal('ghcr.io/me/churn-model:1')).toBe(false)
    expect(looksLocal('registry:5000/m:1')).toBe(false)
    expect(looksLocal('localhost/m:1')).toBe(false)
    expect(looksLocal('')).toBe(false)
  })
})
