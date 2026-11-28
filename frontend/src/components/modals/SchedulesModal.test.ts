import { describe, expect, it } from 'vitest'
import { CRON_PRESETS, formatWhen } from './SchedulesModal'

describe('schedules helpers', () => {
  it('offers only five-field cron presets', () => {
    for (const [, cron] of CRON_PRESETS) expect(cron.trim().split(/\s+/)).toHaveLength(5)
  })

  it('formats local times and passes through what it cannot read', () => {
    expect(formatWhen(null)).toBe('—')
    expect(formatWhen('not a date')).toBe('not a date')
    expect(formatWhen('2026-11-29T02:30:00')).toMatch(/02:30/)
  })
})
