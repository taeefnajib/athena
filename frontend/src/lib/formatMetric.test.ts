import { describe, expect, it } from 'vitest'
import { formatMetric } from './formatMetric'

describe('formatMetric', () => {
  it('shows ratios as percentages', () => {
    expect(formatMetric('accuracy', 0.9333)).toBe('93.3%')
    expect(formatMetric('pr_auc', 0.81)).toBe('81.0%')
    expect(formatMetric('mean_coverage', 0.884)).toBe('88.4%')
    expect(formatMetric('f1_at_0.5', 0.41)).toBe('41.0%')
  })
  it('keeps other scores as numbers', () => {
    expect(formatMetric('mase', 0.849)).toBe('0.849')
    expect(formatMetric('silhouette', 0.5441)).toBe('0.5441')
    expect(formatMetric('mae', 5.386)).toBe('5.386')
    expect(formatMetric('rmse', 0.8)).toBe('0.8')
    expect(formatMetric('calinski_harabasz', 815.467)).toBe('815.5')
    expect(formatMetric('llr_pvalue', 1.2e-9)).toBe('1.200e-9')
  })
  it('handles percent units, counts and non-finite values', () => {
    expect(formatMetric('mape', 1.861)).toBe('1.86%')
    expect(formatMetric('k', 4)).toBe('4')
    expect(formatMetric('horizon', 28)).toBe('28')
    expect(formatMetric('mae', Number.NaN)).toBe('–')
  })
})
