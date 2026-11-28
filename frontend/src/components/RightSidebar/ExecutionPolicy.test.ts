import { describe, expect, it } from 'vitest'
import { cleanResources } from './ExecutionPolicy'

describe('cleanResources', () => {
  it('drops empty and zero requests', () => {
    expect(cleanResources({ cpu: 2, memory_gb: null, gpu: 0 })).toEqual({ cpu: 2 })
    expect(cleanResources({ cpu: null, gpu: Number.NaN })).toBeNull()
  })
})
